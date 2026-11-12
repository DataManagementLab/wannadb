import logging

from flask import Blueprint, request, make_response, abort, g
from psycopg2 import Error as PostgresError
from redis.exceptions import RedisError
from werkzeug.exceptions import RequestEntityTooLarge

from wannadb_web.auth_limits import (
	LOGINS_PER_PEER, LOGINS_PER_USERNAME, REGISTRATIONS_PER_PEER, auth_retry_after,
)

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
	try:
		role = get_organisation_authorisation(g.auth_token.id, organisation_id, raise_on_error=True)
	except RuntimeError:
		abort(make_response({"error": "Organization access checks are temporarily unavailable."}, 503))
	if role is None or (admin and role not in (0, 1)):
		abort(make_response({'error': 'organization access denied'}, 403))
	return organisation_id


def _auth_error(code, message, status):
	return make_response({"code": code, "error": message}, status, {"Cache-Control": "no-store"})


def _check_auth_limit(scope, identity, maximum):
	try:
		retry_after = auth_retry_after(scope, identity, maximum)
	except RedisError:
		abort(_auth_error("AUTH_UNAVAILABLE", "Sign-in and registration are temporarily unavailable.", 503))
	if retry_after:
		response = _auth_error("AUTH_RATE_LIMITED", "Too many attempts. Wait a minute and try again.", 429)
		response.headers["Retry-After"] = str(retry_after)
		abort(response)


def _auth_credentials():
	# Auth requests contain only short JSON credentials, separate from upload limits.
	limit = 16 * 1024
	request.max_content_length = min(request.max_content_length or limit, limit)
	try:
		data = request.get_json(silent=True)
	except RequestEntityTooLarge:
		abort(_auth_error("INVALID_CREDENTIALS", "The credentials request is too large.", 413))
	if not isinstance(data, dict):
		abort(_auth_error("INVALID_CREDENTIALS", "Enter a username and password.", 400))
	username, password = data.get("username"), data.get("password")
	if not isinstance(username, str) or not username.strip() or "\0" in username or not isinstance(password, str):
		abort(_auth_error("INVALID_CREDENTIALS", "Enter a valid username and password.", 400))
	try:
		username.encode("utf-8")
		password_bytes = password.encode("utf-8")
	except UnicodeEncodeError:
		abort(_auth_error("INVALID_CREDENTIALS", "The credentials contain invalid Unicode.", 400))
	return username, password, password_bytes


@user_management.route('/register', methods=['POST'])
def register():
	# Use the connection peer. The frontend proxy may share a bucket across users.
	_check_auth_limit("register-peer", request.remote_addr or "unknown", REGISTRATIONS_PER_PEER)
	username, password, password_bytes = _auth_credentials()
	if len(username) > 128:
		return _auth_error("INVALID_CREDENTIALS", "Use a username of at most 128 characters.", 400)
	if not 1 <= len(password_bytes) <= 72 or b"\0" in password_bytes:
		return _auth_error("INVALID_PASSWORD", "Use a password between 1 and 72 UTF-8 bytes with no null characters.", 400)
	try:
		user_id = add_user(username, password)
	except (PostgresError, RuntimeError):
		return _auth_error("AUTH_UNAVAILABLE", "Account creation is temporarily unavailable. Try again.", 503)
	if user_id is None:
		return _auth_error("USERNAME_TAKEN", "That username is already taken.", 409)
	return make_response({"message": "User registered successfully"}, 201, {"Cache-Control": "no-store"})


@user_management.route('/login', methods=['POST'])
def login():
	_check_auth_limit("login-peer", request.remote_addr or "unknown", LOGINS_PER_PEER)
	username, password, _ = _auth_credentials()
	_check_auth_limit("login-username", username, LOGINS_PER_USERNAME)
	# Continue verifying existing hashes with the bcrypt behavior they were created with.
	user_id = check_password(username, password)
	if type(user_id) is not int:
		return _auth_error("INVALID_CREDENTIALS", "Invalid username or password.", 401)
	token = tokenEncode(Token(username, user_id).json())
	return make_response({"message": "Log in successfully", "token": token}, 200,
		{"Cache-Control": "no-store"})


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
	try:
		organisation_name = get_organisation_name(organisation_id)
	except RuntimeError:
		return make_response({'error': 'Organization metadata is temporarily unavailable.'}, 503)

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
		return make_response({'error': 'Organization members could not be loaded.'}, 503)
	actor_role = next((role for _, user_id, role in members if user_id == g.auth_token.id), None)
	if actor_role not in (0, 1, 10):
		return make_response({'error': 'Organization access denied.'}, 403)
	has_owner = any(role == 0 for _, _, role in members)
	return make_response({
		"members": [name for name, _, _ in members],
		"canManageOwnership": can_manage_organisation_ownership(actor_role, has_owner),
		"isOwner": actor_role == 0,
		"canInvite": actor_role in (0, 1),
	}, 200)


@user_management.route('/get/user/suggestion', methods=['GET'])
@user_management.route('/get/user/suggestion/<_prefix>', methods=['GET'])
def get_user_suggestion(_prefix=None):
	organisation_id = _require_organisation(request.args.get("organisationId"), admin=True)
	prefix = request.args.get("prefix", _prefix)
	if not isinstance(prefix, str) or not 1 <= len(prefix) <= 128 or "\0" in prefix or not prefix.strip():
		return make_response({"error": "Enter a valid username prefix."}, 400)
	members = get_username_suggestion(prefix, organisation_id, g.auth_token.id)
	if members is False:
		return make_response({"error": "User search is temporarily unavailable."}, 503)
	return make_response({"usernames": [member[0] for member in members or []]}, 200, {"Cache-Control": "no-store"})
