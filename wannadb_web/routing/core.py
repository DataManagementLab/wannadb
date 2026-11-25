"""Scoped document-base, task-status and feedback HTTP routes under /core.

ROUTES.md is the wire contract, including field types, required command IDs,
versions and recovery. All non-OPTIONS requests require a valid backend Bearer
credential. Task submission imports lightweight task definitions; workers load
model resources only when processing a job.

Author: Leon Wenderoth
"""
from wannadb_web.worker.progress import attribute_progress

import logging
import re
from uuid import UUID
from typing import Optional

from bson import decode as decode_bson
from redis.exceptions import RedisError
from wannadb_web.postgres.queries import get_base_reference, get_document, get_document_base_data, get_document_by_name_and_content, get_feedbacks_for_document, get_document_by_name, get_base_id, get_organisation_authorisation, documents_available_for_base, get_document_ids_for_snapshot, get_document_base_snapshot
from wannadb_web.postgres.attribute_schema import attribute_ids_for_snapshot, get_attribute_schema_version, parse_attribute_edit
from wannadb_web.postgres.queries import FeedbackOutcomeUnavailable, get_feedback_outcome, get_public_feedback_suggestions
from wannadb_web.postgres.feedback_sessions import FeedbackSessionUnavailable, load_session
from wannadb_web.postgres.transactions import add_feedback, delete_document_base_data

from flask import Blueprint, make_response, request, g, abort
from wannadb_web.Redis.RedisCache import TaskAccess, TaskAdmission, SessionState
from wannadb_web.SQLite.table_query import TableQueryError, validate_table_query
from wannadb_web.limits import MAX_BASE_DOCUMENTS, QueueFullError, WorkLimitError, validate_attribute_count
from wannadb_web.util import tokenDecode
from wannadb_web.worker.data import Signals
from wannadb_web.worker.payload import TABLE_PAGE_SIZE, legacy_payload, project_base

from wannadb_web.worker.tasks import CreateDocumentBase, BaseTask, DocumentBaseConfirmMultipleNuggets, DocumentBaseConfirmNugget, DocumentBaseInteractiveTablePopulation, DocumentBaseLoad, DocumentBaseNoMatchForDocument, DocumentBaseStartRanking, DocumentBaseStopMatching, \
	DocumentBaseUpdateAttributes, ReloadDocumentBaseTask, ReviewPublicSuggestion, DocumentBaseCloseFeedbackSession

core_routes = Blueprint('core_routes', __name__, url_prefix='/core')

logger = logging.getLogger(__name__)
_TASK_FAILURE_STATES = ("FAILURE", "ERROR", "REVOKED", "EXPIRED")


@core_routes.errorhandler(ValueError)
def invalid_feedback_request(error):
	"""Map a feedback-state conflict to an HTTP 409 response.

	:param error: The failure object or safe error text/code handled here.
	:type error: BaseException | str
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	return make_response({"error": str(error)}, 409)


@core_routes.errorhandler(PermissionError)
def feedback_access_denied(error):
	"""Map a scoped feedback permission failure to HTTP 403.

	:param error: The failure object or safe error text/code handled here.
	:type error: BaseException | str
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	return make_response({"error": str(error)}, 403)


