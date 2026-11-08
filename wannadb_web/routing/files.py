from flask import Blueprint, request, make_response, abort, g
from flask_cors import cross_origin

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
	if get_organisation_authorisation(g.auth_token.id, organisation_id) is None:
		abort(make_response({'error': 'organization access denied'}, 403))
	return organisation_id


@main_routes.route('/upload/file', methods=['POST'])
@cross_origin(origins=["http://localhost:3000"])
def upload_files():
    
	files = request.files.getlist('file')
	form = request.form
	organisation_id = _require_organisation(form.get("organisationId"))
	base_name = form.get("baseName")
	if base_name is not None:
		if not base_name.strip():
			return make_response({'error': 'invalid document base'}, 400)
		if get_base_id(base_name, organisation_id) is None:
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
				content = file.stream.read().decode('utf-8')
			except UnicodeDecodeError:
				error = f"{filename}: file must contain UTF-8 text"
			else:
				if '\0' in content:
					error = f"{filename}: file contains a null character"
				elif base_name is not None:
					documents.append([filename, content])
					continue
				else:
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
		task = DocumentBaseAddDocument().apply_async(args=(user_id, documents, base_name, organisation_id))
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


	document_base = get_document_bases_for_organisation(org_id)

	return make_response(document_base, 200)

@main_routes.route('/update/file/content', methods=['PUT'])
def update_file_content():
	authorization = request.headers.get("Authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json(silent=True) or {}
	doc_name = data.get('documentName')
	newContent = data.get('newContent')
	base_name = data.get('baseName')
	organisation_id = data.get('organisationId')
	if doc_name is None or newContent is None or organisation_id is None or base_name is None:
		return make_response({'error': 'missing parameters'}, 400)
	organisation_id = _require_organisation(organisation_id)
	if not isinstance(doc_name, str) or not isinstance(base_name, str) or not base_name:
		return make_response({'error': 'invalid document or base name'}, 400)

	if not isinstance(newContent, str) or '\0' in newContent:
		return make_response({'error': 'content must be valid text'}, 400)
	try:
		doc_id, old_content = get_document_by_name(doc_name, organisation_id, token.id, base_name)
	except Exception:
		return make_response({'error': 'document not found'}, 404)
	scope = get_document_scope(doc_id, token.id)
	if scope is None or scope[0] != organisation_id or scope[2] != base_name:
		return make_response({'error': 'document not found'}, 404)
	if not isinstance(old_content, str):
		return make_response({'error': 'document is not a text file'}, 400)
	task = DocumentBaseUpdateDocument().apply_async(args=(
		token.id, doc_name, newContent, base_name, organisation_id, int(doc_id), old_content))
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
		task = DocumentBaseRemoveDocument().apply_async(args=(
			token.id, document_name, base_name, organisation_id, int(docId)))
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
		return make_response(document, 200)
	if isinstance(document, bytes):
		return make_response(document, 206)
