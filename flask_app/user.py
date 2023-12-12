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



