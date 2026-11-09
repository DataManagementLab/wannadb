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
import logging
from uuid import UUID
from typing import Optional

from wannadb_web.postgres.queries import get_document_base_data, get_document_by_name_and_content, get_feedbacks_for_document, get_document_by_name, get_base_id, get_organisation_authorisation, documents_available_for_base, get_document_ids_for_snapshot
from wannadb_web.postgres.transactions import add_feedback, delete_document_base_data

from flask import Blueprint, make_response, request, g, abort
from wannadb_web.Redis.RedisCache import TaskAccess, SessionState
from wannadb_web.limits import MAX_BASE_DOCUMENTS, QueueFullError, WorkLimitError, validate_attribute_count
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
	token = tokenDecode(request.headers.get("Authorization"))
	if token is None:
		return make_response({"error": "invalid token"}, 401)
	g.auth_token = token
	endpoint = request.endpoint.rsplit(".", 1)[-1]
	access = TaskAccess(token.id)
	if endpoint == "task_status":
		try:
			UUID(view.get("task_id"))
		except (TypeError, ValueError, AttributeError):
			return make_response({"error": "task not found"}, 404)
		scope = access.task(view["task_id"])
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
	"""Queue preprocessing. The worker creates the base only when all data is ready."""
	form = request.get_json()
	base_name = form.get("baseName")
	document_ids = form.get("document_ids")
	if not isinstance(base_name, str) or not base_name.strip() or '\0' in base_name or "attributes" not in form:
		return make_response({"error": "A document base name and attributes are required."}, 400)

	attributes = _attribute_names(form["attributes"])
	if not attributes:
		return make_response({"error": "Enter at least one attribute."}, 400)
	if isinstance(document_ids, str):
		document_ids = [_positive_id(part.strip()) for part in document_ids.split(",")]
	if isinstance(document_ids, list) and len(document_ids) > MAX_BASE_DOCUMENTS:
		raise WorkLimitError(f"Select at most {MAX_BASE_DOCUMENTS} documents.")
	if (not isinstance(document_ids, list) or not document_ids
		or any(type(doc_id) is not int or _positive_id(doc_id) is None for doc_id in document_ids)
		or len(document_ids) != len(set(document_ids))):
		return make_response({"error": "Select one or more distinct documents."}, 400)

	organisation_id = g.organisation_id
	user_id = g.auth_token.id
	if get_base_id(base_name, organisation_id) is not None:
		return make_response({"error": "A document base with that name already exists."}, 409)
	try:
		documents_available = documents_available_for_base(document_ids, user_id, organisation_id)
	except RuntimeError:
		return make_response({"error": "Could not check document availability. Try again."}, 503)
	if not documents_available:
		return make_response({"error": "The selected documents are unavailable for this organization."}, 403)

	try:
		task = CreateDocumentBase().apply_async(args=(user_id, document_ids, attributes, base_name, organisation_id))
	except PermissionError:
		return make_response({"error": "Document base access denied."}, 403)
	except QueueFullError:
		raise
	except Exception as error:
		logger.warning("Could not enqueue document base creation (%s)", type(error).__name__)
		return make_response({"error": "Could not queue creation. Check the document base list before retrying."}, 503)
	return make_response({"task_id": task.id}, 202)


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
	validate_attribute_count(len(value))
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


