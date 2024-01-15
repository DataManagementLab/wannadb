from typing import Union

import bcrypt
from psycopg2 import sql

from wannadb_web.postgres.util import execute_query, execute_transaction


def getUserID(user: str):
	select_query = sql.SQL("SELECT id FROM users WHERE username = %s;")
	result = execute_query(select_query, (user,))
	if isinstance(result[0], int):
		return int(result[0])
	return None


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
	select_query = sql.SQL(
		"SELECT username FROM users WHERE id IN (SELECT userid FROM membership WHERE organisationid = %s);")
	return execute_query(select_query, (organisation_id,))


def getMemberIDsFromOrganisationID(organisationID: int):
	select_query = sql.SQL("SELECT userid FROM membership WHERE organisationid = %s;")
	return execute_query(select_query, (organisationID,))


def getUserNameSuggestion(prefix: str):
	select_query = sql.SQL("SELECT username FROM users WHERE username LIKE %s;")
	return execute_query(select_query, (prefix + "%",))


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
			return [], None
		return None, "Unexpected response format"
	except Exception as e:
		return None, e


def checkPassword(user: str, password: str):
	"""Checks if the password is correct for the given user

	Returns:
		user_id: int (if password is correct)
		False: bool (if password is incorrect)
		Exception: Exception (if something went wrong)
	Raises:
		None
	"""
	select_query = sql.SQL("SELECT password,id as pw FROM users WHERE username = %s ")

	result = execute_query(select_query, (user,))
	_password, _id = result[0]

	if _password:
		stored_password = bytes(_password)
		check = bcrypt.checkpw(password.encode('utf-8'), stored_password)
		if check:
			return int(_id)

	return False


def checkOrganisationAuthorisation(organisationName: str, userName: str):
	select_query = sql.SQL("SELECT authorisation from membership "
						   "where userid = (SELECT id from users where username = (%s)) "
						   "and "
						   "organisationid = (Select id from organisations where name = (%s))")

	result = execute_query(select_query, (organisationName, userName))
	if isinstance(result[0], int):
		return int(result[0])
	if result[0] is None:
		return None




def _getDocument(documentId: int):
	select_query = sql.SQL("""SELECT content,content_byte 
								from documents 
								where id = (%s)""")

	result = execute_query(select_query, (documentId,))

	if result[0]:
		if result[0][0]:
			content = result[0][0]
			return str(content)
		else:
			content = result[0][1]
			return bytes(content)
	else:
		return None


def getDocument_by_name(document_name: str, organisation_id: int, user_id: int):
	"""
		Returns:
			name: str
			content: str or bytes

		Raises:
			Exception: if no document with that name is found
			Exception: if multiple documents with that name are found
	"""



	select_query = sql.SQL("""SELECT name,content,content_byte 
							 FROM documents d
							 JOIN membership m ON d.organisationid = m.organisationid
							 WHERE d.name = (%s) AND m.userid = (%s) AND m.organisationid = (%s)
							 """)

	result = execute_query(select_query, (document_name, user_id, organisation_id,))
	if len(result) == 1:
		document = result[0]
		name = document[0]
		if document[1]:
			content = document[1]
			return str(name), str(content)
		elif document[2]:
			content = document[2]
			return str(name), bytes(content)
	elif len(result) > 1:
		raise Exception("Multiple documents with the same name found")
	else:
		raise Exception("No document with that name found")


def getDocument(document_id: int, user_id: int):
	select_query = sql.SQL("""SELECT name,content,content_byte 
							 FROM documents 
							 JOIN membership m ON documents.organisationid = m.organisationid
							 WHERE id = (%s) AND m.userid = (%s)
							 """)

	result = execute_query(select_query, (document_id, user_id,))
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


def getDocumentsForOrganization(organisation_id: int):

	select_query = sql.SQL("""SELECT id, name,content,content_byte 
						 FROM documents 
						 WHERE organisationid = (%s)
						 """)
	result = execute_query(select_query, (organisation_id,))

	if result is None or len(result) == 0:
		return []

	doc_array = []

	for document in result:
		id = document[0]
		name = document[1]
		content = ''
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


def updateDocumentContent(doc_id: int, new_content):
	try:
		select_query = sql.SQL("""SELECT content, content_byte
								FROM documents
								WHERE id = (%s)
							 """)
		result = execute_query(select_query, (doc_id,))
		if result == None or len(result) == 0:
			return False
		content_type = "content"
		if result[0][0] == None:
			content_type = "content_byte"
		update_query = sql.SQL("UPDATE documents SET " + content_type + " = (%s) WHERE id = (%s)")
		execute_transaction(update_query, (new_content, doc_id,), commit=True, fetch=False)
		return True
	except Exception as e:
		print("updateDocumentContent failed because:\n", e)
		return False

def deleteDocumentContent(doc_id: int):
	try:
		delete_query = sql.SQL("""DELETE
								FROM documents
								WHERE id = (%s)
							 """)
		execute_transaction(delete_query, (doc_id,), commit=True, fetch=False)
		return True
	except Exception as e:
		print("updateDocumentContent failed because:\n", e)
		return False


def getDocuments(document_ids: list[int], user_id: int):
	select_query = sql.SQL(f"""SELECT name,content,content_byte 
							 FROM documents 
							 JOIN membership m ON documents.organisationid = m.organisationid
							 WHERE m.userid = (%s) and documents.id in 
							 ({",".join(str(_id) for _id in document_ids)})
							 """)
	result = execute_query(select_query, (user_id,))
	if isinstance(result, list) and isinstance(result[0], tuple):
		if len(result) > 0:
			if result[0][1]:
				documents = []
				for document in result:
					name = document[0]
					content = document[1]
					documents.append((str(name), str(content)))
				return documents
			elif result[0][2]:
				b_documents = []
				for document in result:
					name = document[0]
					content = document[2]
					b_documents.append((str(name), bytes(content)))
				return b_documents
	return []



def getDocument_ids(organisation_id: int, user_id: int):
	select_query = sql.SQL("""SELECT name,content,content_byte 
									from documents 
									join membership m on documents.organisationid = m.organisationid
									where m.organisationid = (%s) and m.userid = (%s)
									""")

	result = execute_query(select_query, (organisation_id, user_id,))
	if isinstance(result, list) and isinstance(result[0], tuple):
		if len(result) > 0:
			if result[0][1]:
				documents = []
				for document in result:
					name = document[0]
					content = document[1]
					documents.append((str(name), str(content)))
				return documents
			elif result[0][2]:
				b_documents = []
				for document in result:
					name = document[0]
					content = document[2]
					b_documents.append((str(name), bytes(content)))
				return b_documents
	return []

