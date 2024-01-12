from flask import Blueprint, request, make_response

from wannadb_web.postgres.queries import getDocument
from wannadb_web.util import tokenDecode
from wannadb_web.postgres.transactions import addDocument

main_routes = Blueprint('main_routes', __name__, url_prefix='/data')


@main_routes.route('/file', methods=['POST'])
def upload_files():
	files = request.files.getlist('file')
	form = request.form

	authorization = request.headers.get("authorization")
	organisation_id = int(form.get("organisationId"))

	token = tokenDecode(authorization)

	document_ids: list = []

	for file in files:
		content_type = file.content_type
		if 'text/plain' in content_type:
			filename = file.filename
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


@main_routes.route('/file/<_id>', methods=['GET'])
def get_file(_id):
	print(request.json)
	authorization = request.json.get("authorization")
	document_id = int(_id)

	token = tokenDecode(authorization)

	document_ids: list = []

	document = getDocument(document_id, token.id)

	if document is None:
		return make_response(document_ids, 404)
	if isinstance(document, str):
		return make_response(document, 200)
	if isinstance(document, bytes):
		return make_response(document, 206)
