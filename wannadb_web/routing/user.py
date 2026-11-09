import logging

from flask import Blueprint, request, make_response, abort, g
from psycopg2 import Error as PostgresError

from wannadb_web.util import Token, tokenEncode, tokenDecode
from wannadb_web.postgres.queries import check_password, get_members_of_organisation, get_organisation_from_user_id, \
	get_organisation_ids_from_user_id, get_organisation_name, get_username_suggestion, get_organisation_authorisation
from wannadb_web.postgres.transactions import (
	OrganisationLifecycleConflict, add_user, add_organisation, add_user_to_organisation_new,
	can_manage_organisation_ownership, delete_organisation_transaction, delete_user_transaction,
	leave_organisation_transaction, remove_user_from_organisation_new, transfer_organisation_ownership,
)

user_management = Blueprint('user_management', __name__)
logger = logging.getLogger(__name__)


@user_management.errorhandler(OrganisationLifecycleConflict)
def organisation_lifecycle_conflict(error):
	return make_response({'error': str(error)}, 409)


@user_management.errorhandler(PermissionError)
def organisation_lifecycle_permission(error):
	return make_response({'error': str(error)}, 403)


def _run_lifecycle_change(operation, *args):
	try:
		operation(*args)
	except PostgresError as error:
		logger.error("Organization transaction failed (%s, SQLSTATE=%s).",
			type(error).__name__, error.pgcode or "unavailable")
		abort(make_response({'error': 'The database could not complete the request. Try again.'}, 503))


@user_management.before_request
def authenticate_users():
	if request.method == 'OPTIONS' or request.endpoint in ('user_management.login', 'user_management.register'):
		return None
	g.auth_token = tokenDecode(request.headers.get('Authorization'))
	if g.auth_token is None:
		return make_response({'error': 'no authorization'}, 401)


def _require_organisation(value, admin=False):
	if isinstance(value, bool) or not isinstance(value, (int, str)):
		abort(make_response({'error': 'invalid organization ID'}, 400))
	try:
		organisation_id = int(value)
	except (ValueError, TypeError):
		abort(make_response({'error': 'invalid organization ID'}, 400))
	if organisation_id <= 0 or organisation_id > 9223372036854775807:
		abort(make_response({'error': 'invalid organization ID'}, 400))
	role = get_organisation_authorisation(g.auth_token.id, organisation_id)
	if role is None or (admin and role not in (0, 1)):
		abort(make_response({'error': 'organization access denied'}, 403))
	return organisation_id


@user_management.route('/register', methods=['POST'])
def register():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')

	_id = add_user(username, password)

	if _id > 0:
		user = Token(username, _id)
		token = tokenEncode(user.json())

		return make_response({'message': 'User registered successfully',
							  'token': token}, 201)
	elif _id < 0:
		return make_response({'message': 'Conflicting username'}, 409)
	else:
		return make_response({'message': 'User register failed'}, 422)


@user_management.route('/login', methods=['POST'])
def login():
	data = request.get_json()
	username = data.get('username')
	password = data.get('password')

	pwcheck = check_password(username, password)
	if isinstance(pwcheck, Exception):
		raise pwcheck
	if isinstance(pwcheck, bool):
		return make_response({'message': 'Wrong Password'}, 401)
	if isinstance(pwcheck, int):
		_id = pwcheck
		user = Token(username, _id)
		token = tokenEncode(user.json())

		return make_response({'message': 'Log in successfully',
							  'token': token}, 200)


@user_management.route('/deleteUser', methods=['DELETE'])
def delete_user():
	data = request.get_json(silent=True)
	if not isinstance(data, dict):
		return make_response({'error': 'An account and password are required.'}, 400)
	user_id = check_password(data.get('username'), data.get('password'))
	if type(user_id) is not int or user_id != g.auth_token.id:
		return make_response({'error': 'Invalid account or password.'}, 401)

	_run_lifecycle_change(delete_user_transaction, user_id)
	return make_response('', 204)


@user_management.route('/createOrganisation', methods=['POST'])
def create_organisation():
	data = request.get_json()
	authorization = request.headers.get("Authorization")

	organisation_name = data.get("organisationName")

	organisation_id, error = add_organisation(organisation_name, authorization)
	if error is None:
		return make_response({'organisation_id': organisation_id}, 200)
	if error == "name already exists.":
		return make_response({"error": error}, 409)
	if error == "Authentication failed.":
		return make_response({"error": error}, 401)
	return make_response({"error": error}, 422)


@user_management.route('/leaveOrganisation', methods=['DELETE'])
def leave_organisation():
	data = request.get_json(silent=True)
	if not isinstance(data, dict):
		return make_response({'error': 'An organization is required.'}, 400)
	organisation_id = _require_organisation(data.get("organisationId"))
	_run_lifecycle_change(leave_organisation_transaction, organisation_id, g.auth_token.id)
	return make_response({'status': True}, 200)


