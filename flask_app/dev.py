from flask import Blueprint, make_response

from postgres.queries import _getDocument
from postgres.transactions import createUserTable, createDocumentsTable, createOrganisationTable, createMembershipTable, \
	dropTables

dev_routes = Blueprint('dev_routes', __name__, url_prefix='/dev')


@dev_routes.route('/createTables/<schema>', methods=['POST'])
def create_tables(schema):
	try:
		createUserTable(schema)
		createOrganisationTable(schema)
		createMembershipTable(schema)
		createDocumentsTable(schema)
		return f'create Tables in {schema} successfully'
	except Exception as e:
		print("create Tables in {schema} failed because: \n", e)

@dev_routes.route('/dropTables/<schema>', methods=['POST'])
def drop_tables(schema):
	try:
		dropTables(schema)
		return f'drop Tables in {schema} successfully'
	except Exception as e:
		print("drop Tables in {schema} failed because: \n", e)


@dev_routes.route('/getDocument/<_id>', methods=['GET'])
def get_document(_id):
	try:
		response = _getDocument(_id)
		return make_response(response, 200)
	except Exception as e:
		return make_response({"message": f"getFile with {_id} ", "details": str(e)}, 400)
