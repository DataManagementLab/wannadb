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
import asyncio
import logging.config
import pickle
from typing import Optional

from wannadb_web.postgres.queries import get_document_base_data
from wannadb_web.postgres.transactions import addDocumentBase

from flask import Blueprint, make_response, request
from celery.result import AsyncResult
from wannadb.data.data import Attribute, Document, InformationNugget, DocumentBase
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache
from wannadb_web.util import tokenDecode
from wannadb_web.worker.data import Signals

from wannadb_web.worker.tasks import CreateDocumentBase, BaseTask, DocumentBaseAddAttributes, DocumentBaseConfirmMultipleNuggets, DocumentBaseConfirmNugget, DocumentBaseInteractiveTablePopulation, DocumentBaseLoad, DocumentBaseNoMatchForDocument, DocumentBaseStartRanking, DocumentBaseStopMatching, \
	DocumentBaseUpdateAttributes, DocumentBaseGetOrderedNuggets, ReloadDocumentBaseTask


core_routes = Blueprint('core_routes', __name__, url_prefix='/core')

logger = logging.getLogger(__name__)


@core_routes.route('/document_base', methods=['POST'])
def create_document_base():
	"""
    Endpoint for creating a document base.

	This endpoint is used to create a document base from a list of document ids and a list of attributes.

	Header:
    {
        "Authorization": "your_authorization_token"
    }

    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "document_ids": "1, 2, 3",
        "attributes": "plane,car,bike"
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
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

	attributes = attributes_strings.split(",")
	document_ids = document_ids.split(",")

	statistics = Statistics(False)
	user_id = _token.id

	statisticsDump = pickle.dumps(statistics)
	task = CreateDocumentBase().apply_async(args=(user_id, document_ids, attributes, statisticsDump,
												  base_name, organisation_id))

	doc_base_id = addDocumentBase(base_name, attributes, organisation_id, document_ids)
	if doc_base_id < 0:
		return make_response({"error": "Duplicated Entry!" if doc_base_id == -409 else "An error occured!"}, -doc_base_id)

	return make_response({'task_id': task.id, 'id': doc_base_id}, 202)

@core_routes.route('/document_base/<organisation_id>/<base_name>', methods=['GET'])
def get_document_base(organisation_id: int, base_name: str):
	"""
	Endpoint for retrieving a document base using it's name und organisation id
	"""
	authorization = request.headers.get("Authorization")
	if (authorization is None or organisation_id is None or base_name is None):
		return make_response({'error': 'missing parameters'}, 400)
	
	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({'error': 'invalid token'}, 401)
	
	document_base = get_document_base_data(base_name, organisation_id)
	if document_base is None:
		return make_response({'error': 'document base not found'}, 404)
	
	return make_response({"data": document_base}, 200)

@core_routes.route('/document_base/load', methods=['POST'])
def load_document_base():

	"""
    Endpoint for loading a document base.

	This endpoint is used to load a document base from a name and an organisation id.

	Header:
    {
        "Authorization": "your_authorization_token"
    }

    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
	if (organisation_id is None or base_name is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseLoad().apply_async(args=(user_id, base_name, organisation_id))

	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/interactive', methods=['POST'])
def interactive_document_base():
	"""
    Endpoint for interactive document population

	This endpoint is used to load a document base from a name and an organisation id.

	Header:
	{
		"Authorization": "your_authorization_token"
	}

    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
 
	if (organisation_id is None or base_name is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseInteractiveTablePopulation().apply_async(args=(user_id, base_name, organisation_id))

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/attributes/add', methods=['POST'])
def document_base_attribute_add():
	"""
    Endpoint for add attributes to a document base.

	This endpoint is used to add attributes to a document base from a list of attributes.

	Header:
	{
		"Authorization": "your_authorization_token"
	}
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "attributes": "plane,car,bike"
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id = form.get("organisationId")
	base_name = form.get("baseName")
	attributes_string = form.get("attributes")
	if (organisation_id is None or base_name is None or attributes_string is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	attributes_strings = attributes_string.split(",")


	attributes = []
	for att in attributes_strings:
		attributes.append(Attribute(att))

	statistics = Statistics(False)
	user_id = _token.id

	#attributesDump = pickle.dumps(attributes)
	#statisticsDump = pickle.dumps(statistics)
	task = DocumentBaseAddAttributes().apply_async(args=(user_id, attributes_strings,
												  base_name, organisation_id))

	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/attributes/update', methods=['POST'])
def document_base_attribute_update():
	"""
    Endpoint for update the attributes of a document base.

	This endpoint is used to update the attributes of a document base from a list of attributes.

	Header:
	{
		"Authorization": "your_authorization_token"
	}
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "attributes": "plane,car,bike"
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id = form.get("organisationId")
	base_name = form.get("baseName")
	attributes_string = form.get("attributes")
	if (organisation_id is None or base_name is None or attributes_string is None
			or authorization is None):
		return make_response({"error": "missing parameters"}, 400)
	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	attributes_strings = attributes_string.split(",")

	#attributes = []
	#for att in attributes_string:
	#	attributes.append(Attribute(att))
	#
	#statistics = Statistics(False)
 
	user_id = _token.id

	task = DocumentBaseUpdateAttributes().apply_async(args=(
     														user_id, 
                   											attributes_strings,
												  			base_name, 
                 											organisation_id
                            							))

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
		signals = Signals(user_id).to_json()
		return make_response({"state": "SUCCESS", "meta": signals}, 200)
	if status is None:
		return make_response({"error": "task not found"}, 500)

	signals = Signals(user_id).to_json()
	return make_response({"state": task.status, "meta": signals}, 202)


@core_routes.route('/status/<task_id>', methods=['POST'])
def task_update(task_id: str):
	signals = Signals(task_id)

	## todo: hier muss feedback emitted werden im format:
	## {	------------------	}

	signals.feedback_request_from_ui.emit(request.json.get("feedback"))

@core_routes.route('/document_base/do_current_attribute', methods=['POST'])
def document_base_do_current_attribute():
	"""
    Endpoint for giving feedback on doing the current attribute of a document base.

	Header:
	{
		"Authorization": "your_authorization_token"
	}
    Example Form Payload:
    {
		"do-attribute": true
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	do_attribute = form.get("doAttribute")
	if authorization is None or do_attribute is None:
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseStartRanking().apply_async(args=(user_id, do_attribute))

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/reload', methods=['POST'])
def reload_document_base():
	"""
    Endpoint for reloading the document base.

    Header:
    {
        "Authorization": "your_authorization_token"
    }
	No Body Parameters
    """
	authorization = request.headers.get("Authorization")
	if authorization is None:
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = ReloadDocumentBaseTask().apply_async(args=(user_id,))

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/order/nugget', methods=['POST'])
def sort_nuggets():
	"""
    Endpoint for creating a document base.

	This endpoint is used to create a document base from a list of document ids and a list of attributes.

	Header:
	{
		"Authorization": "your_authorization_token"
	}
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "documentName": "your_document_name",
        "documentContent": "your_document_content",
    }
    """
	form = request.get_json()
	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
	document_name = form.get("documentName")
	document_content = form.get("documentContent")
	if organisation_id is None or base_name is None or document_name is None or document_content is None or authorization is None:
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)
	
	if _token is False:
		return make_response({"error": "invalid token"}, 401)
	
	user_id = _token.id
	
	task = DocumentBaseGetOrderedNuggets().apply_async(args=(
     														user_id, 
                   											base_name, 
                              								organisation_id, 
                                      						document_name, 
                                            				document_content
                              							))
	
	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/custom', methods=['POST'])
def confirm_nugget_custom():
	"""
    Endpoint to confirm a custom nugget.

	Header:
    {
        "Authorization": "your_authorization_token"
    }
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "documentName": "your_document_name",
        "documentContent": "your_document_content",
        "nuggetText": "nugget_as_text",
        "startIndex": "start_index_of_nugget",
        "endIndex": "end_index_of_nugget",
        "interactiveCallTaskId": "interactive_call_task_id"
    }
    """
	form = request.get_json()

	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
 
	document_name = form.get("documentName")
	document_content = form.get("documentContent")
	nugget_text = form.get("nuggetText")
	start_index: Optional[int]  = form.get("startIndex")
	end_index: Optional[int]  = form.get("endIndex")
	
	i_task_id = form.get("interactiveCallTaskId")

	if (organisation_id is None 
     	or base_name is None 
      	or document_name is None 
       	or document_content is None 
        or authorization is None 
        or nugget_text is None 
        or start_index is None 
        or end_index is None 
        or i_task_id is None):
     
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)
	
	if _token is False:
		return make_response({"error": "invalid token"}, 401)
	
	user_id = _token.id
	
	task = DocumentBaseConfirmNugget().apply_async(args=(
     													user_id, 
                                                      	base_name, 
                                                       	organisation_id, 
                                                        document_name, 
                                                        document_content, 
                                                        nugget_text,
                                                        start_index,
                                                        end_index,
                                                        i_task_id
                                                    ))
	
	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/match', methods=['POST'])
def confirm_nugget_match():
	"""
    Endpoint to confirm a match nugget.

	Header:
    {
        "Authorization": "your_authorization_token"
    }
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "documentName": "your_document_name",
        "documentContent": "your_document_content",
        "nuggetText": "nugget_as_text",
        "startIndex": "start_index_of_nugget",
        "endIndex": "end_index_of_nugget",
        "interactiveCallTaskId": "interactive_call_task_id"
    }
    """
	form = request.get_json()

	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")
 
	document_name = form.get("documentName")
	document_content = form.get("documentContent")
	nugget_text = form.get("nuggetText")
	start_index: Optional[int]  = int(form.get("startIndex")) if form.get("startIndex") is not None else None
	end_index: Optional[int]  = int(form.get("endIndex")) if form.get("endIndex") is not None else None

	i_task_id = form.get("interactiveCallTaskId")

	if (organisation_id is None 
     	or base_name is None 
      	or document_name is None 
       	or document_content is None 
        or authorization is None 
        or nugget_text is None 
        or start_index is None 
        or end_index is None 
        or i_task_id is None):
     
		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)
	
	if _token is False:
		return make_response({"error": "invalid token"}, 401)
	
	user_id = _token.id
 
	document = Document(document_name, document_content)
 
	nugget = InformationNugget(document, start_index, end_index)
	
	task = DocumentBaseConfirmNugget().apply_async(args=(
     													user_id, 
                                                      	base_name, 
                                                       	organisation_id, 
                                                        document_name, 
                                                        document_content,
														None,
                                                        start_index,
                                                        end_index,
                                                        i_task_id
                                                    ))
	
	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/multiple', methods=['POST'])