@core_routes.errorhandler(FeedbackOutcomeUnavailable)
@core_routes.errorhandler(FeedbackSessionUnavailable)
@core_routes.errorhandler(RedisError)
def feedback_status_unavailable(error):
	"""Return retryable HTTP 503 when feedback publication/receipt state is unavailable.

	:param error: The failure object or safe error text/code handled here.
	:type error: BaseException | str
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	return make_response({"error": "Feedback status is temporarily unavailable. Check the result again shortly."},
		503, {"Cache-Control": "no-store"})


def _positive_id(value):
	"""Validate a positive database identifier before using it for scoped access.

	:param value: The value to validate, store or convert as described above.
	:type value: object
	:returns: The positive id result.
	:rtype: int | None
	"""
	if isinstance(value, str) and value.isascii() and value.isdigit():
		value = int(value) if len(value) <= 19 else None
	return value if type(value) is int and 0 < value <= 9223372036854775807 else None


def _selection_span(content, start, end, selected_text):
	"""Require an exact, nonempty Unicode code-point selection in the displayed source.

	:param content: The complete source text or snapshot payload for this operation.
	:type content: str | bytes
	:param start: The inclusive Unicode code-point offset.
	:type start: int
	:param end: The exclusive Unicode code-point offset.
	:type end: int
	:param selected_text: The text that must exactly match the selected span.
	:type selected_text: str
	:returns: The selection span result.
	:rtype: tuple[int, int]
	"""
	if (not isinstance(content, str) or type(start) is not int or type(end) is not int or
		not 0 <= start < end <= len(content) or not content[start:end].strip() or
		not isinstance(selected_text, str) or content[start:end] != selected_text):
		abort(make_response({"error": "selection must match a nonempty span inside the document"}, 400))
	return start, end


def _feedback_selection(form):
	"""Validate positive and optional distinct negative selections in a feedback request.

	:param form: The parsed JSON submission containing the scoped mutation parameters.
	:type form: dict[str, object]
	:returns: The feedback selection result.
	:rtype: tuple[str, str, int, int, str | None, int | None, int | None]
	"""
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
	"""Authenticate and validate live task/base/session scope before dispatching a core route.

	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response | None
	:raises ValueError: If an input fails validation for this operation.
	"""
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
		cache_error = None
		try:
			scope = access.task(view["task_id"])
		except RedisError as error:
			cache_error = error
			scope = None
		if scope is None:
			outcome = get_feedback_outcome(token.id, view["task_id"])
			if outcome is None and cache_error is not None:
				raise cache_error
			if outcome is not None:
				scope = outcome
				g.feedback_outcome = outcome
			elif request.args.get("feedbackSession") == "1":
				scope = load_session(token.id, view["task_id"])
				g.feedback_publication_missing = scope is not None
		else:
			allowed, g.task_session_exists = access.poll_access(scope)
			if not allowed:
				scope = None
		if scope is None or not scope.get("session_id"):
			return make_response({"error": "task not found"}, 404)
		if request.args.get("feedbackSession") == "1" and (
			not scope.get("interactive") or scope.get("session_id") != view["task_id"] or
			_positive_id(request.args.get("organisationId")) != scope["organisation_id"] or
			request.args.get("baseName") != scope["base_name"]
		):
			return make_response({"error": "interactive session not found"}, 404)
		g.task_scope = scope
		return None
	if endpoint == "task_update":
		return None
	data = request.get_json(silent=True) if request.is_json else {}
	if not isinstance(data, dict):
		return make_response({"error": "invalid request"}, 400)
	feedback_endpoints = {"document_base_do_current_attribute", "reload_document_base", "stop_feedback", "close_feedback",
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
		if type(expected_version) is not int or not 0 < expected_version < 9223372036854775807:
			return make_response({"error": "a published session version is required"}, 400)
		outcome = get_feedback_outcome(token.id, command_id)
		if outcome is not None:
			if outcome["session_id"] != session_id or outcome["expected_version"] != expected_version:
				return make_response({"error": "command ID belongs to different request parameters"}, 409)
			scope = outcome
		else:
			scope = access.task(session_id)
			if (not scope or not scope.get("interactive") or scope.get("session_id") != session_id):
				return make_response({"error": "interactive session not found"}, 404)
			checkpoint = load_session(token.id, session_id)
			if checkpoint is None or checkpoint["base_id"] != scope["base_id"]:
				return make_response({
					"error": "This feedback session is unavailable. Reopen the base to continue from saved matches.",
				}, 404)
		if (("organisationId" in data and _positive_id(data["organisationId"]) != scope["organisation_id"]) or
			("baseName" in data and data["baseName"] != scope["base_name"])):
			return make_response({"error": "feedback belongs to another document base"}, 403)
		g.feedback_options = {"session_id": session_id, "expected_version": expected_version, "command_id": command_id}
		g.feedback_scope = scope
		if outcome is not None:
			g.feedback_options["durable_outcome"] = outcome
		if endpoint in {"document_base_do_current_attribute", "reload_document_base", "stop_feedback", "close_feedback"}:
			return None
		if endpoint == "confirm_nugget_multi_match" or outcome is not None:
			if "organisationId" not in data or "baseName" not in data:
				return make_response({"error": "an organization and document base are required"}, 400)
			g.organisation_id = scope["organisation_id"]
			return None
	base_scope = request.args if endpoint == "feedback_overview" else data
	organisation_id = _positive_id(view.get("organisation_id", base_scope.get("organisationId")))
	if organisation_id is None:
		return make_response({"error": "invalid organization ID"}, 400)
	try:
		role = get_organisation_authorisation(token.id, organisation_id, raise_on_error=True)
	except RuntimeError:
		return make_response({"error": "Organization access checks are temporarily unavailable."}, 503)
	if role is None or (endpoint in ("delete_document_base", "delete_document_base_by_id") and role not in (0, 1)):
		return make_response({"error": "organization access denied"}, 403)
	g.organisation_id = organisation_id
	g.organisation_role = role
	g.requested_base_id = _positive_id(base_scope.get("baseId"))
	if "baseId" in base_scope and g.requested_base_id is None:
		return make_response({"error": "invalid document base ID"}, 400)
	base_name = view.get("base_name", base_scope.get("baseName"))
	if base_name is not None and (not isinstance(base_name, str) or not base_name.strip()):
		return make_response({"error": "invalid document base name"}, 400)
	if endpoint != "create_document_base" and base_name is not None:
		try:
			base_id = get_base_id(base_name, organisation_id, raise_on_error=True)
		except RuntimeError:
			return make_response({"error": "Document base metadata is temporarily unavailable."}, 503)
		if base_id is None or (g.requested_base_id is not None and base_id != g.requested_base_id):
			return make_response({"error": "document base not found"}, 404)
		if endpoint == "feedback_overview":
			g.feedback_overview_scope = (base_name, base_id)
	# A caller must select documents from the requested organization and base,
	# even when they also belong to another organization containing the same text.
	if "documentName" in data:
		document_id, _, _ = get_document_by_name_and_content(
			data.get("documentName"), data.get("documentContent"), token.id,
			organisation_id=organisation_id, base_name=base_name)
		if document_id is None:
			return make_response({"error": "document not found"}, 404)
	return None


@core_routes.route('/document_base', methods=['POST'])
def create_document_base():
	"""Queue preprocessing. The worker creates the base only when all data is ready.

	JSON contains the organization/base scope, document IDs and attributes.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	:raises WorkLimitError: A source-document, corpus or other web work budget was exceeded.
	"""
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


def _base_reference(*, base_id=None, name=None):
	"""Resolve the selected stable ID or exact name inside the authorized organization.

	:param base_id: The selected document-base database ID.
	:type base_id: int | None
	:param name: The selected display name or operation identifier.
	:type name: str | None
	:returns: The base reference result.
	:rtype: tuple[object, ...]
	"""
	try:
		base = get_base_reference(g.organisation_id, base_id=base_id, name=name)
	except RuntimeError:
		abort(make_response({"error": "Document base metadata is temporarily unavailable."}, 503))
	if base is None:
		abort(make_response({"error": "document base not found"}, 404))
	return base


def _base_reference_response(base):
	"""Encode a base reference with stable attribute identities for the browser.

	:param base: The authorized domain base or decoded snapshot record.
	:type base: DocumentBase | dict[str, object]
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	base_id, name, version, stored_ids, names = base
	attribute_ids = attribute_ids_for_snapshot({"attributes": [{"name": name} for name in names]}, version, stored_ids)
	return make_response({"id": base_id, "name": name, "attributeIds": attribute_ids}, 200)


