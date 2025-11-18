import logging
from typing import Union
from warnings import deprecated

import bcrypt
from psycopg2 import sql

from wannadb_web.postgres.util import execute_query, execute_transaction

logger = logging.getLogger(__name__)


def get_user_id(user: str):
	"""
    Gets the user ID for a given username.
    
    :param user: The username to look up.
    :type user: str
    :return: The user ID if found, otherwise None.
	:rtype: Union[int, None]
	"""
	select_query = sql.SQL("SELECT id FROM users WHERE username = %s;")
	result = execute_query(select_query, (user,))
	if isinstance(result[0], int):
		return int(result[0])
	return None


def get_organisation_id(organisation_name: str):
	"""
    Gets the organisation ID for a given organisation name.
    
    :param organisation_name: The name of the organisation to look up.
    :type organisation_name: str
	:return: The organisation ID if found, otherwise None.
	:rtype: Union[int, None]"""
	select_query = sql.SQL("SELECT id FROM organisations WHERE name = %s;")
	return execute_query(select_query, (organisation_name,))


def get_organisation_name(organisation_id: int):
	"""
    Gets the organisation name for a given organisation ID.
    
    :param organisation_id: The ID of the organisation to look up.
	:type organisation_id: int
	:return: The organisation name if found, otherwise -1.
	:rtype: Union[str, int]
	"""
	select_query = sql.SQL("SELECT name FROM organisations WHERE id = %s;")
	response = execute_query(select_query, (organisation_id,))
	if response is None:
		return -1
	return str(response[0])


def get_members_of_organisation(organisation_id: int):
	"""
    Gets the usernames of all members in a given organisation.
    
    :param organisation_id: The ID of the organisation to look up.
	:type organisation_id: int
	:return: A list of usernames of members in the organisation.
	:rtype: list[str]
	"""
	select_query = sql.SQL(
		"SELECT username FROM users WHERE id IN (SELECT userid FROM membership WHERE organisationid = %s);")
	return execute_query(select_query, (organisation_id,))


def get_member_ids_from_organisation_id(organisationID: int):
	"""
    Gets the user IDs of all members in a given organisation.
    
    :param organisationID: The ID of the organisation to look up.
	:type organisationID: int
	:return: A list of user IDs of members in the organisation.
	:rtype: list[int]
	"""
	select_query = sql.SQL("SELECT userid FROM membership WHERE organisationid = %s;")
	return execute_query(select_query, (organisationID,))


def get_username_suggestion(prefix: str):
	"""
    Gets a list of usernames that start with the given prefix.
    
    :param prefix: The prefix to search for.
	:type prefix: str
	:return: A list of usernames that start with the prefix.
	:rtype: list[str]
	"""
	select_query = sql.SQL("SELECT username FROM users WHERE username LIKE %s;")
	return execute_query(select_query, (prefix + "%",))


def get_organisation_ids_from_user_id(userID: int):
	"""
    Gets the organisation IDs associated with a given user ID.
	
	:param userID: The ID of the user to look up.
	:type userID: int
	:return: A tuple containing a list of organisation IDs or None, and an error message or None.
	:rtype: tuple[Union[list[int], None], Union[str, Exception, None]]
	"""
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


def get_organisation_from_user_id(user_id: int):
	"""
	Gets the organisations associated with a given user ID.
	
	:param user_id: The ID of the user to look up.
	:type user_id: int
	:return: A tuple containing a list of organisations or None, and an error message or None.
	:rtype: tuple[Union[list[dict[str, Union[str, int]]], None], Union[str, Exception, None]]
	"""
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


def check_password(user: str, password: str):
	"""
 	Checks if the password is correct for the given user

	:param user: the username to check
	:type user: str
	:param password: the password to check
	:type password: str
	:return: user ID if password is correct, False otherwise
	:rtype: Union[int, bool]
	:raises Exception: Exception (if something went wrong)
	"""
	select_query = sql.SQL("SELECT password,id as pw FROM users WHERE username = %s ")

	result = execute_query(select_query, (user,))
	if result is None or not result:
		return False
	_password, _id = result[0]

	if _password:
		stored_password = bytes(_password, 'utf-8')
		check = bcrypt.checkpw(password.encode('utf-8'), stored_password)
		if check:
			return int(_id)

	return False


