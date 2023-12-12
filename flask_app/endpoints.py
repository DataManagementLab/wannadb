from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from config import tokenDecode
from postgres.transactions import addDocument

main_routes = Blueprint('main_routes', __name__, url_prefix='/data')


@main_routes.route('/upload', methods=['POST'])
def upload_files():
	try:
		files = request.files.getlist('files')
		form = request.form

		authorization = form.get("authorization")
		organisation_id = int(form.get("organisationId"))

		token = tokenDecode(authorization)

		dokument_ids: list[int] = []

		for file in files:
			file_content = file.read()
			filename = file.filename
			content = str(file_content.tokenDecode('utf-8'))
			dokument_id = addDocument(filename, content, organisation_id, token.id)
			dokument_ids.append(dokument_id)

		return jsonify(dokument_ids)

	except Exception as e:
		raise Exception("upload files failed because: \n", e)
