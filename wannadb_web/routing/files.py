from flask import Blueprint, request, make_response, abort, g
from flask_cors import cross_origin

from wannadb_web.limits import MAX_FILE_BYTES, MAX_UPLOAD_FILES, WorkLimitError, validate_document_text
from wannadb_web.worker.tasks import DocumentBaseAddDocument, DocumentBaseRemoveDocument, DocumentBaseUpdateDocument
from wannadb_web.postgres.queries import delete_document_content, get_base_id, get_document, get_document_bases_for_organisation, get_document_by_name, get_documents_for_organisation, get_document_scope, get_organisation_authorisation

from wannadb_web.util import tokenDecode
from wannadb_web.postgres.transactions import add_document

main_routes = Blueprint('main_routes', __name__, url_prefix='/data')


@main_routes.before_request
def authenticate_files():
	if request.method == 'OPTIONS':
		return None
	g.auth_token = tokenDecode(request.headers.get('Authorization'))
	if g.auth_token is None:
		return make_response({'error': 'no authorization'}, 401)


def _positive_id(value):
	if isinstance(value, bool) or not isinstance(value, (int, str)):
		abort(make_response({'error': 'invalid ID'}, 400))
	try:
		value = int(value)
	except (ValueError, TypeError):
		abort(make_response({'error': 'invalid ID'}, 400))
	if value <= 0 or value > 9223372036854775807:
		abort(make_response({'error': 'invalid ID'}, 400))
	return value


def _require_organisation(value):
	organisation_id = _positive_id(value)
	try:
		role = get_organisation_authorisation(g.auth_token.id, organisation_id, raise_on_error=True)
	except RuntimeError:
		abort(make_response({'error': 'Organization access checks are temporarily unavailable.'}, 503))
	if role is None:
		abort(make_response({'error': 'organization access denied'}, 403))
	return organisation_id


@main_routes.route('/upload/file', methods=['POST'])
@cross_origin(origins=["http://localhost:3000"])
def upload_files():
    
	files = request.files.getlist('file')
	if len(files) > MAX_UPLOAD_FILES:
		raise WorkLimitError(f"Upload at most {MAX_UPLOAD_FILES} files at once.")
	form = request.form
	organisation_id = _require_organisation(form.get("organisationId"))
	base_name = form.get("baseName")
	expected_base_id = _positive_id(form["baseId"]) if "baseId" in form else None
	if expected_base_id is not None and base_name is None:
		return make_response({'error': 'a document base name is required'}, 400)
	if base_name is not None:
		if not base_name.strip():
			return make_response({'error': 'invalid document base'}, 400)
		try:
			base_id = get_base_id(base_name, organisation_id, raise_on_error=True)
		except RuntimeError:
			return make_response({'error': 'Document base metadata is temporarily unavailable.'}, 503)
		if base_id is None or (expected_base_id is not None and base_id != expected_base_id):
			return make_response({'error': 'document base not found'}, 404)

	user_id = g.auth_token.id
	documents = []
	document_ids = []
	errors = []
	for file in files:
		filename = file.filename
		content_type = file.mimetype or ''
		is_text_file = content_type == 'text/plain' or (
			content_type in ('', 'application/octet-stream') and (filename or '').lower().endswith('.txt')
		)
		if not is_text_file:
			error = f"{filename}: wrong type {content_type}"
		elif not filename or '\0' in filename:
			error = "The file needs a valid name."
		else:
			try:
				data = file.stream.read(MAX_FILE_BYTES + 1)
				if len(data) > MAX_FILE_BYTES:
					raise WorkLimitError(f"File exceeds the {MAX_FILE_BYTES}-byte limit.")
				content = data.decode('utf-8')
				if '\0' in content:
					raise ValueError("File contains a null character.")
				validate_document_text(content)
			except UnicodeDecodeError:
				error = f"{filename}: file must contain UTF-8 text"
			except (ValueError, WorkLimitError) as reason:
				error = f"{filename}: {reason}"
			else:
				if base_name is not None:
					documents.append([filename, content])
					continue
				document_id, _ = add_document(filename, content, organisation_id, user_id)
				if type(document_id) is int and document_id > 0:
					document_ids.append(document_id)
					continue
				error = f"{filename}: could not save file"
		errors.append(error)
		document_ids.append(error)

	if base_name is not None:
		if not documents:
			return make_response(errors or ["Select at least one text file."], 400)
		try:
			task = DocumentBaseAddDocument().apply_async(args=(user_id, documents, base_name, organisation_id),
				expected_base_id=base_id)
		except ValueError as error:
			return make_response({'error': str(error)}, 409)
		return make_response({'taskId': task.id, 'errors': errors}, 202)

	if not document_ids or all(isinstance(doc_id, str) for doc_id in document_ids):
		return make_response(document_ids, 400)
	if errors:
		return make_response(document_ids, 207)
	return make_response(document_ids, 201)


@main_routes.route('/organization/get/files/<_id>', methods=['GET'])
def get_files_for_organization(_id):
	authorization = request.headers.get("Authorization")
	org_id = _require_organisation(_id)

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	documents = get_documents_for_organisation(org_id)

	return make_response(documents, 200)