def check_organisation_authorisation(organisationName: str, userName: str):
	"""
	Checks the authorisation level of a user in a given organisation.
 
	:param organisationName: The name of the organisation.
	:type organisationName: str
	:param userName: The username of the user.
	:type userName: str
	:return: The authorisation level if found, otherwise None.
	:rtype: Union[int, None]
	"""
	select_query = sql.SQL("SELECT authorisation from membership "
						   "where userid = (SELECT id from users where username = (%s)) "
						   "and "
						   "organisationid = (Select id from organisations where name = (%s))")

	result = execute_query(select_query, (organisationName, userName))
	if isinstance(result[0], int):
		return int(result[0])
	if result[0] is None:
		return None


def get_base_id(base_name: str, org_id: int):
	"""
	Gets the document base ID for a given base name and organisation ID.
 
	:param base_name: The name of the document base.
	:type base_name: str
	:param org_id: The ID of the organisation.
	:type org_id: int
	:return: The document base ID if found, otherwise None.
	:rtype: Union[int, None]
	"""
	select_query = sql.SQL(
		"SELECT id from document_bases "
		"WHERE name = (%s) AND organisation_id = (%s)"
	)

	result = execute_query(select_query, (base_name, org_id))
	if isinstance(result[0], int):
		return int(result[0])
	if result[0] is None:
		return None


def get_document_base_data(base_name: str, organisation_id: int):
	select_query = sql.SQL(
		"SELECT id, name, attributes from document_bases "
		"WHERE name = (%s) AND organisation_id = (%s)"
	)

	result = execute_query(select_query, (base_name, organisation_id))
	if not result:
		return None

	data = {
		'id': result[0][0],
		'name': result[0][1],
		'attributes': str(result[0][2]).replace('{', '').replace('}', '').split(","),
		"documents": []
	}

	select_documents_query = sql.SQL(
		"SELECT id, name, content from documents "
		"WHERE documentbaseid = (%s)"
	)

	result = execute_query(select_documents_query, (data["id"],))

	if not result:
		documents = []
	else:
		documents = [
			{
				"id": res[0],
				"name": res[1],
				"content": res[2]
			}
			for res in result if res[2]
		]

	data["documents"] = documents

	return data


@deprecated
def _get_document(documentId: int):
	"""
	Get document content by document ID.
 
	:param documentId: The ID of the document to retrieve.
	:type documentId: int
	:return: The content of the document as a string or bytes, or None if not found.
	:rtype: Union[str, bytes, None]
	"""
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


def get_document_by_name(document_name: str, organisation_id: int, user_id: int) -> tuple[str, Union[str, bytes]]:
	"""
	Gets a document by its name within a specific organisation for a specific user.
 
	:param document_name: The name of the document to retrieve.
	:type document_name: str
	:param organisation_id: The ID of the organisation the document belongs to.
	:type organisation_id: int
	:param user_id: The ID of the user requesting the document.
	:type user_id: int
	:return: A tuple containing the document name and its content (as str or bytes).
	:rtype: tuple[str, Union[str, bytes]]
	:raises Exception: if no document with that name is found
	:raises Exception: if multiple documents with that name are found
	"""
	select_query = sql.SQL("""SELECT id,content,content_byte

							 FROM documents d
							 JOIN membership m ON d.organisationid = m.organisationid
							 WHERE d.name = (%s) AND m.userid = (%s) AND m.organisationid = (%s)
							 """)

	result = execute_query(select_query, (document_name, user_id, organisation_id,))
	if result is None:
		raise Exception("No document with that name found")
	if len(result) == 1:
		document = result[0]
		id = document[0]
		if document[1]:
			content = document[1]
			return str(id), str(content)
		elif document[2]:
			content = document[2]
			return str(id), bytes(content)
	elif len(result) > 1:
		raise Exception("Multiple documents with the same name found")
	raise Exception("No document with that name found")


def get_document(document_id: int, user_id: int):
	"""
	Gets a document by its ID for a specific user.
 
	:param document_id: The ID of the document to retrieve.
	:type document_id: int
	:param user_id: The ID of the user requesting the document.
	:type user_id: int
	:return: A tuple containing the document name and its content (as str or bytes), or None if not found.
	:rtype: Union[tuple[str, Union[str, bytes]], None]
	"""
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