def confirm_nugget_multi_match():
	"""
	Endpoint to confirm multiple match nuggets in a document.

	Header:
    {
        "Authorization": "your_authorization_token"
    }
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "nuggets": [
            {
                "documentName": "your_document_name_1",
				"documentContent": "your_document_content_1",
                "text": "nugget_as_text_1",
                "startIndex": "start_index_of_nugget_1",
                "endIndex": "end_index_of_nugget_1",
            },
            {
                "documentName": "your_document_name_2",
                "documentContent": "your_document_content_2",
                "text": "nugget_as_text_2",
                "startIndex": "start_index_of_nugget_2",
                "endIndex": "end_index_of_nugget_2",
            }
        ],
		"interactiveCallTaskId": "interactive_call_task_id"
    }
	"""
	form = request.get_json()

	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")

	nuggets = form.get("nuggets")

	if (organisation_id is None
       or base_name is None
       or authorization is None
       or nuggets is None):

		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	documents_and_nuggets = [(
		nugget.get("documentName"),
		nugget.get("documentContent"),
		nugget.get("startIndex"),
		nugget.get("endIndex")
	) for nugget in nuggets]

	task = DocumentBaseConfirmMultipleNuggets().apply_async(args=(
		user_id,
		base_name,
		organisation_id,
		documents_and_nuggets
	))

	return make_response({'task_id': task.id}, 202)

