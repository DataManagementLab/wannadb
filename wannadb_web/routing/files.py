from flask import Blueprint, request, make_response

from wannadb_web.postgres.queries import deleteDocumentContent, getDocument, getDocumentsForOrganization, updateDocumentContent
from wannadb_web.util import tokenDecode
from wannadb_web.postgres.transactions import addDocument

main_routes = Blueprint('main_routes', __name__, url_prefix='/data')


@main_routes.route('/upload/file', methods=['POST'])
def upload_files():
    
	files = request.files.getlist('file')
	form = request.form

	authorization = request.headers.get("authorization")
	organisation_id = int(form.get("organisationId"))

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	document_ids: list = []

	for file in files:
		content_type = file.content_type
		if 'text/plain' in content_type:
			filename = file.filename
			print("name:" + filename) 
			content = str(file.stream.read().decode('utf-8'))
			dokument_id = addDocument(filename, content, organisation_id, token.id)
			document_ids.append(dokument_id)
		else:
			document_ids.append(f"wrong type {content_type}")

	if all(isinstance(document_ids, str) for _ in document_ids):
		return make_response(document_ids, 400)
	if any(isinstance(document_ids, str) for _ in document_ids):
		return make_response(document_ids, 207)
	return make_response(document_ids, 201)


@main_routes.route('/organization/get/files/<_id>', methods=['GET'])
def get_files_for_organization(_id):
	authorization = request.headers.get("authorization")
	org_id = int(_id)

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	documents = getDocumentsForOrganization(org_id)

	return make_response(documents, 200)

@main_routes.route('/update/file/content', methods=['POST'])
def update_file_content():
	authorization = request.headers.get("authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json()
	docId = data.get('documentId')
	newContent = data.get('newContent')

	status = updateDocumentContent(docId, newContent)

	return make_response({"status": status}, 200)

@main_routes.route('/file/delete', methods=['POST'])
def delete_file():
	authorization = request.headers.get("authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json()
	docId = data.get('documentId')
 
	status = deleteDocumentContent(docId)

	return make_response({"status": status}, 200)

@main_routes.route('/get/file/<_id>', methods=['GET'])
def get_file(_id):
 
	authorization = request.headers.get("authorization")
	document_id = int(_id)

	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)


	document_ids: list = []

	document = getDocument(document_id, token.id)

	if document is None:
		return make_response(document_ids, 404)
	if isinstance(document, str):
		return make_response(document, 200)
	if isinstance(document, bytes):
		return make_response(document, 206)