@deprecated
def get_document_by_name_and_content(doc_name: str, doc_content: str, user_id: int):
	"""
	Gets a document by its name and content for a specific user.\n
	**Warning**: This functioned does not work as intended and is therefore deprecated.
 
	:param doc_name: The name of the document to retrieve.
	:type doc_name: str
	:param doc_content: The content of the document to retrieve.
	:type doc_content: str
	:param user_id: The ID of the user requesting the document.
	:type user_id: int
	:return: A tuple containing the document name and its content (as str or bytes), or None if not found.
	:rtype: Union[tuple[str, Union[str, bytes]], None]
	"""
	select_query = sql.SQL("""	SELECT name,content,content_byte 
							 	FROM documents 
							 	JOIN membership m ON documents.organisationid = m.organisationid
							 	WHERE name = (%s) AND m.userid = (%s)
							 """)
        						#AND content LIKE %(%s)%

	result = execute_query(select_query, (doc_name, user_id, ))
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


def get_documents_for_organisation(organisation_id: int):
	"""
	Gets all documents for a specific organisation.
 
	:param organisation_id: The ID of the organisation to retrieve documents for.
	:type organisation_id: int
	:return: A list of dictionaries containing document IDs, names, and contents.
	:rtype: list[dict[str, Union[int, str]]]
	"""
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
		if document[2] == None:
			continue
		content = document[2]
		doc_array.append({
			"id": id,
			"name": name,
			"content": content
		})
	return doc_array


def get_document_bases_for_organisation(organisation_id: int):
	"""
	Gets all document bases for a specific organisation.
 
	:param organisation_id: The ID of the organisation to retrieve document bases for.
	:type organisation_id: int
	:return: A list of dictionaries containing document base IDs, names, and attributes.
	:rtype: list[dict[str, Union[int, str, list[str]]]]
	"""
	select_query = sql.SQL("""SELECT id, name, attributes
						 FROM document_bases

						 WHERE organisation_id = (%s)
						 """)
	result = execute_query(select_query, (organisation_id,))

	if result is None or not result:
		return []

	doc_array = [{"id": id, "name": name, "attributes": attributes} for id, name, attributes in result]
	return doc_array


def update_document_content(doc_id: int, new_content):
	"""
	Updates the content of a document by its ID.
 
	:param doc_id: The ID of the document to update.
	:type doc_id: int
	:param new_content: The new content to set for the document.
	:type new_content: Union[str, bytes]
	:return: True if the update was successful, False otherwise.
	:rtype: bool
	"""
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
		logger.error(f"updateDocumentContent failed because:\n{e}")
		return False


def delete_document_content(doc_id: int):
	"""
	Deletes a document by its ID.
 
	:param doc_id: The ID of the document to delete.
	:type doc_id: int
	:return: True if the deletion was successful, False otherwise.
	:rtype: bool
	"""
	try:
		delete_query = sql.SQL("""DELETE
								FROM documents
								WHERE id = (%s)
							 """)
		execute_transaction(delete_query, (doc_id,), commit=True, fetch=False)
		return True
	except Exception as e:
		logger.error(f"updateDocumentContent failed because:\n{e}")
		return False


def get_documents(document_ids: list[int], user_id: int):
	"""
	Gets multiple documents by their IDs for a specific user.
 
	:param document_ids: A list of document IDs to retrieve.
	:type document_ids: list[int]
	:param user_id: The ID of the user requesting the documents.
	:type user_id: int
	:return: A list of tuples containing document names and their contents (as str or bytes).
	:rtype: list[tuple[str, Union[str, bytes]]]
	"""
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
	return [(None,None)]


def get_document_ids(organisation_id: int, user_id: int):
	"""
	Gets all document IDs for a specific organisation and user.
 
	:param organisation_id: The ID of the organisation to retrieve documents for.
	:type organisation_id: int
	:param user_id: The ID of the user requesting the documents.
	:type user_id: int
	:return: A list of tuples containing document names and their contents (as str or bytes).
	:rtype: list[tuple[str, Union[str, bytes]]]
	"""
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


def get_feedbacks_for_document(document_id: int):
	"""
    Retrieves feedback summary for a given document.
    
    :param document_id: ID of the document to retrieve feedback for.
    :type document_id: int
	:return: A dictionary summarizing feedback counts by attribute and positivity.
    :rtype: dict[str, dict[str, int]]
	"""
	select_query = sql.SQL("""SELECT attribute, positive, count(*)
								FROM document_feedback 
								WHERE documentid = (%s)
								GROUP BY positive, attribute
							 """)
	result = execute_query(select_query, (document_id,))
	feedback_summary = {}
	if result is None:
		return feedback_summary
	for attribute, positive, count in result:
		if attribute not in feedback_summary:
			feedback_summary[attribute] = {"positive": 0, "negative": 0}
		if positive:
			feedback_summary[attribute]["positive"] += count
		else:
			feedback_summary[attribute]["negative"] += count
	return feedback_summary
