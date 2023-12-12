from flask import Blueprint, request, make_response

from config import tokenDecode
from postgres.transactions import addDocument

main_routes = Blueprint('main_routes', __name__, url_prefix='/data')


@main_routes.route('/upload', methods=['POST'])
def upload_files():
	try:
		files = request.files.getlist('file')
		form = request.form

		authorization = form.get("authorization")
		organisation_id = int(form.get("organisationId"))

		token = tokenDecode(authorization)

		document_ids: list = []

		for file in files:
			content_type = file.content_type
			if 'text/plain' in content_type:
				filename = file.filename
				content = str(file.stream.read().decode('utf-8'))
				dokument_id = addDocument(filename, content, organisation_id, token.id)
				print(dokument_id)
				document_ids.append(dokument_id)
			else:
				document_ids.append(f"wrong type {content_type}")

		if all(isinstance(document_ids, str) for _ in document_ids):
			return make_response(document_ids, 400)
		if any(isinstance(document_ids, str) for _ in document_ids):
			return make_response(document_ids, 207)
		return make_response(document_ids, 201)

	except Exception as e:
		return make_response({"message": "Upload failed", "details": str(e)}, 500)
