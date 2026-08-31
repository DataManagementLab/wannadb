from flask import Blueprint, request, make_response
from flask_cors import cross_origin

from wannadb_web.worker.tasks import DocumentBaseAddDocument, DocumentBaseRemoveDocument, DocumentBaseUpdateDocument
from wannadb_web.postgres.queries import delete_document_content, get_base_id, get_document, get_document_bases_for_organisation, get_document_by_name, get_document_by_name_and_content, get_documents_for_organisation, \
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
		print(f"base_name: {base_name}")
		base_id = get_base_id(base_name, organisation_id)
		print(f"base_id: {base_id}")
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
			document_id, document_name = add_document(filename, content, organisation_id, token.id, base_id)
			if isinstance(document_id, int) and base_id is not None:
				# if the document was added successfully and a base_id was provided, we trigger the celery task to update the attributes of the document base
				DocumentBaseAddDocument().apply_async(args=(token.id, document_name, content, base_name, organisation_id))
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

@main_routes.route('/update/file/content', methods=['PUT'])
def update_file_content():
	authorization = request.headers.get("Authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json()
	doc_name = data.get('documentName')
	newContent = data.get('newContent')
	base_name = data.get('baseName')
	organisation_id = data.get('organisationId')
	if doc_name is None or newContent is None or organisation_id is None or base_name is None:
		return make_response({'error': 'missing parameters'}, 400)

	try:
		doc_id, _ = get_document_by_name(doc_name, organisation_id, token.id)
	except Exception as e:
		print(f"Error retrieving document by name: {e}")
		return make_response({'error': 'document not found'}, 404)
	status = update_document_content(doc_id, newContent)

	if status:
		DocumentBaseUpdateDocument().apply_async(args=(token.id, doc_name, newContent, base_name, organisation_id))
		print(f"Document with id {doc_id} updated successfully.")
		return make_response({"status": status}, 200)
	else:
		print(f"Failed to update document with id {doc_id}.")
		return make_response({"status": status}, 400)

@main_routes.route('/file/delete', methods=['DELETE'])
def delete_file():
	authorization = request.headers.get("Authorization")
 
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

 
	data = request.get_json()
	docId = data.get('documentId')
	print(f"Received request to delete document with id: {docId}")
	base_name = data.get('baseName')
	organisation_id = data.get('organisationId')
	doc_name = data.get('documentName')
	if docId is None:
		return make_response({'error': 'missing parameters'}, 400)
	if docId == -1 and (doc_name is None or organisation_id is None):
		return make_response({'error': 'missing parameters'}, 400)
	if docId == -1 and doc_name is not None and organisation_id is not None:
		docId, _ = get_document_by_name(doc_name, organisation_id, token.id)
		document_name = doc_name
	else:
		document_name, _ = get_document(docId, token.id)
	if document_name is None:
		return make_response({'error': 'document not found'}, 404)
	status = delete_document_content(docId)

	if base_name is not None and organisation_id is not None:
		DocumentBaseRemoveDocument().apply_async(args=(token.id, document_name, base_name, organisation_id))

	if status:
		print(f"Document with id {docId} deleted successfully.")
		return make_response({"status": status}, 200)
	else:
		print(f"Failed to delete document with id {docId}.")
		return make_response({"status": status}, 400)

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
