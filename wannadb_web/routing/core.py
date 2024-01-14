"""
core_routes Module

This module defines Flask routes for the 'core' functionality of the Wannadb UI.

It includes a Blueprint named 'core_routes' with routes related to creating document bases.

Routes:
    - /core/create_document_base (POST): Endpoint for creating a document base.


Dependencies:
    - Flask: Web framework for handling HTTP requests and responses.
    - config.tokenDecode: Function for decoding authorization tokens.
    - wannadb_ui.wannadb_api.WannaDBAPI: API for interacting with Wannadb.

Example:
    To create a Flask app and register the 'core_routes' Blueprint:

    ```python
    from flask import Flask
    from core_routes import core_routes

    app = Flask(__name__)
    app.register_blueprint(core_routes)
    ```

Author: Leon Wenderoth
"""
import logging.config
import pickle

from celery.result import AsyncResult
from flask import Blueprint, make_response, jsonify, url_for, request

from wannadb.data.data import Attribute
from wannadb.statistics import Statistics
from wannadb_web.util import tokenDecode
from wannadb_web.worker.tasks import create_document_base_task, long_task
from wannadb_web.worker.util import TaskObject

core_routes = Blueprint('core_routes', __name__, url_prefix='/core')

logger = logging.getLogger(__name__)


@core_routes.route('/document_base', methods=['POST'])
def create_document():
	"""
    Endpoint for creating a document base.

	This endpoint is used to create a document base from a list of document ids and a list of attributes.

	Example Header:
	{
		"Authorization": "your_authorization_token"
	}

    Example JSON Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "document_ids": [
        1, 2, 3
        ],
        "attributes": [
        "plane","car","bike"
        ]
    }
    """
	form = request.form
	authorization = request.headers.get("authorization")
	authorization = form.get("authorization")
	organisation_id = form.get("organisationId")
	base_name = form.get("baseName")
	document_ids = form.get("document_ids")
	attributes = form.get("attributes")
	_token = tokenDecode(authorization)

	statistics = Statistics(False)
	user_id = _token.id

	attributesDump = pickle.dumps(attributes)
	statisticsDump = pickle.dumps(statistics)

	task = create_document_base_task.apply_async(args=(user_id, document_ids, attributesDump, statisticsDump,
													   base_name,organisation_id))

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/longtask', methods=['POST'])
def longtask():
	task = long_task.apply_async()
	return jsonify(str(task.id)), 202, {'Location': url_for('core_routes.task_status',
															task_id=task.id)}


@core_routes.route('/status/<string:task_id>')
def task_status(task_id):
	task: AsyncResult = AsyncResult(task_id)
	print(task.status)
	meta = task.info
	if meta is None:
		return make_response({"error": "task not found"}, 404)
	if task.status == "FAILURE":
		return make_response(
			{"state": "FAILURE", "meta": str(meta)}, 500)
	print(meta)
	if not isinstance(meta, bytes):
		return make_response({"error": "task not correct"}, 404)

	taskObject = TaskObject.from_dump(meta)
	return make_response({"state": taskObject.state.value, "meta": taskObject.signals.to_json(), "msg": taskObject.msg},
						 200)
