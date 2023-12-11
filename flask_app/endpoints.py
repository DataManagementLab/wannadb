from flask import Blueprint, request,jsonify
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from config import decode

from postgres.transactions import addDocument

main_routes = Blueprint('main_routes', __name__, url_prefix='/data')


@main_routes.route('/upload', methods=['POST'])
def upload_files():
	try:
		files = request.files
		form = request.form

		authorization = form.get("authorization")
		organisation_id = form.get("organisationid")

		token = decode(authorization)

		dokument_ids: list[int] = []

		for _filename, storage in files.items():
			filename = secure_filename(_filename)
			t = storage.read()
			dokument_id = addDocument(filename, t, organisation_id, token.id)
			dokument_ids.append(dokument_id)

		return jsonify(dokument_ids)

	except Exception as e:
		raise Exception("upload files failed because: \n", e)