@core_routes.route('/document_base/by-id/<organisation_id>/<base_id>', methods=['GET'])
def get_document_base_by_id(organisation_id, base_id):
	"""Read a stable document-base reference under organization membership checks.

	:param organisation_id: The organization database ID used to scope access.
	:type organisation_id: int
	:param base_id: The selected document-base database ID.
	:type base_id: int
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	base_id = _positive_id(base_id)
	if base_id is None:
		return make_response({"error": "invalid document base ID"}, 400)
	return _base_reference_response(_base_reference(base_id=base_id))


@core_routes.route('/document_base/resolve/<organisation_id>', methods=['GET'])
def resolve_document_base(organisation_id):
	"""Resolve an exact base name inside the authorized organization.

	:param organisation_id: The organization database ID used to scope access.
	:type organisation_id: int
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	name = request.args.get("name")
	if not name or not name.strip() or "\0" in name:
		return make_response({"error": "invalid document base name"}, 400)
	return _base_reference_response(_base_reference(name=name))


@core_routes.route('/document_base/<organisation_id>/<path:base_name>', methods=['GET'])
def get_document_base(organisation_id, base_name):
	"""Return the scoped document-base catalog or HTTP 404.

	:param organisation_id: The organization database ID used to scope access.
	:type organisation_id: int
	:param base_name: The exact document-base display name.
	:type base_name: str
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	document_base = get_document_base_data(base_name, g.organisation_id)
	if document_base is None:
		return make_response({"error": "document base not found"}, 404)
	return make_response({"data": document_base}, 200)


def _delete_base(name, base_id=None):
	"""Delete the selected base and encode a safe scoped result.

	:param name: The selected display name or operation identifier.
	:type name: str
	:param base_id: The selected document-base database ID.
	:type base_id: int | None
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	try:
		deleted = delete_document_base_data(name, g.organisation_id, g.auth_token.id, base_id=base_id)
	except RuntimeError:
		return make_response({"error": "Could not delete the document base. Try again."}, 503)
	if not deleted:
		return make_response({"error": "document base not found"}, 404)
	return make_response({"message": "document base deleted"}, 200)


@core_routes.route('/document_base/by-id/<organisation_id>/<base_id>', methods=['DELETE'])
def delete_document_base_by_id(organisation_id, base_id):
	"""Delete a stable-ID-selected base under backend role checks.

	:param organisation_id: The organization database ID used to scope access.
	:type organisation_id: int
	:param base_id: The selected document-base database ID.
	:type base_id: int
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	base_id = _positive_id(base_id)
	if base_id is None:
		return make_response({"error": "invalid document base ID"}, 400)
	base = _base_reference(base_id=base_id)
	return _delete_base(base[1], base_id=base_id)


@core_routes.route('/document_base/<organisation_id>/<path:base_name>', methods=['DELETE'])
def delete_document_base(organisation_id, base_name):
	"""Delete an exact-name-selected base under backend role checks.

	:param organisation_id: The organization database ID used to scope access.
	:type organisation_id: int
	:param base_name: The exact document-base display name.
	:type base_name: str
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	return _delete_base(base_name)


