from flask import Blueprint, request, jsonify

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

		dokument_ids: list = []

		for file in files:
			content_type = file.content_type
			if 'text/plain' in content_type:
				filename = file.filename
				content = str(file.stream.read().decode('utf-8'))
				dokument_id = addDocument(filename, content, organisation_id, token.id)
				print(dokument_id)
				dokument_ids.append(dokument_id)
			else:
				dokument_ids.append(f"wrong type {content_type}")

		return jsonify(dokument_ids)

	except Exception as e:
		raise Exception("upload files failed because: \n", e)
