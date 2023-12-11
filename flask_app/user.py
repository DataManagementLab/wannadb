# main_routes.py
from flask import Blueprint, request, jsonify

from config import Token, encode
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
		token = encode(user.dict())

		return jsonify({'message': 'User registered successfully',
                  		'status': True,
						'token': token})

	return jsonify({'message': 'User register failed', 'status': False})


@user_management.route('/login', methods=['POST'])
def login():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')

	_correct = checkPassword(username, password)

	if _correct:
		user = Token(username, _correct)
		token = encode(user.dict())

		return jsonify({'message': 'Log in successfully',
                  		'status': True,
						'token': token})
	else:
		return jsonify({'message': 'Wrong Password', 'status': False})
