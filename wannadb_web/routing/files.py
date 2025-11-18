from flask import Blueprint, request, make_response
from flask_cors import cross_origin

from wannadb_web.postgres.queries import delete_document_content, get_base_id, get_document, get_document_bases_for_organisation, get_documents_for_organisation, \
	update_document_content

from wannadb_web.util import tokenDecode
from wannadb_web.postgres.transactions import add_document

main_routes = Blueprint('main_routes', __name__, url_prefix='/data')


@main_routes.route('/upload/file', methods=['POST'])
@cross_origin(origins=["http://localhost:3000"])
def upload_files():
    
	files = request.files.getlist('file')
	form = request.form

	authorization = request.headers.get("Authorization")
	organisation_id = int(form.get("organisationId"))

	base_name = form.get("baseName")
	if (base_name is not None):
		base_id = get_base_id(base_name, organisation_id)
		if base_id is None:
			# if document base name was passed but no id could be found, we return a 404 for resource not found
			return make_response({'error': 'document base not found'}, 404)
	else:
		base_id = None

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	document_ids: list = []

	for file in files:
		content_type = file.content_type
		if 'text/plain' in content_type:
			filename = file.filename
			content = str(file.stream.read().decode('utf-8'))
			document_id = add_document(filename, content, organisation_id, token.id, base_id)
			document_ids.append(document_id)
		else:
			document_ids.append(f"wrong type {content_type}")

	if all(isinstance(doc_id, str) for doc_id in document_ids):
		return make_response(document_ids, 400)
	if any(isinstance(doc_id, str) for doc_id in document_ids):
		return make_response(document_ids, 207)
	return make_response(document_ids, 201)


@main_routes.route('/organization/get/files/<_id>', methods=['GET'])
def get_files_for_organization(_id):
	authorization = request.headers.get("Authorization")
	org_id = int(_id)

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	documents = get_documents_for_organisation(org_id)

	return make_response(documents, 200)

@main_routes.route('/organization/get/documentbase/<_id>', methods=['GET'])
def get_documentbase_for_organization(_id):
	authorization = request.headers.get("Authorization")
	org_id = int(_id)

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	document_base = get_document_bases_for_organisation(org_id)

	return make_response(document_base, 200)

@main_routes.route('/update/file/content', methods=['POST'])
def update_file_content():
	authorization = request.headers.get("Authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json()
	docId = data.get('documentId')
	newContent = data.get('newContent')

	status = update_document_content(docId, newContent)

	return make_response({"status": status}, 200)

@main_routes.route('/file/delete', methods=['POST'])
def delete_file():
	authorization = request.headers.get("Authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json()
	docId = data.get('documentId')
 
	status = delete_document_content(docId)

	return make_response({"status": status}, 200)

@main_routes.route('/get/file/<_id>', methods=['GET'])
def get_file(_id):
 
	authorization = request.headers.get("Authorization")
	document_id = int(_id)

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	document_ids: list = []

	document = get_document(document_id, token.id)

	if document is None:
		return make_response(document_ids, 404)
	if isinstance(document, str):
		return make_response(document, 200)
	if isinstance(document, bytes):
		return make_response(document, 206)