@user_management.route('/transferOrganisationOwnership', methods=['POST'])
def transfer_ownership():
	data = request.get_json(silent=True)
	if not isinstance(data, dict):
		return make_response({'error': 'An organization and replacement owner are required.'}, 400)
	organisation_id = _require_organisation(data.get("organisationId"), admin=True)
	replacement = data.get("newOwner")
	if not isinstance(replacement, str) or not replacement.strip() or "\0" in replacement:
		return make_response({'error': 'A replacement owner is required.'}, 400)
	_run_lifecycle_change(transfer_organisation_ownership, organisation_id, g.auth_token.id, replacement)
	return make_response({'status': True}, 200)


@user_management.route('/deleteOrganisation', methods=['DELETE'])
def delete_organisation():
	data = request.get_json(silent=True)
	if not isinstance(data, dict) or data.get("confirmDelete") is not True:
		return make_response({'error': 'Explicit confirmation is required to delete an organization.'}, 400)
	organisation_id = _require_organisation(data.get("organisationId"), admin=True)
	_run_lifecycle_change(delete_organisation_transaction, organisation_id, g.auth_token.id)
	return make_response({'status': True}, 200)


@user_management.route('/getOrganisations', methods=['GET'])
def get_organisations():
	authorization = request.headers.get("Authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisation_ids, error = get_organisation_ids_from_user_id(token.id)
	if error is None:
		return make_response({'organisation_ids': organisation_ids}, 200)
	if organisation_ids[0] < 0:
		return make_response({'user is in no organisation'}, 404)
	return make_response({"error": error}, 409)


@user_management.route('/getOrganisationName/<_id>', methods=['GET'])
def get_organisation_name_route(_id):
	authorization = request.headers.get("Authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisation_id = _require_organisation(_id)
	organisation_name = get_organisation_name(organisation_id)

	if organisation_name == -1:
		return make_response({'organisation not found': organisation_name}, 404)
	if isinstance(organisation_name, str):
		return make_response({"organisation_name": organisation_name}, 200)
	return make_response({"error": "error"}, 409)


@user_management.route('/getOrganisationNames', methods=['GET'])
def get_organisation_names():
	authorization = request.headers.get("Authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({}, 401)

	organisations, error = get_organisation_from_user_id(token.id)
	if error is None:
		return make_response({'organisations': organisations}, 200)
	if organisations <= 0:
		return make_response({'user is in no organisation'}, 404)
	return make_response({"error": error}, 409)


@user_management.route('/addUserToOrganisation', methods=['POST'])
def add_user_to_organisation():
	authorization = request.headers.get("Authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

	data = request.get_json()
	organisation_id = _require_organisation(data.get("organisationId"), admin=True)
	new_user = data.get("newUser")
	if not isinstance(new_user, str) or not new_user:
		return make_response({'error': 'missing new user'}, 400)

	organisation_id, error = add_user_to_organisation_new(organisation_id, new_user, token.id)

	if error:
		return make_response({"error": error}, 409)
	return make_response({'organisation_id': organisation_id}, 200)


@user_management.route('/removeUserFromOrganisation', methods=['DELETE'])
def remove_user_from_organisation():
	data = request.get_json(silent=True)
	if not isinstance(data, dict):
		return make_response({'error': 'An organization and member are required.'}, 400)
	organisation_id = _require_organisation(data.get("organisationId"), admin=True)
	user_to_remove = data.get("userToRemove")
	if not isinstance(user_to_remove, str) or not user_to_remove.strip() or "\0" in user_to_remove:
		return make_response({'error': 'A member is required.'}, 400)
	_run_lifecycle_change(remove_user_from_organisation_new, organisation_id, user_to_remove, g.auth_token.id)
	return make_response({'status': True}, 200)


@user_management.route('/getOrganisationMembers/<_id>', methods=['GET'])
def get_organisation_members(_id):
	organisation_id = _require_organisation(_id)
	members = get_members_of_organisation(organisation_id, include_roles=True)
	if not isinstance(members, list):
		return make_response({'error': 'Organization members could not be loaded.'}, 404)
	actor_role = next((role for _, user_id, role in members if user_id == g.auth_token.id), None)
	if actor_role not in (0, 1, 10):
		return make_response({'error': 'Organization access denied.'}, 403)
	has_owner = any(role == 0 for _, _, role in members)
	return make_response({
		"members": [name for name, _, _ in members],
		"canManageOwnership": can_manage_organisation_ownership(actor_role, has_owner),
	}, 200)


@user_management.route('/get/user/suggestion/<_prefix>', methods=['GET'])
def get_user_suggestion(_prefix):
	authorization = request.headers.get("Authorization")
	token = tokenDecode(authorization)
	if token is None:
		return make_response({'error': 'no authorization'}, 401)

	members_raw = get_username_suggestion(_prefix)
	result = []
	for member in members_raw:
		result.append(member[0])
	return make_response({"usernames": result}, 200)
