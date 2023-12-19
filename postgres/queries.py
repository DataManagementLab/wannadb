from typing import Union
import bcrypt
from psycopg2 import sql
from postgres.util import execute_query


def getUserID(user: str):
	select_query = sql.SQL("SELECT id FROM users WHERE username = %s;")
	return execute_query(select_query, (user,))


def getOrganisationID(organisation_name: str):
	select_query = sql.SQL("SELECT id FROM organisations WHERE name = %s;")
	response = execute_query(select_query, (organisation_name,))
	if response is None:
		return -1
	return int(response[0])


def getOrganisationName(organisation_id: int):
	select_query = sql.SQL("SELECT name FROM organisations WHERE id = %s;")
	response = execute_query(select_query, (organisation_id,))
	if response is None:
		return -1
	return str(response[0])


def getMemberIDsFromOrganisationID(organisationID: int):
	select_query = sql.SQL("SELECT userid FROM membership WHERE organisationid = %s;")
	return execute_query(select_query, (organisationID,))


def getOrganisationIDsFromUserId(userID: int):
	try:
		select_query = sql.SQL("SELECT organisationid FROM membership WHERE userid = %s;")
		response = execute_query(select_query, (userID,))
		if isinstance(response, list):
			return response[0], None
		elif response is None:
			return [-1], None
		else:
			return None, "Unexpected response format"

	except Exception as e:
		return None, e


def checkPassword(user: str, password: str) -> Union[tuple[bool, int], tuple[bool, str]]:
	select_query = sql.SQL("SELECT password,id as pw FROM users WHERE username = %s ")
	_password, _id = execute_query(select_query, (user,))[0]

	try:
		if _password:
			stored_password = bytes(_password)
			check = bcrypt.checkpw(password.encode('utf-8'), stored_password)
			if check:
				return bcrypt.checkpw(password.encode('utf-8'), stored_password), int(_id)

		return False, ""

	except Exception as e:
		print("checkPassword failed because: \n", e)
		return False, str(e)


def checkOrganisationAuthorisation(organisationName: str, userName: str) -> int:
	select_query = sql.SQL("SELECT membership from membership "
						   "where userid = (SELECT id from users where username = (%s)) "
						   "and "
						   "organisationid = (Select id from organisations where name = (%s))")

	result = execute_query(select_query, (organisationName, userName))
	try:
		if result[0]:
			authorisation = result[0]
			return int(authorisation)  # sketchy conversion but works

	except Exception as e:
		print("checkOrganisationAuthorisation failed because: \n", e)
		return 99


def _getDocument(documentId: int):
	select_query = sql.SQL("SELECT content "
						   "from documents "
						   "where id = (%s)")

	result = execute_query(select_query, (documentId,))
	try:
		if result[0]:
			content = result[0]
			return str(content)

	except Exception as e:
		print("checkOrganisationAuthorisation failed because: \n", e)
