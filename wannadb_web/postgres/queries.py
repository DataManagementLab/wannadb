from typing import Union

import bcrypt
from psycopg2 import sql

from wannadb_web.postgres.util import execute_query


def getUserID(user: str):
	select_query = sql.SQL("SELECT id FROM users WHERE username = %s;")
	return execute_query(select_query, (user,))


def getOrganisationID(organisation_name: str):
	select_query = sql.SQL("SELECT id FROM organisations WHERE name = %s;")
	return execute_query(select_query, (organisation_name,))

def getOrganisationName(organisation_id: int):
	select_query = sql.SQL("SELECT name FROM organisations WHERE id = %s;")
	response = execute_query(select_query, (organisation_id,))
	if response is None:
		return -1
	return str(response[0])

def getMembersOfOrganisation(organisation_id: int):
	select_query = sql.SQL("SELECT username FROM users WHERE id IN (SELECT userid FROM membership WHERE organisationid = %s);")
	return execute_query(select_query, (organisation_id,))

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

def getOrganisationFromUserId(user_id: int):
	try:
		select_query = sql.SQL("""	SELECT organisationid, o.name
									FROM membership
									JOIN organisations o ON membership.organisationid = o.id
									WHERE userid = %s;""")
		response = execute_query(select_query, (user_id,))
		if isinstance(response, list):
			organisations: list[dict[str, Union[str, int]]] = []
			for org in response:
				organisations.append({"id": int(org[0]), "name": str(org[1])})
			return organisations, None
		if response is None:
			return [-1], None
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
	select_query = sql.SQL("""SELECT content,content_byte 
								from documents 
								where id = (%s)""")

	result = execute_query(select_query, (documentId,))
	try:
		if result[0]:
			if result[0][0]:
				content = result[0][0]
				return str(content)
			else:
				content = result[0][1]
				return bytes(content)
		else:
			return None

	except Exception as e:
		print("_getDocument failed because: \n", e)


def getDocument(document_id: int, user_id: int):
	select_query = sql.SQL("""SELECT name,content,content_byte 
							 FROM documents 
							 JOIN membership m ON documents.organisationid = m.organisationid
							 WHERE id = (%s) AND m.userid = (%s)
							 """)

	result = execute_query(select_query, (document_id, user_id,))
	try:
		if len(result) > 0:
			for document in result:
				name = document[0]
				if document[1]:
					content = document[1]
					return str(name), str(content)
				elif document[2]:
					content = document[2]
					return str(name), bytes(content)
		else:
			return None
	except Exception as e:
		print("getDocument failed because:\n", e)
  
def getDocumentsForOrganization(organisation_id: int):
	try:
		select_query = sql.SQL("""SELECT id, name,content,content_byte 
							 FROM documents 
							 WHERE organisationid = (%s)
							 """)
		result = execute_query(select_query, (organisation_id,))
	
		if result == None or len(result) == 0:
			return []

		doc_array = []
  
		for document in result:
			id = document[0]
			name = document[1]
			content = '';
			if document[2]:
				content = document[2]
			elif document[3]:
				content = document[3]
			doc_array.append({
				"id": id,
				"name": name,
				"content": content
			})
		return doc_array

	except Exception as e:
		print("getDocumentsForOrganization failed because:\n", e)
		return []


def getDocuments(document_ids: list[int], user_id: int):
	select_query = sql.SQL(f"""SELECT name,content,content_byte 
							 FROM documents 
							 JOIN membership m ON documents.organisationid = m.organisationid
							 WHERE m.userid = (%s) and documents.id in 
							 ({",".join(str(_id) for _id in document_ids)})
							 """)
	result = execute_query(select_query, (user_id,))
	try:
		if len(result) > 0:
			documents = []
			for document in result:
				name = document[0]
				if document[1]:
					content = document[1]
					documents.append((str(name), str(content)))
				elif document[2]:
					content = document[2]
					documents.append((str(name), bytes(content)))
			return documents
		else:
			return None
	except Exception as e:
		print("getDocuments failed because:\n", e)


def getDocument_ids(organisation_id: int, user_id: int):
	select_query = sql.SQL("""SELECT name,content,content_byte 
									from documents 
									join membership m on documents.organisationid = m.organisationid
									where m.organisationid = (%s) and m.userid = (%s)
									""")

	result = execute_query(select_query, (organisation_id, user_id,))
	print(result)
	documents = []
	try:
		if len(result) > 0:
			for document in result:
				if document[1]:
					name = document[0]
					content = document[1]
					documents.append((str(name), str(content)))
				elif document[2]:
					name = document[0]
					content = document[2]
					documents.append((str(name), bytes(content)))
		return documents
	except Exception as e:
		print("getDocument_ids failed because: \n", e)