@core_routes.route('/document_base/load', methods=['POST'])
def load_document_base():
	"""Queue a scoped catalog/document load, returning 202 with task_id.

	JSON selects the organization/base, optional base ID and automatic-match mode.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	"""
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
	include_automatic_matches = form.get("includeAutomaticMatches", False)
	if type(include_automatic_matches) is not bool:
		return make_response({"error": "includeAutomaticMatches must be a boolean"}, 400)
	if (organisation_id is None or base_name is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	args = (user_id, base_name, organisation_id)
	if include_automatic_matches:
		args += (True,)
	task = DocumentBaseLoad().apply_async(args=args, expected_base_id=g.requested_base_id)

	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/query', methods=['POST'])
def query_document_base():
	"""Validate and enqueue one bounded read-only SQL query for the selected base.

	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	form = request.get_json()
	base_name = form.get("baseName")
	if not base_name:
		return make_response({"error": "a document base is required"}, 400)
	include_automatic = form.get("includeAutomaticMatches", True)
	if type(include_automatic) is not bool:
		return make_response({"error": "includeAutomaticMatches must be a boolean"}, 400)
	try:
		query = validate_table_query(form.get("sqlQuery"))
	except TableQueryError as error:
		return make_response({"error": str(error)}, 400)
	task = DocumentBaseLoad().apply_async(
		args=(g.auth_token.id, base_name, g.organisation_id), kwargs={"sql_query": query, "confirmed_only": not include_automatic}, expected_base_id=g.requested_base_id)
	return make_response({"task_id": task.id}, 202)


@core_routes.route('/document_base/interactive', methods=['POST'])
def interactive_document_base():
	"""Open a separate feedback session and return 202 with its task_id.

	JSON selects the organization/base; use task_id as the new sessionId.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
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

	task = DocumentBaseInteractiveTablePopulation().apply_async(args=(user_id, base_name, organisation_id),
		expected_base_id=g.requested_base_id)

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/feedback/overview', methods=['GET'])
def feedback_overview():
	"""Return saved attribute progress without starting a worker task.

	Read-only progress; no worker task starts. See ROUTES.md for scope fields.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	"""
	scope = getattr(g, "feedback_overview_scope", None)
	if scope is None:
		return make_response({"error": "a document base is required"}, 400)
	base_name, base_id = scope
	snapshot = get_document_base_snapshot(base_name, base_id, g.organisation_id, g.auth_token.id,
		include_attribute_schema=True)
	if snapshot is None:
		return make_response({"error": "document base snapshot not found"}, 404)
	_, content, version, stored_ids = snapshot
	base = decode_bson(content)
	ids = attribute_ids_for_snapshot(base, version, stored_ids)
	documents = base["documents"]
	document_count = len(documents)
	attributes = [dict(progress, id=ids[progress["name"]])
		for progress in attribute_progress(documents, [item["name"] for item in base["attributes"]])]
	return make_response({
		"id": base_id, "name": base_name, "attributes": attributes, "attributeVersion": version, "documentCount": document_count,
		"nuggetCount": sum(len(document["nuggets"]) for document in documents),
	}, 200, {"Cache-Control": "no-store"})


@core_routes.route('/document_base/attributes/add', methods=['POST'])
def document_base_attribute_add():
	"""Queue explicit attribute additions against the displayed schema version.

	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	form = request.get_json()
	attributes = _attribute_names(form.get("attributes"))
	return _queue_attribute_edit(form, [{"op": "add", "name": name} for name in attributes])


def _attribute_names(value):
	"""Normalize submitted attribute names and reject empty, duplicate or oversized lists.

	:param value: The value to validate, store or convert as described above.
	:type value: object
	:returns: The attribute names result.
	:rtype: list[str]
	"""
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
	"""Queue explicit add/remove/rename operations against the schema version.

	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	form = request.get_json()
	return _queue_attribute_edit(form, form.get("operations"))


def _queue_attribute_edit(form, operations):
	"""Validate the displayed schema UUID and enqueue the exact scoped attribute edit.

	:param form: The parsed JSON submission containing the scoped mutation parameters.
	:type form: dict[str, object]
	:param operations: Validated explicit attribute add/remove/rename operations.
	:type operations: list[dict[str, object]]
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	base_name = form.get("baseName")
	if not base_name:
		return make_response({"error": "A document base is required."}, 400)
	try:
		version, operations = parse_attribute_edit(form.get("expectedVersion"), operations)
	except ValueError as error:
		return make_response({"error": str(error)}, 400)
	try:
		current_version = get_attribute_schema_version(base_name, g.organisation_id)
	except RuntimeError:
		return make_response({"error": "Could not read the attribute schema. Try again."}, 503)
	if current_version != version:
		return make_response({"error": "Attributes changed. Reload them before editing again."}, 409)
	task = DocumentBaseUpdateAttributes().apply_async(args=(
		g.auth_token.id, operations, base_name, g.organisation_id, version), expected_base_id=g.requested_base_id)
	return make_response({'task_id': task.id}, 202)


# @core_routes.route('/longtask', methods=['POST'])
# def longtask():
# 	task = long_task.apply_async()
# 	return jsonify(str(task.id)), 202, {'Location': url_for('core_routes.task_status',
# 															task_id=task.id)}


def _recovered_feedback_status(outcome):
	"""Expose a committed receipt when its live Redis publication cannot be used.

	:param outcome: The saved command receipt used for recovery/replay.
	:type outcome: dict[str, object]
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	version = outcome["published_version"]
	return make_response({
		"state": "SUCCESS", "meta": {},
		"session": {"session_id": outcome["session_id"], "version": version, "phase": "finished",
			"attribute": None, "closed": True, "error": None},
		"command": {"command_id": outcome["command_id"], "state": "published",
			"expected_version": outcome["expected_version"], "published_version": version,
			"snapshot_version": outcome["snapshot_version"], "recovered": True},
	}, 200, {"Cache-Control": "no-store"})


def _lost_feedback_publication():
	"""Return a closed failure publication that directs the reviewer to reopen the base.

	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	return make_response({
		"state": "FAILURE",
		"meta": {"error": "This feedback session is unavailable. Reopen the base to continue from saved matches."},
	}, 500, {"Cache-Control": "no-store"})


@core_routes.route('/status/<task_id>', methods=['GET'])
def task_status(task_id: str):
	"""Read authorized task state, live publication and any recoverable committed receipt.

	:param task_id: The scoped Celery task/command UUID.
	:type task_id: str
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	:raises FeedbackOutcomeUnavailable: A durable command receipt cannot currently be read or
	    confirmed.
	"""
	user_id = g.auth_token.id
	scope = g.task_scope
	if getattr(g, "feedback_publication_missing", False):
		return _lost_feedback_publication()
	outcome = getattr(g, "feedback_outcome", None)
	if outcome is not None:
		if not outcome["settled"]:
			raise FeedbackOutcomeUnavailable("Waiting for feedback publication.")
		return _recovered_feedback_status(outcome)
	try:
		return _read_task_status(task_id, user_id, scope)
	except RedisError:
		if scope.get("command_id"):
			outcome = get_feedback_outcome(user_id, task_id)
			if outcome is not None and outcome["settled"]:
				return _recovered_feedback_status(outcome)
		raise


def _read_task_status(task_id, user_id, scope):
	"""Project scoped task/session data and classify terminal/review-conflict results.

	:param task_id: The scoped Celery task/command UUID.
	:type task_id: str
	:param user_id: The authenticated account ID selecting the authorized scope.
	:type user_id: int
	:param scope: The authorized user, base, organization and session/task identity.
	:type scope: dict[str, object]
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	:raises FeedbackOutcomeUnavailable: A durable command receipt cannot currently be read or
	    confirmed.
	"""
	task = BaseTask().AsyncResult(task_id=task_id)
	status = TaskAdmission("celery", user_id, task_id).status(task.status)
	created_base_id = None
	if scope.get("creation") is True and status == "SUCCESS":
		result = task.result
		created_base_id = _positive_id(result.get("base_id")) if isinstance(result, dict) else None
		if created_base_id is None or get_base_id(scope["base_name"], scope["organisation_id"]) != created_base_id:
			return make_response({"error": "The created document base is no longer available."}, 404)
	view = request.args.get("view")
	if view not in (None, "full", "catalog", "document", "review", "table", "table-export"):
		return make_response({"error": "Invalid task view."}, 400)
	raw_offset = request.args.get("offset", "0")
	if not raw_offset.isascii() or not raw_offset.isdecimal() or len(raw_offset) > 7:
		return make_response({"error": "Invalid page offset."}, 400)
	offset = int(raw_offset)
	document_id = _positive_id(request.args.get("documentId"))
	document_name = request.args.get("documentName")
	if view == "document" and (("documentId" in request.args and document_id is None) or
		(document_id is None and not document_name)):
		return make_response({"error": "A document is required."}, 400)
	full_response = request.args.get("summary") != "1"
	include_payload = full_response and view not in ("table", "table-export")
	include_feedback = request.args.get("feedback") != "0" and view in (None, "full", "review")
	session = SessionState(user_id, scope["base_id"], scope["session_id"])
	parent_status = BaseTask().AsyncResult(task_id=scope["session_id"]).status if scope.get("command_id") else None
	parent_failed = parent_status in _TASK_FAILURE_STATES
	snapshot = session.snapshot(include_payload=include_payload, include_feedback=include_feedback)
	signals = Signals(user_id, base_id=scope["base_id"], session_id=scope["session_id"]).to_json(
		include_payload=include_payload, include_feedback=include_feedback, snapshot=snapshot)
	base = signals["document_base_to_ui"]
	if base:
		if not base["ids_resolved"]:
			document_ids = get_document_ids_for_snapshot(scope["base_id"], scope["organisation_id"], user_id,
				{document["name"]: document["text"] for document in base["documents"]})
			for document in base["documents"]:
				document["id"] = document_ids.get(document["name"])
		base.update(id=scope["base_id"], organization_id=scope["organisation_id"], name=scope["base_name"])
		feedback = signals["feedback_request_to_ui"]
		if view is None:
			base, feedback = legacy_payload(base, feedback)
		else:
			base, feedback = project_base(base, feedback, view, offset=offset,
				document_id=document_id, document_name=document_name)
			if view == "document" and not base["documents"]:
				return make_response({"error": "Document not found."}, 404)
		signals.update(document_base_to_ui=base, feedback_request_to_ui=feedback)
	publication = snapshot["publication"]
	if scope.get("interactive") and not scope.get("command_id") and not publication["closed"]:
		# A finished compute step can leave an interactive session waiting for input.
		if publication["version"] > 0 and status in ("SUCCESS", "PENDING"):
			if not g.task_session_exists:
				return _lost_feedback_publication()
			status = "STARTED"
		elif publication["version"] == 0 and status == "SUCCESS":
			return _lost_feedback_publication()
	command = session.command(scope["command_id"]) if scope.get("command_id") else None
	if command is not None:
		command = {key: command[key] for key in ("command_id", "state", "expected_version", "consumed_version",
			"published_version", "propagation_limited", "error") if key in command}
	live_processing = (status == "STARTED" and publication["phase"] == "processing" and
		command is not None and command["state"] == "consumed")
	if scope.get("command_id") and (parent_failed or status in _TASK_FAILURE_STATES or
		signals.get("error") or (command is None and status != "QUEUED") or
		(command is not None and (command["state"] == "rejected" or
			(command["state"] == "consumed" and not live_processing)))):
		outcome = get_feedback_outcome(user_id, task_id)
		if outcome is not None:
			if parent_failed or publication["closed"] or (outcome["settled"] and not live_processing):
				return _recovered_feedback_status(outcome)
			if status in _TASK_FAILURE_STATES or signals.get("error") or (command and command["state"] == "rejected"):
				raise FeedbackOutcomeUnavailable("Waiting for feedback publication.")
	if parent_failed and not publication["closed"] and (not command or command["state"] in ("accepted", "consumed")):
		# Worker loss may prevent cleanup. Report the failed outcome without writing on GET.
		message = "The interactive session stopped before publishing feedback. Reload the base."
		command = dict(command or {}, command_id=scope["command_id"], expected_version=scope["expected_version"],
			state="rejected", error=message)
	public_review_conflict = signals.get("error") == "PUBLIC_REVIEW_CONFLICT"
	if signals.get("error") == "STALE_BASE":
		signals["error"] = "This base changed in another session or access was lost. Reload before editing again; no newer changes were overwritten."
	else:
		error_messages = {
			"PUBLIC_REVIEW_CONFLICT": "This suggestion or its saved match changed. Reload the suggestions before reviewing it.",
			"PERSISTENCE_FAILED": "Changes could not be saved.",
			"ATTRIBUTES_CHANGED": "Attributes changed. Reload them before editing again.",
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
	if scope.get("table_query") and status == "SUCCESS" and full_response:
		paged = view == "table"
		size = TABLE_PAGE_SIZE if paged else None
		result = session.table_page(offset if paged else 0, size)
		if result is None:
			legacy = task.result
			legacy = legacy.get("table_query") if isinstance(legacy, dict) else None
			if legacy is not None:
				rows = legacy["rows"]
				result = dict(legacy, rows=rows[offset:offset + size] if paged else rows,
					totalRows=len(rows), offset=offset if paged else 0)
		if result is None and view in ("table", "table-export"):
			return make_response({"error": "This query result expired. Run the query again."}, 404)
		if result is not None:
			result.update(taskId=task_id, pageSize=TABLE_PAGE_SIZE)
		body["table_query"] = result
	http_status = 200 if status == "SUCCESS" else 202
	if status in _TASK_FAILURE_STATES:
		body["state"] = "FAILURE" if status == "ERROR" else status
		if status == "EXPIRED":
			signals["error"] = "The task expired in the queue before a worker could start it. Try again."
		elif not signals.get("error"):
			signals["error"] = "The task was cancelled." if status == "REVOKED" else "The background task failed."
		http_status = 500
	if public_review_conflict:
		body.update(state="FAILURE", code="CONFLICT", error=signals["error"])
		http_status = 409
	return make_response(body, http_status, {"Cache-Control": "no-store"})


@core_routes.route('/status/<task_id>', methods=['POST'])
def task_update(task_id: str):
	# Legacy raw signal injection is replaced by the scoped feedback endpoints.
	"""Reject legacy raw signal injection with HTTP 410.

	:param task_id: The scoped Celery task/command UUID.
	:type task_id: str
	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	return make_response({"error": "use the document-base feedback endpoints"}, 410)

@core_routes.route('/document_base/do_current_attribute', methods=['POST'])
def document_base_do_current_attribute():
	"""Start, reset or skip the exact attribute waiting in this session.

	JSON needs sessionId, expectedVersion, commandId and the scoped ranking options.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	"""
	form = request.get_json()
	scope = g.feedback_scope
	if _positive_id(form.get("organisationId")) is None or not isinstance(form.get("baseName"), str):
		return make_response({"error": "an organization and document base are required"}, 400)
	attribute = form.get("attribute")
	if not isinstance(attribute, str) or not attribute.strip():
		return make_response({"error": "an attribute is required"}, 400)
	do_attribute = form.get("doAttribute")
	reset = form.get("reset", False)
	if type(do_attribute) is not bool or type(reset) is not bool or (reset and not do_attribute):
		return make_response({"error": "Invalid ranking or reset option"}, 400)
	user_id = g.auth_token.id
	ranking = DocumentBaseStartRanking()
	args = (user_id, do_attribute, reset, attribute)
	replay = ranking.existing_submission(args, **g.feedback_options)
	if replay is not None:
		return make_response({'task_id': replay.id}, 202)
	session = SessionState(user_id, scope["base_id"], scope["session_id"])
	expected_version = g.feedback_options["expected_version"]
	publication = session.metadata()
	if (publication["closed"] or publication["phase"] != "selection" or
		publication["version"] != expected_version or publication["attribute"] != attribute):
		return make_response({"error": "This attribute is no longer waiting to start. Refresh the session."}, 409)
	task = ranking.apply_async(args=args, **g.feedback_options)
	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/reload', methods=['POST'])
def reload_document_base():
	"""Refresh a feedback step or resolve a pending decision conflict.

	JSON needs sessionId, expectedVersion, commandId and optional conflictResolution.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	"""
	authorization = request.headers.get("Authorization")
	if authorization is None:
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is None:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	resolution = request.get_json().get("conflictResolution")
	if resolution is not None and resolution not in ("keep", "replace"):
		return make_response({"error": "Choose whether to keep or replace the saved decision."}, 400)
	args = (user_id,) if resolution is None else (user_id, resolution)
	task = ReloadDocumentBaseTask().apply_async(args=args, **g.feedback_options)

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/confirm/nugget/custom', methods=['POST'])
def confirm_nugget_custom():
	"""Confirm an exact custom span for the current ranked attribute.

	JSON needs sessionId, expectedVersion, commandId, scope and exact code-point spans.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	"""
	form = request.get_json()
	name, content, start, end, negative_text, negative_start, negative_end = _feedback_selection(form)
	task = DocumentBaseConfirmNugget().apply_async(args=(
		g.auth_token.id, form.get("baseName"), g.organisation_id, name, content,
		form["nuggetText"], start, end, negative_text, negative_start, negative_end), **g.feedback_options)
	return make_response({"task_id": task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/match', methods=['POST'])
def confirm_nugget_match():
	"""Confirm an existing candidate at an exact span for this session.

	JSON needs sessionId, expectedVersion, commandId, scope and the exact candidate span.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	"""
	form = request.get_json()
	name, content, start, end, negative_text, negative_start, negative_end = _feedback_selection(form)
	task = DocumentBaseConfirmNugget().apply_async(args=(
		g.auth_token.id, form.get("baseName"), g.organisation_id, name, content,
		None, start, end, negative_text, negative_start, negative_end), **g.feedback_options)
	return make_response({"task_id": task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/multiple', methods=['POST'])
def confirm_nugget_multi_match():
	"""Confirm one selected match per document in a single scoped command.

	JSON needs sessionId, expectedVersion, commandId, scope and one match per document.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	:raises WorkLimitError: A source-document, corpus or other web work budget was exceeded.
	"""
	nuggets = request.get_json().get("nuggets")
	if not isinstance(nuggets, list) or not nuggets:
		return make_response({"error": "select at least one match"}, 400)
	if len(nuggets) > MAX_BASE_DOCUMENTS:
		raise WorkLimitError(f"Select matches from at most {MAX_BASE_DOCUMENTS} documents.")

	documents_and_nuggets = []
	documents = {}
	for selected in nuggets:
		if not isinstance(selected, dict):
			return make_response({"error": "invalid selection"}, 400)
		name, content = selected.get("documentName"), selected.get("documentContent")
		if not isinstance(name, str) or not name or "\0" in name or name in documents:
			return make_response({"error": "select one match per document"}, 400)
		start, end = _selection_span(content, selected.get("startIndex"), selected.get("endIndex"), selected.get("text"))
		documents[name] = content
		documents_and_nuggets.append((name, content, start, end))

	scope = g.feedback_scope
	user_id = g.auth_token.id
	args = (user_id, scope["base_name"], scope["organisation_id"], documents_and_nuggets)
	feedback = DocumentBaseConfirmMultipleNuggets()
	replay = feedback.existing_submission(args, **g.feedback_options)
	if replay is not None:
		return make_response({"task_id": replay.id}, 202)
	session = SessionState(user_id, scope["base_id"], scope["session_id"])
	publication = session.metadata()
	if (publication["closed"] or publication["phase"] != "ranking" or
		publication["version"] != g.feedback_options["expected_version"]):
		return make_response({"error": "This session is no longer waiting for this feedback. Refresh the session."}, 409)

	try:
		matched = get_document_ids_for_snapshot(scope["base_id"], scope["organisation_id"], user_id, documents)
	except RuntimeError:
		return make_response({"error": "Could not check the selected documents. Try again."}, 503)
	# Exact stored-text matches validate the spans without needing the legacy raw row ID.
	if documents.keys() - matched.keys():
		return make_response({"error": "document not found"}, 404)

	task = feedback.apply_async(args=args, **g.feedback_options)
	return make_response({"task_id": task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/none', methods=['POST'])
def confirm_no_match_in_document():
	"""Reject a candidate or record whole-document No Match in this session.

	JSON needs command identity/scope; empty text and zero offsets mean whole-document No Match.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
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
	"""Stop the current attribute and advance to the next attribute.

	JSON needs sessionId, expectedVersion and commandId; whole-session closure uses
	feedback/close.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
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

@core_routes.route('/document_base/feedback/close', methods=['POST'])
def close_feedback():
	"""Close this user's session while preserving saved canonical matches.

	JSON needs sessionId, expectedVersion and commandId; unresolved proposals may be discarded.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	"""
	task = DocumentBaseCloseFeedbackSession().apply_async(
		args=(g.auth_token.id,), **g.feedback_options)
	return make_response({"task_id": task.id}, 202)


def _public_feedback_document(form):
	"""Resolve an authorized source document and its canonical base scope.

	:param form: The parsed JSON submission containing the scoped mutation parameters.
	:type form: dict[str, object]
	:returns: The public feedback document result.
	:rtype: tuple[int, str, str, int | None]
	"""
	base_id = _positive_id(form.get("baseId"))
	if "baseId" in form and base_id is None:
		abort(make_response({"error": "invalid document base ID"}, 400))
	base_name = _base_reference(base_id=base_id)[1] if base_id is not None else form.get("baseName")
	user_id = g.auth_token.id
	if "documentId" in form:
		document_id = _positive_id(form.get("documentId"))
		if document_id is None:
			abort(make_response({"error": "invalid document ID"}, 400))
		_, content = get_document(document_id, user_id, g.organisation_id, base_name)
	else:
		document_id, _, content = get_document_by_name_and_content(
			form.get("documentName"), form.get("documentContent"), user_id,
			organisation_id=g.organisation_id, base_name=base_name)
	if document_id is None or content is None:
		abort(make_response({"error": "document not found"}, 404))
	return document_id, content, base_name, base_id


@core_routes.route('/document_base/feedback/public', methods=['POST'])
def add_public_feedback():
	"""Save feedback only for the source and canonical mapping displayed to the voter.

	Validate the displayed source/mapping identity before saving a vote or correction.

	:returns: The scoped JSON response or HTTP error; see ``ROUTES.md``.
	:rtype: flask.Response
	"""
	form = request.get_json()
	attribute, positive = form.get("attribute"), form.get("isPositive")
	attribute_id = form.get("attributeId")
	try:
		attribute_id = str(UUID(attribute_id))
	except (ValueError, TypeError, AttributeError):
		return make_response({"error": "A current attribute ID is required."}, 400)
	mapping_revision = form.get("mappingRevision")
	if not isinstance(mapping_revision, str) or not re.fullmatch(r"[a-f0-9]{64}", mapping_revision):
		return make_response({"error": "Reload the document to get its current mapping identity."}, 400)
	if type(positive) is not bool or not isinstance(form.get("documentContent"), str):
		return make_response({"error": "invalid document feedback"}, 400)

	document_id, content, base_name, base_id = _public_feedback_document(form)
	if form["documentContent"] != content:
		return make_response({"error": "The document changed. Reload before retrying."}, 409)
	start, end, text = form.get("startIndex"), form.get("endIndex"), form.get("nuggetText")
	no_match = form.get("noMatch", False)
	has_span = start is not None or end is not None or text is not None
	if type(no_match) is not bool or (no_match and has_span) or (positive and (no_match or has_span)):
		return make_response({"error": "A no-match correction requires a negative vote without a text selection."}, 400)
	if has_span:
		start, end = _selection_span(content, start, end, text)

	outcome = add_feedback(
		document_id=document_id, user_id=g.auth_token.id, positive=positive, attribute=attribute,
		feedback_start=start, feedback_end=end, organisation_id=g.organisation_id,
		expected_content=content, base_name=base_name, base_id=base_id, attribute_id=attribute_id, no_match=no_match, mapping_revision=mapping_revision)
	if outcome == -409:
		return make_response({"error": "The document changed or feedback conflicted. Reload before retrying."}, 409)
	if outcome == -422:
		return make_response({"error": "The attribute is no longer available. Reload before retrying."}, 422)
	if isinstance(outcome, int):
		return make_response({"error": "Could not save document feedback."}, -outcome)
	return make_response(outcome, 200)


@core_routes.route('/document_base/feedback/public/get', methods=['POST'])
def get_public_feedback():
	"""Read version-bound counts or page exact-occurrence correction suggestions.

	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	form = request.get_json()
	try:
		if "suggestionsOffset" in form:
			offset = form["suggestionsOffset"]
			if type(offset) is not int or not 0 <= offset <= 2147483647:
				return make_response({"error": "Invalid suggestion page offset."}, 400)
			page_size = 20
			if "documentId" in form or "documentName" in form:
				document_id, _, _, base_id = _public_feedback_document(form)
			else:
				base_id = _positive_id(form.get("baseId"))
				if base_id is None:
					return make_response({"error": "A valid document base ID is required."}, 400)
				_base_reference(base_id=base_id)
				document_id = None
			rows = get_public_feedback_suggestions(g.organisation_id, base_id, document_id, offset, page_size + 1, user_id=g.auth_token.id)
			return make_response({"suggestions": rows[:page_size],
				"nextOffset": offset + page_size if len(rows) > page_size else None,
				"canReview": g.organisation_role == 0}, 200)
		if (not isinstance(form.get("documentContent"), str) or
			not isinstance(form.get("attributeIds"), dict) or not isinstance(form.get("expectedMappings"), dict)):
			return make_response({"error": "The displayed document, attributes and mappings are required."}, 400)
		document_id, _, _, _ = _public_feedback_document(form)
		feedback = get_feedbacks_for_document(document_id, g.auth_token.id,
			expected_content=form["documentContent"], expected_attribute_ids=form["attributeIds"],
			expected_mappings=form["expectedMappings"])
	except RuntimeError:
		return make_response({"error": "Document feedback is temporarily unavailable."}, 503)
	return make_response({"feedback": feedback}, 200)


@core_routes.route('/document_base/feedback/public/review', methods=['POST'])
def review_public_feedback():
	"""Enqueue an owner decision using the full displayed suggestion identity.

	:returns: The HTTP response containing the scoped result or a safe request error.
	:rtype: flask.Response
	"""
	if g.organisation_role != 0:
		return make_response({"error": "Organization owner access required."}, 403)
	form = request.get_json()
	base_id = _positive_id(form.get("baseId"))
	document_id = _positive_id(form.get("documentId"))
	accepted = form.get("accepted")
	suggestion_id = _positive_id(form.get("suggestionId"))
	try:
		attribute_id = str(UUID(form.get("attributeId")))
	except (ValueError, TypeError, AttributeError):
		return make_response({"error": "A current attribute ID is required."}, 400)
	revisions = ("suggestionVersion", "mappingRevision", "sourceRevision")
	if (base_id is None or document_id is None or suggestion_id is None or type(accepted) is not bool
		or any(not isinstance(form.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", form[key]) for key in revisions)
		or "startIndex" not in form or "endIndex" not in form):
		return make_response({"error": "Invalid suggestion review identity."}, 400)
	start, end = form["startIndex"], form["endIndex"]
	if (start is not None or end is not None) and (
		type(start) is not int or type(end) is not int or not 0 <= start < end):
		return make_response({"error": "Invalid suggestion span."}, 400)
	base_name = _base_reference(base_id=base_id)[1]
	review = {key: form[key] for key in (*revisions, "startIndex", "endIndex")}
	review.update(attributeId=attribute_id, suggestionId=suggestion_id)
	task = ReviewPublicSuggestion().apply_async(args=(g.auth_token.id, base_name, g.organisation_id, base_id,
		document_id, review, accepted), expected_base_id=base_id)
	return make_response({"task_id": task.id}, 202)