@core_routes.route('/document_base/confirm/nugget/none', methods=['POST'])
def confirm_no_match_in_document():
	"""
    Endpoint to confirm no match for a nugget in a document.

	Header:
    {
        "Authorization": "your_authorization_token"
    }
    Example Form Payload:
    {
        "organisationId": "your_organisation_id",
        "baseName": "your_document_base_name",
        "documentName": "your_document_name",
        "documentContent": "your_document_content",
        "nuggetText": "nugget_as_text",
        "startIndex": "start_index_of_nugget",
        "endIndex": "end_index_of_nugget",
        "interactiveCallTaskId": "interactive_call_task_id"
    }
    """
	form = request.get_json()

	authorization = request.headers.get("Authorization")
	organisation_id: Optional[int] = form.get("organisationId")
	base_name = form.get("baseName")

	document_name = form.get("documentName")
	document_content = form.get("documentContent")
	nugget_text = form.get("nuggetText")
	start_index: Optional[int]  = int(form.get("startIndex")) if form.get("startIndex") is not None else None
	end_index: Optional[int]  = int(form.get("endIndex")) if form.get("endIndex") is not None else None

	i_task_id = form.get("interactiveCallTaskId")

	if (organisation_id is None
     	or base_name is None
      	or document_name is None
       	or document_content is None
        or authorization is None
        or nugget_text is None
        or start_index is None
        or end_index is None
        or i_task_id is None):

		return make_response({"error": "missing parameters"}, 400)

	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseNoMatchForDocument().apply_async(args=(
     													user_id,
                                                      	base_name,
                                                       	organisation_id,
                                                        document_name,
                                                        document_content,
                                                        nugget_text,
                                                        start_index,
                                                        end_index,
                                                        i_task_id
                                                    ))

	return make_response({'task_id': task.id}, 202)


@core_routes.route('/document_base/feedback/stop', methods=['POST'])
def stop_feedback():
	"""
	Endpoint to stop feedback for a document.

	header: {
		"Authorization": "your_authorization_token"
	}
	no payload is required
	"""
	authorization = request.headers.get("Authorization")

	if (authorization is None):
		return make_response({"error": "missing header fields"}, 400)

	_token = tokenDecode(authorization)

	if _token is False:
		return make_response({"error": "invalid token"}, 401)

	user_id = _token.id

	task = DocumentBaseStopMatching().apply_async(args=(user_id,))

	return make_response({'task_id': task.id}, 202)

