# main_routes.py
from flask import Blueprint, request, make_response

from config import Token, tokenEncode, tokenDecode
from postgres.queries import (checkPassword, getMembersOfOrganisation,
							  getOrganisationIDsFromUserId, getOrganisationName, getOrganisationFromUserId)
from postgres.transactions import addUser, addOrganisation, addUserToOrganisation, addUserToOrganisation2, deleteUser, leaveOrganisation

user_management = Blueprint('user_management', __name__)


@user_management.route('/register', methods=['POST'])
def register():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')

	_id = addUser(username, password)

	if _id > 0:
		user = Token(username, _id)
		token = tokenEncode(user.json())

		return make_response({'message': 'User registered successfully',
							  'token': token}, 201)
	if _id < 0:
		return make_response({'message': 'Conflicting username'}, 409)
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
	if not _correct:
		return make_response({'message': 'Wrong Password'}, 401)
	return make_response({'message': 'User login failed'}, 422)


@user_management.route('/deleteUser/', methods=['POST'])
def delete_user():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')
	authorization = request.headers.get("Authorization")

	if authorization is None:
		return make_response({'message': 'no authorization '}, 401)

	check, _id = checkPassword(username, password)
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'message': 'no authorization '}, 400)

	if check is False or token.id != _id:
		return make_response({'message': 'User not authorised '}, 401)

	response = deleteUser(username, password)

	if response:
		return make_response({'message': 'User deleted'}, 204)
	return make_response({'message': 'User deleted failed'}, 409)


@user_management.route('/createOrganisation', methods=['POST'])
def create_organisation():
	data = request.get_json()
	authorization = request.headers.get("Authorization")

	organisation_name = data.get("organisationName")

	organisation_id, error = addOrganisation(organisation_name, authorization)
	if error is None:
		return make_response({'organisation_id': organisation_id}, 200)
	return make_response({"error": error}, 409)

@user_management.route('/leaveOrganisation', methods=['POST'])
def leave_organisation():
	data = request.get_json()
	authorization = request.headers.get("Authorization")

	organisationId = data.get("organisationId")

	success, error = leaveOrganisation(organisationId, authorization)
	if success:
		return make_response({'status': True}, 200)
	return make_response({"status": False, "msg": str(error)}, 500)


@user_management.route('/getOrganisations', methods=['GET'])
def get_organisations():
	authorization = request.headers.get("authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisation_ids, error = getOrganisationIDsFromUserId(token.id)
	if error is None:
		return make_response({'organisation_ids': organisation_ids}, 200)
	if organisation_ids[0] < 0:
		return make_response({'user is in no organisation'}, 404)
	return make_response({"error": error}, 409)


@user_management.route('/getOrganisationName/<_id>', methods=['GET'])
def get_organisation_name(_id):
	authorization = request.headers.get("authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisation_name = getOrganisationName(_id)

	if organisation_name == -1:
		return make_response({'organisation not found': organisation_name}, 404)
	if isinstance(organisation_name, str):
		return make_response({"organisation_name": organisation_name}, 200)
	return make_response({"error": "error"}, 409)


@user_management.route('/getOrganisationNames', methods=['GET'])
def get_organisation_names():
	authorization = request.headers.get("authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisations, error = getOrganisationFromUserId(token.id)
	if error is None:
		return make_response({'organisations': organisations}, 200)
	if organisations < 0:
		return make_response({'user is in no organisation'}, 404)
	return make_response({"error": error}, 409)


@user_management.route('/addUserToOrganisation', methods=['POST'])
def add_user_to_organisation():
	authorization = request.headers.get("authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

	data = request.get_json()
	organisation_name = data.get("organisationId")
	new_user = data.get("newUser")

	organisation_id, error = addUserToOrganisation2(organisation_name, new_user)

	if error:
		return make_response({"error": error}, 409)
	return make_response({'organisation_id': organisation_id}, 200)

@user_management.route('/getOrganisationMembers/<_id>', methods=['GET'])
def get_organisation_members(_id):
	authorization = request.headers.get("authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

	members_raw = getMembersOfOrganisation(_id)
	if members_raw is None:
		return make_response({'error':'organisation '+_id+' not found'}, 404)

	members = []
	for member in members_raw:
		members.append(member[0])
 
	return make_response({"members": members}, 200)