@core_routes.route('/status/<task_id>', methods=['GET'])
def task_status(task_id: str):
	user_id = g.auth_token.id
	scope = g.task_scope
	task = BaseTask().AsyncResult(task_id=task_id)
	status = task.status
	created_base_id = None
	if scope.get("creation") is True and status == "SUCCESS":
		result = task.result
		created_base_id = _positive_id(result.get("base_id")) if isinstance(result, dict) else None
		if created_base_id is None or get_base_id(scope["base_name"], scope["organisation_id"]) != created_base_id:
			return make_response({"error": "The created document base is no longer available."}, 404)
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
	base = signals["document_base_to_ui"]
	if base:
		document_ids = get_document_ids_for_snapshot(scope["base_id"], scope["organisation_id"], user_id,
			{document["name"]: document["text"] for document in base["documents"]})
		base.update(id=scope["base_id"], organization_id=scope["organisation_id"], name=scope["base_name"])
		for document in base["documents"]:
			document["id"] = document_ids.get(document["name"])
	publication = snapshot["publication"]
	command = session.command(scope["command_id"]) if scope.get("command_id") else None
	if command is not None:
		command = {key: command[key] for key in ("command_id", "state", "expected_version", "consumed_version", "published_version", "error") if key in command}
	if signals.get("error") == "STALE_BASE":
		signals["error"] = "This base changed in another session or access was lost. Reload before editing again; no newer changes were overwritten."
	else:
		error_messages = {
			"PERSISTENCE_FAILED": "Changes could not be saved.",
			"MATCHING_FAILED": "The feedback session could not continue. Reload the base before retrying.",
			"BASE_LOAD_FAILED": "The saved document base could not be loaded.",
			"CREATE_CONFLICT": "A document base with that name already exists.",
			"CREATE_INPUT_CHANGED": "A selected document changed or is no longer available. Select the files again.",
			"CREATE_ACCESS_DENIED": "Document base access denied.",
			"CREATE_FAILED": "Could not prepare or save the document base. You can retry creation.",
			"CREATE_INVALID": "Check the selected documents and attribute names.",
			"TASK_LIMIT": "The worker reached its processing time limit. Retry with less work.",
		}
		signals["error"] = error_messages.get(signals["error"], signals["error"])
	if command and command.get("state") == "rejected":
		signals["error"] = command.get("error") or "Feedback was rejected. Reload the current session state."
	body = {"state": status, "meta": signals, "session": publication, "command": command}
	if created_base_id is not None:
		body["base_id"] = created_base_id
	http_status = 200 if status == "SUCCESS" else 202
	if status in ("FAILURE", "ERROR", "REVOKED"):
		body["state"] = "REVOKED" if status == "REVOKED" else "FAILURE"
		if not signals.get("error"):
			signals["error"] = "The task was cancelled." if status == "REVOKED" else "The background task failed."
		http_status = 500
	return make_response(body, http_status, {"Cache-Control": "no-store"})


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
	"""Save document feedback, using half-open Unicode code-point offsets for a span."""
	form = request.get_json()
	name, content = form.get("documentName"), form.get("documentContent")
	attribute, positive = form.get("attribute"), form.get("isPositive")
	if (not isinstance(name, str) or not name or not isinstance(content, str)
		or not isinstance(attribute, str) or not attribute.strip() or '\0' in attribute
		or type(positive) is not bool):
		return make_response({"error": "invalid document feedback"}, 400)

	start, end, text = form.get("startIndex"), form.get("endIndex"), form.get("nuggetText")
	if start is not None or end is not None or text is not None:
		start, end = _selection_span(content, start, end, text)

	user_id = g.auth_token.id
	base_name = form.get("baseName")
	document_id, _, _ = get_document_by_name_and_content(
		name, content, user_id, organisation_id=g.organisation_id, base_name=base_name)
	if document_id is None:
		return make_response({"error": "document not found"}, 404)

	feedback_id = add_feedback(
		document_id=document_id, user_id=user_id, positive=positive, attribute=attribute,
		feedback_start=start, feedback_end=end, organisation_id=g.organisation_id,
		expected_content=content, base_name=base_name)
	if feedback_id == -409:
		return make_response({"error": "The document changed or feedback conflicted. Reload before retrying."}, 409)
	if feedback_id < 0:
		return make_response({"error": "Could not save document feedback."}, -feedback_id)
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
		user_id, organisation_id=organisation_id, base_name=form.get("baseName")
	)
	if document_id is None:
		return make_response({"error": "document not found"}, 404)

	feedback = get_feedbacks_for_document(int(document_id))

	return make_response({'feedback': feedback}, 200)