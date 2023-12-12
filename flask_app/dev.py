from flask import Blueprint, request
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from postgres.transactions import createUserTable
from config import decode

dev_routes = Blueprint('dev_routes', __name__, url_prefix='/dev')


@dev_routes.route('/createTables', methods=['POST'])
def createTables():
	try:
		createUserTable()
  
	except Exception as e:
		return str(e)

	#finally:
		# TODO whats that?
		# Remove the temporary files
		#for file in files:
		#	filename = secure_filename(file.filename)
		#	if os.path.exists(filename):
		#		os.remove(filename)

	return 'Table created successfully'
