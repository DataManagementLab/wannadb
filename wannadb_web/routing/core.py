"""
core_routes Module

This module defines Flask routes for the 'core' functionality of the Wannadb UI.

It includes a Blueprint named 'core_routes' with routes related to creating document bases.

Routes:
    - /core/create_document_base (POST): Endpoint for creating a document base.


Dependencies:
    - Flask: Web framework for handling HTTP requests and responses.
    - config.tokenDecode: Function for decoding authorization tokens.
    - wannadb_ui.wannadb_api.WannaDBAPI: API for interacting with Wannadb.

Example:
    To create a Flask app and register the 'core_routes' Blueprint:

    ```python
    from flask import Flask
    from core_routes import core_routes

    app = Flask(__name__)
    app.register_blueprint(core_routes)
    ```

Author: Leon Wenderoth
"""
import asyncio
import logging.config
import pickle
from uuid import UUID
from typing import Optional

from wannadb_web.postgres.queries import get_document_base_data, get_document_by_name_and_content, get_feedbacks_for_document, get_document_by_name, get_base_id, get_organisation_authorisation, documents_available_for_base
from wannadb_web.postgres.transactions import add_feedback, add_document_base, delete_document_base_data

from flask import Blueprint, make_response, request, g, abort
from celery.result import AsyncResult
from wannadb.data.data import Attribute, Document, InformationNugget, DocumentBase
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache, TaskAccess, SessionState
from wannadb_web.util import tokenDecode
from wannadb_web.worker.data import Signals

from wannadb_web.worker.tasks import CreateDocumentBase, BaseTask, DocumentBaseAddAttributes, DocumentBaseConfirmMultipleNuggets, DocumentBaseConfirmNugget, DocumentBaseInteractiveTablePopulation, DocumentBaseLoad, DocumentBaseNoMatchForDocument, DocumentBaseStartRanking, DocumentBaseStopMatching, \
	DocumentBaseUpdateAttributes, DocumentBaseGetOrderedNuggets, ReloadDocumentBaseTask

core_routes = Blueprint('core_routes', __name__, url_prefix='/core')

logger = logging.getLogger(__name__)


@core_routes.errorhandler(ValueError)
def invalid_feedback_request(error):
	return make_response({"error": str(error)}, 409)


@core_routes.errorhandler(PermissionError)
def feedback_access_denied(error):
	return make_response({"error": str(error)}, 403)


def _positive_id(value):
	if isinstance(value, str) and value.isascii() and value.isdigit():
		value = int(value) if len(value) <= 19 else None
	return value if type(value) is int and 0 < value <= 9223372036854775807 else None


def _selection_span(content, start, end, selected_text):
	if (not isinstance(content, str) or type(start) is not int or type(end) is not int or
		not 0 <= start < end <= len(content) or not content[start:end].strip() or
		not isinstance(selected_text, str) or content[start:end] != selected_text):
		abort(make_response({"error": "selection must match a nonempty span inside the document"}, 400))
	return start, end


def _feedback_selection(form):
	name, content = form.get("documentName"), form.get("documentContent")
	if not isinstance(name, str) or not name:
		abort(make_response({"error": "a document name is required"}, 400))
	start, end = _selection_span(content, form.get("startIndex"), form.get("endIndex"), form.get("nuggetText"))
	negative_text = form.get("noMatchText")
	negative_start, negative_end = form.get("noMatchStartIndex"), form.get("noMatchEndIndex")
	if negative_text in (None, "") and negative_start in (None, -1) and negative_end in (None, -1):
		negative_text, negative_start, negative_end = None, None, None
	else:
		negative_start, negative_end = _selection_span(content, negative_start, negative_end, negative_text)
		if (start, end) == (negative_start, negative_end):
			abort(make_response({"error": "positive and negative selections must differ"}, 400))
	return name, content, start, end, negative_text, negative_start, negative_end


