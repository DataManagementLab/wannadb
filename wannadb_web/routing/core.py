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
from typing import Optional

from celery.result import AsyncResult
from flask import Blueprint, make_response, request

from wannadb.data.data import Attribute
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache
from wannadb_web.util import tokenDecode
from wannadb_web.worker.data import Signals
from wannadb_web.worker.tasks import CreateDocumentBase, BaseTask, DocumentBaseAddAttributes

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
        "document_ids": "1, 2, 3",
        "attributes": "plane,car,bike"
    }
    """
	form = request.form
	authorization = form.get("authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
	document_ids: Optional[list[int]] = form.get("document_ids")
	attributes_strings = form.get("attributes")
	if (organisation_id is None or base_name is None or document_ids is None or attributes_strings is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	attributes_strings = attributes_strings.split(",")
	document_ids = document_ids.split(",")

	statistics = Statistics(False)
	user_id = _token.id

	statisticsDump = pickle.dumps(statistics)
	task = CreateDocumentBase().apply_async(args=(user_id, document_ids, attributes_strings, statisticsDump,
												  base_name, organisation_id))

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/attributes', methods=['UPDATE'])
def document_base():
	"""
    Endpoint for update a document base.

	This endpoint is used to update a document base from a list of attributes.

    Example Form Payload:
    {
		"authorization": "your_authorization_token"
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "attributes": "plane,car,bike"
    }
    """
	form = request.form
	authorization = form.get("authorization")
	organisation_id = form.get("organisationId")
	base_name = form.get("baseName")
	attributes_string = form.get("attributes")
	if (organisation_id is None or base_name is None or attributes_string is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	attributes_strings = attributes_strings.split(",")

	attributes = []
	for att in attributes_string:
		attributes.append(Attribute(att))

	statistics = Statistics(False)
	user_id = _token.id

	#attributesDump = pickle.dumps(attributes)
	#statisticsDump = pickle.dumps(statistics)
	task = DocumentBaseAddAttributes().apply_async(args=(user_id, attributes_strings,
												  base_name, organisation_id))

	return make_response({'task_id': task.id}, 202)


# @core_routes.route('/longtask', methods=['POST'])
# def longtask():
# 	task = long_task.apply_async()
# 	return jsonify(str(task.id)), 202, {'Location': url_for('core_routes.task_status',
# 															task_id=task.id)}


@core_routes.route('/status/<token>/<task_id>', methods=['GET'])
def task_status(token: str,task_id: str):
 
	_token = tokenDecode(token)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)
	user_id = _token.id
 
	task: AsyncResult = BaseTask().AsyncResult(task_id=task_id)
	status = task.status
	if status == "FAILURE":
		return make_response({"state": "FAILURE", "meta": Signals(user_id).to_json()}, 500)
	if status == "SUCCESS":
		return make_response({"state": "SUCCESS", "meta": Signals(user_id).to_json()}, 200)
	if status is None:
		return make_response({"error": "task not found"}, 500)
	return make_response({"state": task.status, "meta": Signals(user_id).to_json()}, 202)


@core_routes.route('/status/<task_id>', methods=['POST'])
def task_update(task_id: str):
	signals = Signals(task_id)

	## todo: hier muss feedback emitted werden im format:
	## {	------------------	}

	signals.feedback_request_from_ui.emit(request.json.get("feedback"))
