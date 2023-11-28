# main_routes.py
from flask import Blueprint, request, jsonify

from config import User, encode
from postgres.transactions import addUser

user_management = Blueprint('user_management', __name__)


@user_management.route('/registerrrrrrrrrrrrrrrrrr', methods=['POST'])
def register():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')

	_id = addUser(username, password)

	if id:
		user = User(username, _id)
		token = encode(user)
		return jsonify({'message': 'User registered successfully',
						'token': token})

	return jsonify({'message': 'User registered successfully'})
