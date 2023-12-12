from flask import Blueprint

from postgres.transactions import createUserTable

dev_routes = Blueprint('dev_routes', __name__, url_prefix='/dev')


@dev_routes.route('/createTables', methods=['POST'])
def createTables():
	try:
		createUserTable()
		return 'createUserTable successfully'
	except Exception as e:
		print("createTables failed because: \n", e)

	return 'Table created successfully'