@core_routes.before_request
def authorize_core_request():
	if request.method == "OPTIONS":
		return None
	view = request.view_args or {}
	token = tokenDecode(request.headers.get("Authorization") or view.get("token"))
	if token is None:
		return make_response({"error": "invalid token"}, 401)
	g.auth_token = token
	endpoint = request.endpoint.rsplit(".", 1)[-1]
	access = TaskAccess(token.id)
	if endpoint == "task_status":
		scope = access.task(view.get("task_id"))
		if not access.permitted(scope) or not scope.get("session_id"):
			return make_response({"error": "task not found"}, 404)
		g.task_scope = scope
		return None
	if endpoint == "task_update":
		return None
	data = request.get_json(silent=True) if request.is_json else {}
	if not isinstance(data, dict):
		return make_response({"error": "invalid request"}, 400)
	feedback_endpoints = {"document_base_do_current_attribute", "reload_document_base", "stop_feedback",
		"confirm_nugget_custom", "confirm_nugget_match", "confirm_no_match_in_document", "confirm_nugget_multi_match"}
	if endpoint in feedback_endpoints:
		session_id = data.get("sessionId")
		command_id = data.get("commandId")
		expected_version = data.get("expectedVersion")
		try:
			if not isinstance(session_id, str) or not isinstance(command_id, str):
				raise ValueError("missing IDs")
			UUID(session_id); UUID(command_id)
		except (ValueError, TypeError, AttributeError):
			return make_response({"error": "an explicit feedback session and command ID are required"}, 400)
		if type(expected_version) is not int or expected_version < 1:
			return make_response({"error": "a published session version is required"}, 400)
		scope = access.task(session_id)
		if (not access.permitted(scope) or not scope.get("interactive") or scope.get("session_id") != session_id):
			return make_response({"error": "interactive session not found"}, 404)
		if (("organisationId" in data and _positive_id(data["organisationId"]) != scope["organisation_id"]) or
			("baseName" in data and data["baseName"] != scope["base_name"])):
			return make_response({"error": "feedback belongs to another document base"}, 403)
		g.feedback_options = {"session_id": session_id, "expected_version": expected_version, "command_id": command_id}
		g.feedback_scope = scope
		if endpoint in {"document_base_do_current_attribute", "reload_document_base", "stop_feedback"}:
			return None
	organisation_id = _positive_id(view.get("organisation_id", data.get("organisationId")))
	if organisation_id is None:
		return make_response({"error": "invalid organization ID"}, 400)
	role = get_organisation_authorisation(token.id, organisation_id)
	if role is None or (endpoint == "delete_document_base" and role not in (0, 1)):
		return make_response({"error": "organization access denied"}, 403)
	g.organisation_id = organisation_id
	base_name = view.get("base_name", data.get("baseName"))
	if base_name is not None and (not isinstance(base_name, str) or not base_name.strip()):
		return make_response({"error": "invalid document base name"}, 400)
	if endpoint != "create_document_base" and base_name is not None:
		if get_base_id(base_name, organisation_id) is None:
			return make_response({"error": "document base not found"}, 404)
	# A caller must select documents from the requested organization and base,
	# even when they also belong to another organization containing the same text.
	documents = data.get("nuggets") if endpoint == "confirm_nugget_multi_match" else [data] if "documentName" in data else []
	if not isinstance(documents, list) or (endpoint == "confirm_nugget_multi_match" and not documents):
		return make_response({"error": "invalid documents"}, 400)
	for document in documents:
		if not isinstance(document, dict):
			return make_response({"error": "invalid document"}, 400)
		document_id, _, _ = get_document_by_name_and_content(
			document.get("documentName"), document.get("documentContent"), token.id,
			organisation_id=organisation_id, base_name=base_name)
		if document_id is None:
			return make_response({"error": "document not found"}, 404)
	return None


