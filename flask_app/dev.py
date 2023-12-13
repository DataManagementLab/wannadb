from flask import Blueprint, make_response

from postgres.queries import _getDocument
from postgres.transactions import createUserTable, createDocumentsTable, createOrganisationTable, createMembershipTable

dev_routes = Blueprint('dev_routes', __name__, url_prefix='/dev')


@dev_routes.route('/createTables', methods=['POST'])
def createTables():
	try:
		createUserTable()
		createDocumentsTable()
		createOrganisationTable()
		createMembershipTable()
		return 'create Tables successfully'
	except Exception as e:
		print("create Tables failed because: \n", e)


@dev_routes.route('/getDocument/<_id>', methods=['GET'])
def get_document(_id):
	try:
		response = _getDocument(_id)
		return make_response(response, 200)
	except Exception as e:
		return make_response({"message": f"getFile with {_id} ", "details": str(e)}, 400)
