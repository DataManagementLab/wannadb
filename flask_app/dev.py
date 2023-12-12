from flask import Blueprint

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
