import logging
from flask import Blueprint, make_response

from wannadb_web.postgres.queries import _get_document
from wannadb_web.postgres.transactions import create_document_base_table, create_document_feedback_table, create_user_table, create_documents_table, create_organisation_table, \
	create_membership_table, drop_tables, drop_schema, create_schema

dev_routes = Blueprint('dev_routes', __name__, url_prefix='/dev')

logger = logging.getLogger(__name__)

@dev_routes.route('/createTables/<schema>', methods=['POST'])
def create_tables(schema):
	try:
		create_schema(schema)
		create_user_table(schema)
		create_organisation_table(schema)
		create_membership_table(schema)
		create_document_base_table(schema)
		create_documents_table(schema)
		create_document_feedback_table(schema)
		return make_response({"message": f"create Tables in {schema} successfully"}, 200)
	except Exception as e:
		logger.error(f"create Tables in {schema} failed because: \n", e)
		return make_response({"message": f"create Tables in {schema} failed", "details": str(e)}, 400)


@dev_routes.route('/dropTables/<schema>', methods=['POST']) # potential vulnerability
def drop_tables(schema):
	try:
		drop_tables(schema)
		drop_schema(schema)
		return f'drop Tables in {schema} successfully'
	except Exception as e:
		logger.error(f"drop Tables in {schema} failed because: \n", e)


@dev_routes.route('/getDocument/<_id>', methods=['GET'])
def get_document(_id):
	try:
		response = _get_document(_id)
		return make_response(response, 200)
	except Exception as e:
		return make_response({"message": f"getFile with {_id} ", "details": str(e)}, 400)
