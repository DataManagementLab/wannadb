# main_routes.py
from flask import Blueprint, request, make_response

from config import Token, tokenEncode, tokenDecode
from postgres.queries import checkPassword
from postgres.transactions import addUser, addOrganisation, addUserToOrganisation, deleteUser

user_management = Blueprint('user_management', __name__)


@user_management.route('/register', methods=['POST'])
def register():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')

	_id = addUser(username, password)

	if _id:
		user = Token(username, _id)
		token = tokenEncode(user.json())

		return make_response({'message': 'User registered successfully',
							  'token': token}, 201)

	return make_response({'message': 'User register failed'}, 422)


@user_management.route('/login', methods=['POST'])
def login():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')

	_correct, _id = checkPassword(username, password)

	if _correct:
		user = Token(username, _id)
		token = tokenEncode(user.json())

		return make_response({'message': 'Log in successfully',
							  'token': token}, 200)
	else:
		return make_response({'message': 'Wrong Password'}, 401)


@user_management.route('/deleteUser/', methods=['POST'])
def delete_user():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')
	authorization = data.get("authorization")

	check, _id = checkPassword(username, password)
	token = tokenDecode(authorization)
	if not (token and check and token.id == _id):
		return make_response({'message': 'User not authorised '}, 401)

	response = deleteUser(username, password)

	if response:
		return make_response({'message': 'User deleted'}, 204)
	return make_response({'message': 'User deleted failed'}, 409)


@user_management.route('/createOrganisation', methods=['POST'])
def create_organisation():
	data = request.get_json()
	authorization = data.get("authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisation_name = data.get("organisationName")

	organisation_id, error = addOrganisation(organisation_name, authorization)
	if error:
		return make_response({"error": error}, 409)
	return make_response({'organisation_id': organisation_id}, 200)


@user_management.route('/addUserToOrganisation', methods=['POST'])
def add_user_to_organisation():
	data = request.get_json()
	authorization = data.get("authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisation_name = data.get("organisationName")
	new_user = data.get("newUser")

	organisation_id, error = addUserToOrganisation(organisation_name, authorization, new_user)

	if error:
		return make_response({"error": error}, 409)
	return make_response({'organisation_id': organisation_id}, 200)