@main_routes.route('/organization/get/documentbase/<_id>', methods=['GET'])
def get_documentbase_for_organization(_id):
	authorization = request.headers.get("Authorization")
	org_id = _require_organisation(_id)

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	try:
		document_base = get_document_bases_for_organisation(org_id)
	except RuntimeError:
		return make_response({'error': 'Document base list is temporarily unavailable.'}, 503)

	return make_response(document_base, 200)

@main_routes.route('/update/file/content', methods=['PUT'])
def update_file_content():
	authorization = request.headers.get("Authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json(silent=True)
	if not isinstance(data, dict):
		return make_response({'error': 'invalid request'}, 400)
	doc_name = data.get('documentName')
	newContent = data.get('newContent')
	base_name = data.get('baseName')
	organisation_id = data.get('organisationId')
	if newContent is None or organisation_id is None:
		return make_response({'error': 'missing parameters'}, 400)
	organisation_id = _require_organisation(organisation_id)
	base_id = _positive_id(data["baseId"]) if "baseId" in data else None

	if not isinstance(newContent, str) or '\0' in newContent:
		return make_response({'error': 'content must be valid text'}, 400)
	try:
		validate_document_text(newContent)
	except ValueError:
		return make_response({'error': 'content must be valid UTF-8 text'}, 400)
	if "documentId" in data:
		doc_id = _positive_id(data["documentId"])
		doc_name, old_content = get_document(doc_id, token.id, organisation_id)
	else:
		if not isinstance(doc_name, str) or not isinstance(base_name, str) or not base_name:
			return make_response({'error': 'invalid document or base name'}, 400)
		try:
			doc_id, old_content = get_document_by_name(doc_name, organisation_id, token.id, base_name)
		except LookupError:
			return make_response({'error': 'document not found'}, 404)
	scope = get_document_scope(doc_id, token.id)
	if (scope is None or scope[0] != organisation_id or scope[2] is None or
		(base_id is not None and scope[1] != base_id) or (base_name is not None and scope[2] != base_name)):
		return make_response({'error': 'document not found'}, 404)
	base_name = scope[2]
	if "expectedContent" in data and data["expectedContent"] != old_content:
		return make_response({'error': 'The document changed. Reload before editing.'}, 409)
	if not isinstance(old_content, str):
		return make_response({'error': 'document is not a text file'}, 400)
	try:
		task = DocumentBaseUpdateDocument().apply_async(args=(
			token.id, doc_name, newContent, base_name, organisation_id, int(doc_id), old_content),
			expected_base_id=scope[1])
	except ValueError as error:
		return make_response({'error': str(error)}, 409)
	return make_response({'taskId': task.id}, 202)


@main_routes.route('/file/delete', methods=['DELETE'])
def delete_file():
	authorization = request.headers.get("Authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json(silent=True) or {}
	docId = data.get('documentId')
	base_name = data.get('baseName')
	organisation_id = data.get('organisationId')
	doc_name = data.get('documentName')
	if docId is None:
		return make_response({'error': 'missing parameters'}, 400)
	if docId == -1 and (doc_name is None or organisation_id is None):
		return make_response({'error': 'missing parameters'}, 400)
	if docId == -1 and doc_name is not None and organisation_id is not None:
		organisation_id = _require_organisation(organisation_id)
		try:
			docId, _ = get_document_by_name(doc_name, organisation_id, token.id, base_name)
		except Exception:
			return make_response({'error': 'document not found'}, 404)
		document_name = doc_name
	else:
		docId = _positive_id(docId)
		document_name, _ = get_document(docId, token.id)
	if document_name is None:
		return make_response({'error': 'document not found'}, 404)
	scope = get_document_scope(docId, token.id)
	if scope is None:
		return make_response({'error': 'document not found'}, 404)
	if organisation_id is not None and _require_organisation(organisation_id) != scope[0]:
		return make_response({'error': 'document not found'}, 404)
	if base_name is not None and base_name != scope[2]:
		return make_response({'error': 'document not found'}, 404)
	organisation_id, base_id, base_name = scope
	if base_name is not None:
		try:
			task = DocumentBaseRemoveDocument().apply_async(args=(
				token.id, document_name, base_name, organisation_id, int(docId)), expected_base_id=base_id)
		except ValueError as error:
			return make_response({'error': str(error)}, 409)
		return make_response({'taskId': task.id}, 202)

	status = delete_document_content(docId, organisation_id, base_id, token.id)
	if status:
		print(f"Document with id {docId} deleted successfully.")
		return make_response({"status": status}, 200)
	else:
		print(f"Failed to delete document with id {docId}.")
		return make_response({"status": status}, 400)

@main_routes.route('/get/file/<_id>', methods=['GET'])
def get_file(_id):
 
	authorization = request.headers.get("Authorization")
	document_id = _positive_id(_id)

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	document_ids: list = []

	_, document = get_document(document_id, token.id)

	if document is None:
		return make_response(document_ids, 404)
	if isinstance(document, str):
		return make_response(document, 200, {"Content-Type": "text/plain; charset=utf-8"})
	if isinstance(document, bytes):
		return make_response(document, 206)
