# main_routes.py
from flask import Blueprint, request, make_response

from config import Token, tokenEncode
from postgres.queries import checkPassword
from postgres.transactions import addUser

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

	_correct = checkPassword(username, password)

	if _correct:
		user = Token(username, _correct)
		token = tokenEncode(user.json())

		return make_response({'message': 'Log in successfully',
							  'token': token}, 200)
	else:
		return make_response({'message': 'Wrong Password'}, 401)


@user_management.route('/creatOrganisation', methods=['POST'])
def creat_organisation():
	form = request.form
	authorization = form.get("authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisation_name = form.get("organisationName")

	organisation_id = addOrganisation(organisation_name, authorization)

	if organisation_id is None:
		return make_response({'organisation_id': ""}, 422)
	return make_response({'organisation_id': organisation_id}, 200)