@core_routes.route('/document_base', methods=['POST'])
def create_document_base():
	"""
    Endpoint for creating a document base.

	This endpoint is used to create a document base from a list of document ids and a list of attributes.

	Header:
    {
        "Authorization": "your_authorization_token"
    }

    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "document_ids": [1, 2, 3],
        "attributes": "plane,car,bike"
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
	document_ids: Optional[list[int]] = form.get("document_ids")
	attributes_strings = form.get("attributes")
	if (organisation_id is None or base_name is None or document_ids is None or attributes_strings is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	attributes = attributes_strings.split(",")
	# A JSON array of integers is the canonical input. Strict numeric CSV remains
	# accepted during deployment of older clients; values never enter SQL text.
	if isinstance(document_ids, str):
		parts = document_ids.split(",")
		if not all(part.strip().isascii() and part.strip().isdigit() and len(part.strip()) <= 19 for part in parts):
			return make_response({"error": "invalid document IDs"}, 400)
		document_ids = [int(part.strip()) for part in parts]
	if (not isinstance(document_ids, list) or not document_ids or
		any(type(doc_id) is not int or not 0 < doc_id <= 9223372036854775807 for doc_id in document_ids) or
		len(document_ids) != len(set(document_ids))):
		return make_response({"error": "invalid document IDs"}, 400)
	organisation_id = g.organisation_id
	if not documents_available_for_base(document_ids, _token.id, organisation_id):
		return make_response({"error": "documents are unavailable for this organization"}, 403)

	statistics = Statistics(False)
	user_id = _token.id


	doc_base_id = add_document_base(base_name, attributes, organisation_id, document_ids, user_id)

	if doc_base_id < 0:
		return make_response({"error": "Duplicated Entry!" if doc_base_id == -409 else "An error occured!"}, -doc_base_id)


	statisticsDump = pickle.dumps(statistics)
	task = CreateDocumentBase().apply_async(args=(user_id, document_ids, attributes, statisticsDump,
												  base_name, organisation_id))
	return make_response({'task_id': task.id, 'id': doc_base_id}, 202)

@core_routes.route('/document_base/<organisation_id>/<base_name>', methods=['GET'])
def get_document_base(organisation_id: int, base_name: str):
	"""
	Endpoint for retrieving a document base using it's name und organisation id
	"""
	authorization = request.headers.get("Authorization")
	if (authorization is None or organisation_id is None or base_name is None):
		return make_response({'error': 'missing parameters'}, 400)
	
	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({'error': 'invalid token'}, 401)
	
	document_base = get_document_base_data(base_name, organisation_id)
	if document_base is None:
		return make_response({'error': 'document base not found'}, 404)
	
	return make_response({"data": document_base}, 200)

@core_routes.route('/document_base/<organisation_id>/<base_name>', methods=['DELETE'])
def delete_document_base(organisation_id: int, base_name: str):
	"""
	Endpoint for deleting a document base using it's name and organisation id
	"""
	authorization = request.headers.get("Authorization")
	if (authorization is None or organisation_id is None or base_name is None):
		return make_response({'error': 'missing parameters'}, 400)

	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({'error': 'invalid token'}, 401)

	success = delete_document_base_data(base_name, organisation_id, _token.id)
	if not success:
		return make_response({'error': 'document base not found'}, 404)

	return make_response({'message': 'document base deleted'}, 200)

@core_routes.route('/document_base/load', methods=['POST'])
def load_document_base():
	"""
    Endpoint for loading a document base.

	This endpoint is used to load a document base from a name and an organisation id.

	Header:
    {
        "Authorization": "your_authorization_token"
    }

    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
	if (organisation_id is None or base_name is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseLoad().apply_async(args=(user_id, base_name, organisation_id))

	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/interactive', methods=['POST'])
def interactive_document_base():
	"""
    Endpoint for interactive document population

	This endpoint is used to load a document base from a name and an organisation id.

	Header:
	{
		"Authorization": "your_authorization_token"
	}

    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
 
	if (organisation_id is None or base_name is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseInteractiveTablePopulation().apply_async(args=(user_id, base_name, organisation_id))

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/attributes/add', methods=['POST'])
def document_base_attribute_add():
	"""
    Endpoint for add attributes to a document base.

	This endpoint is used to add attributes to a document base from a list of attributes.

	Header:
	{
		"Authorization": "your_authorization_token"
	}
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "attributes": "plane,car,bike"
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id = form.get("organisationId")
	base_name = form.get("baseName")
	attributes_string = form.get("attributes")
	if (organisation_id is None or base_name is None or attributes_string is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	attributes_strings = _attribute_names(attributes_string)
	task = DocumentBaseAddAttributes().apply_async(args=(_token.id, attributes_strings, base_name, organisation_id))
	return make_response({'task_id': task.id}, 202)


def _attribute_names(value):
	if isinstance(value, str):
		value = value.split(",") if value else []
	if (not isinstance(value, list) or any(
		not isinstance(name, str) or not name.strip() or '\0' in name for name in value
	) or len(set(value)) != len(value)):
		abort(make_response({"error": "Attribute names must be nonempty and unique."}, 400))
	return value


@core_routes.route('/document_base/attributes/update', methods=['POST'])
def document_base_attribute_update():
	form = request.get_json()
	base_name = form.get("baseName")
	if base_name is None or "attributes" not in form:
		return make_response({"error": "missing parameters"}, 400)
	attributes = _attribute_names(form["attributes"])
	task = DocumentBaseUpdateAttributes().apply_async(args=(
		g.auth_token.id, attributes, base_name, g.organisation_id))
	return make_response({'task_id': task.id}, 202)


# @core_routes.route('/longtask', methods=['POST'])
# def longtask():
# 	task = long_task.apply_async()
# 	return jsonify(str(task.id)), 202, {'Location': url_for('core_routes.task_status',
# 															task_id=task.id)}


@core_routes.route('/status/<token>/<task_id>', methods=['GET'])
def task_status(token: str,task_id: str):
 
	user_id = g.auth_token.id
	scope = g.task_scope
	task = BaseTask().AsyncResult(task_id=task_id)
	status = task.status
	include_payload = request.args.get("summary") != "1"
	include_feedback = request.args.get("feedback") != "0"
	session = SessionState(user_id, scope["base_id"], scope["session_id"])
	if scope.get("command_id"):
		parent_status = BaseTask().AsyncResult(task_id=scope["session_id"]).status
		if parent_status in ("FAILURE", "ERROR", "REVOKED") and not session.metadata().get("closed"):
			# Worker loss can prevent after_return; never leave its accepted commands looking successful.
			session.close(error="The interactive session stopped before publishing feedback. Reload the base.")
	snapshot = session.snapshot(include_payload=include_payload, include_feedback=include_feedback)
	signals = Signals(user_id, base_id=scope["base_id"], session_id=scope["session_id"]).to_json(
		include_payload=include_payload, include_feedback=include_feedback, snapshot=snapshot)
	publication = snapshot["publication"]
	command = session.command(scope["command_id"]) if scope.get("command_id") else None
	if command is not None:
		command = {key: command[key] for key in ("command_id", "state", "expected_version", "consumed_version", "published_version", "error") if key in command}
	if signals.get("error") == "STALE_BASE":
		signals["error"] = "This base changed in another session or access was lost. Reload before editing again; no newer changes were overwritten."
	elif signals.get("error") == "PERSISTENCE_FAILED":
		signals["error"] = "Changes could not be saved."
	if command and command.get("state") == "rejected":
		signals["error"] = command.get("error") or "Feedback was rejected. Reload the current session state."
	if status in ("FAILURE", "ERROR", "REVOKED"):
		if not signals.get("error"):
			signals["error"] = "The task was cancelled." if status == "REVOKED" else "The background task failed."
		return make_response({"state": "REVOKED" if status == "REVOKED" else "FAILURE", "meta": signals, "session": publication, "command": command}, 500)
	return make_response({"state": status, "meta": signals, "session": publication, "command": command}, 200 if status == "SUCCESS" else 202)


@core_routes.route('/status/<task_id>', methods=['POST'])
def task_update(task_id: str):
	# Legacy raw signal injection is replaced by the scoped feedback endpoints.
	return make_response({"error": "use the document-base feedback endpoints"}, 410)

@core_routes.route('/document_base/do_current_attribute', methods=['POST'])
def document_base_do_current_attribute():
	"""
    Endpoint for giving feedback on doing the current attribute of a document base.

	Header:
	{
		"Authorization": "your_authorization_token"
	}
    Example Form Payload:
    {
		"do-attribute": true
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	do_attribute = form.get("doAttribute")
	reset = form.get("reset", False)
	if type(do_attribute) is not bool or type(reset) is not bool or (reset and not do_attribute):
		return make_response({"error": "Invalid ranking or reset option"}, 400)
	if authorization is None or do_attribute is None:
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseStartRanking().apply_async(args=(user_id, do_attribute, reset), **g.feedback_options)

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/reload', methods=['POST'])
def reload_document_base():
	"""
    Endpoint for reloading the document base.

    Header:
    {
        "Authorization": "your_authorization_token"
    }
	No Body Parameters
    """
	authorization = request.headers.get("Authorization")
	if authorization is None:
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = ReloadDocumentBaseTask().apply_async(args=(user_id,), **g.feedback_options)

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/order/nugget', methods=['POST'])
def sort_nuggets():
	"""
    Endpoint for creating a document base.

	This endpoint is used to create a document base from a list of document ids and a list of attributes.

	Header:
	{
		"Authorization": "your_authorization_token"
	}
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "documentName": "your_document_name",
        "documentContent": "your_document_content",
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
	document_name = form.get("documentName")
	document_content = form.get("documentContent")
	if organisation_id is None or base_name is None or document_name is None or document_content is None or authorization is None:
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)
	
	if _token is None:
		return make_response({"error": "invalid token"}, 401)
	
	user_id = _token.id
	
	task = DocumentBaseGetOrderedNuggets().apply_async(args=(
     														user_id, 
                   											base_name, 
                              								organisation_id, 
                                      						document_name, 
                                            				document_content
                              							))
	
	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/custom', methods=['POST'])
def confirm_nugget_custom():
	"""
    Endpoint to confirm a custom nugget.

	Header:
    {
        "Authorization": "your_authorization_token"
    }
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "documentName": "your_document_name",
        "documentContent": "your_document_content",
        "nuggetText": "nugget_as_text",
        "startIndex": "start_index_of_nugget",
        "endIndex": "end_index_of_nugget",
        "noMatchText": "no_match_nugget_as_text",
        "noMatchStartIndex": "start_index_of_no_match_nugget",
        "noMatchEndIndex": "end_index_of_no_match_nugget"
    }
    """
	form = request.get_json()
	name, content, start, end, negative_text, negative_start, negative_end = _feedback_selection(form)
	task = DocumentBaseConfirmNugget().apply_async(args=(
		g.auth_token.id, form.get("baseName"), g.organisation_id, name, content,
		form["nuggetText"], start, end, negative_text, negative_start, negative_end), **g.feedback_options)
	return make_response({"task_id": task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/match', methods=['POST'])
def confirm_nugget_match():
	"""
    Endpoint to confirm a match nugget.

	Header:
    {
        "Authorization": "your_authorization_token"
    }
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "documentName": "your_document_name",
        "documentContent": "your_document_content",
        "nuggetText": "nugget_as_text",
        "startIndex": "start_index_of_nugget",
        "endIndex": "end_index_of_nugget"
    }
    """
	form = request.get_json()
	name, content, start, end, negative_text, negative_start, negative_end = _feedback_selection(form)
	task = DocumentBaseConfirmNugget().apply_async(args=(
		g.auth_token.id, form.get("baseName"), g.organisation_id, name, content,
		None, start, end, negative_text, negative_start, negative_end), **g.feedback_options)
	return make_response({"task_id": task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/multiple', methods=['POST'])
def confirm_nugget_multi_match():
	"""
	Endpoint to confirm multiple match nuggets in a document.

	Header:
    {
        "Authorization": "your_authorization_token"
    }
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "nuggets": [
            {
                "documentName": "your_document_name_1",
				"documentContent": "your_document_content_1",
                "text": "nugget_as_text_1",
                "startIndex": "start_index_of_nugget_1",
                "endIndex": "end_index_of_nugget_1",
            },
            {
                "documentName": "your_document_name_2",
                "documentContent": "your_document_content_2",
                "text": "nugget_as_text_2",
                "startIndex": "start_index_of_nugget_2",
                "endIndex": "end_index_of_nugget_2",
            }
        ]
    }
	"""
	form = request.get_json()
	documents_and_nuggets = []
	document_names = set()
	for selected in form["nuggets"]:
		name, content = selected.get("documentName"), selected.get("documentContent")
		if not isinstance(name, str) or not name or name in document_names:
			return make_response({"error": "select one match per document"}, 400)
		document_names.add(name)
		start, end = _selection_span(content, selected.get("startIndex"), selected.get("endIndex"), selected.get("text"))
		documents_and_nuggets.append((name, content, start, end))
	task = DocumentBaseConfirmMultipleNuggets().apply_async(args=(
		g.auth_token.id, form.get("baseName"), g.organisation_id, documents_and_nuggets), **g.feedback_options)
	return make_response({"task_id": task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/none', methods=['POST'])
def confirm_no_match_in_document():
	"""
    Endpoint to confirm no match for a nugget in a document.

	Header:
    {
        "Authorization": "your_authorization_token"
    }
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "documentName": "your_document_name",
        "documentContent": "your_document_content",
        "nuggetText": "nugget_as_text",
        "startIndex": "start_index_of_nugget",
        "endIndex": "end_index_of_nugget"
    }
    """
	form = request.get_json()
	name, content = form.get("documentName"), form.get("documentContent")
	base_name = form.get("baseName")
	text = form.get("nuggetText")
	start, end = form.get("startIndex"), form.get("endIndex")
	if not isinstance(name, str) or not name or not isinstance(content, str) or base_name is None:
		return make_response({"error": "missing document or base"}, 400)
	if not (text == "" and type(start) is int and type(end) is int and start == end == 0):
		start, end = _selection_span(content, start, end, text)
	task = DocumentBaseNoMatchForDocument().apply_async(args=(
		g.auth_token.id, base_name, g.organisation_id, name, content, text, start, end), **g.feedback_options)
	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/feedback/stop', methods=['POST'])
def stop_feedback():
	"""
	Endpoint to stop feedback for a document.

	header: {
		"Authorization": "your_authorization_token"
	}
	no payload is required
	"""
	authorization = request.headers.get("Authorization")

	if (authorization is None):
		return make_response({"error": "missing header fields"}, 400)

	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseStopMatching().apply_async(args=(user_id,), **g.feedback_options)

	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/feedback/public', methods=['POST'])
def add_public_feedback():
	"""
	Endpoint to add public feedback for a document.

	header: {
		"Authorization": "your_authorization_token"
	}
	Example Form Payload:
	{
		"organisationId": "your_organisation_id",
		"documentName": "your_document_name",
		"documentContent": "your_document_content",
		"nuggetText": "nugget_as_text",
		"startIndex": "start_index_of_nugget",
		"endIndex": "end_index_of_nugget",
		"isPositive": true
	}
	"""
	form = request.get_json()

	authorization = request.headers.get("Authorization")
	organisation_id = int(form.get("organisationId")) if form.get("organisationId") is not None else None
	attribute = form.get("attribute")
 
	document_name = form.get("documentName")
	document_content = form.get("documentContent")

	start_index: Optional[int]  = int(form.get("startIndex")) if form.get("startIndex") is not None else None
	end_index: Optional[int]  = int(form.get("endIndex")) if form.get("endIndex") is not None else None
	is_positive: bool = form.get("isPositive")

	if (organisation_id is None
	 	or attribute is None
		or authorization is None
		or is_positive is None
		or document_name is None
		or document_content is None):


		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id
 
	document_id, _, _ = get_document_by_name_and_content(
		document_name,
		document_content,
		user_id, organisation_id=organisation_id
	)
	if document_id is None:
		return make_response({"error": "document not found"}, 404)
 
	feedback_id = add_feedback(
    	document_id=int(document_id),
     	user_id=user_id,
      	positive=is_positive,
       	attribute=attribute,
        feedback_start=start_index,
        feedback_end=end_index, organisation_id=organisation_id
	)
 
	if feedback_id < 0:
		return make_response({"error": "An error occured!"}, -feedback_id)

	return make_response({'feedback_id': feedback_id}, 200)

@core_routes.route('/document_base/feedback/public/get', methods=['POST'])
def get_public_feedback():
	"""
	Endpoint to get public feedback for a document.

	header: {
		"Authorization": "your_authorization_token"
	}
	Example Query Parameters:
	{
		"organisationId": "your_organisation_id",
		"documentName": "your_document_name",
		"documentContent": "your_document_content"
	}
	"""
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")

	if (organisation_id is None
		or authorization is None):

		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id
 
	document_id, _, _ = get_document_by_name_and_content(
		form.get("documentName"),
		form.get("documentContent"),
		user_id, organisation_id=organisation_id
	)
	if document_id is None:
		return make_response({"error": "document not found"}, 404)

	feedback = get_feedbacks_for_document(int(document_id))

	return make_response({'feedback': feedback}, 200)