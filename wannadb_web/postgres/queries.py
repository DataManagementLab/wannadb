import logging
from typing import Union
from deprecated import deprecated

import bcrypt
from psycopg2 import sql

from wannadb_web.postgres.util import execute_query, execute_transaction

logger = logging.getLogger(__name__)


def get_organisation_authorisation(user_id: int, organisation_id: int):
	"""Return a recognized membership role, or None when access is not established."""
	query = sql.SQL("SELECT authorisation FROM membership WHERE userid = %s AND organisationid = %s;")
	result = execute_query(query, (user_id, organisation_id))
	if isinstance(result, list) and len(result) == 1:
		role = result[0][0]
		if type(role) is int and role in (0, 1, 10):
			return role
	return None


def get_document_scope(document_id: int, user_id: int):
	"""Resolve the document's actual organization and base only for a current member."""
	query = sql.SQL("""SELECT d.organisationid, d.documentbaseid, b.name
		FROM documents d
		JOIN membership m ON m.organisationid = d.organisationid
		LEFT JOIN document_bases b ON b.id = d.documentbaseid AND b.organisation_id = d.organisationid
		WHERE d.id = %s AND m.userid = %s AND m.authorisation IN (0, 1, 10);""")
	result = execute_query(query, (document_id, user_id))
	if isinstance(result, list) and len(result) == 1:
		return tuple(result[0])
	return None


def documents_available_for_base(document_ids: list[int], user_id: int, organisation_id: int):
	"""Require every selected document to be unassigned and in the authorized organization."""
	if (not isinstance(document_ids, list) or
		any(type(document_id) is not int or document_id <= 0 for document_id in document_ids) or
		len(set(document_ids)) != len(document_ids)):
		return False
	if get_organisation_authorisation(user_id, organisation_id) is None:
		return False
	query = sql.SQL("""SELECT id FROM documents WHERE id = ANY(%s)
		AND organisationid = %s AND documentbaseid IS NULL;""")
	result = execute_query(query, (document_ids, organisation_id))
	return (not document_ids and result is None) or (
		isinstance(result, list) and {row[0] for row in result} == set(document_ids))


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
	if not isinstance(user, str) or not isinstance(password, str):
		return False
	select_query = sql.SQL("SELECT password, id FROM users WHERE username = %s;")
	result = execute_query(select_query, (user,))
	if not isinstance(result, list) or not result:
		return False
	stored_password, user_id = result[0]
	if isinstance(stored_password, str):
		stored_password = stored_password.encode('utf-8')
	elif isinstance(stored_password, (bytes, bytearray, memoryview)):
		stored_password = bytes(stored_password)
	else:
		return False
	try:
		if bcrypt.checkpw(password.encode('utf-8'), stored_password):
			return int(user_id)
	except (TypeError, ValueError):
		pass
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
	select_query = sql.SQL("SELECT id FROM document_bases WHERE name = %s AND organisation_id = %s;")
	result = execute_query(select_query, (base_name, org_id))
	if isinstance(result, list) and result and type(result[0][0]) is int:
		return result[0][0]
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
		"WHERE documentbaseid = (%s) AND organisationid = (%s)"
	)

	result = execute_query(select_documents_query, (data["id"], organisation_id))

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


def get_document_by_name(document_name: str, organisation_id: int, user_id: int, base_name: str = None) -> tuple[str, Union[str, bytes]]:
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
							 AND m.authorisation IN (0, 1, 10)
							 AND (%s IS NULL OR d.documentbaseid = (SELECT id FROM document_bases
							 WHERE name = %s AND organisation_id = %s))
							 """)

	result = execute_query(select_query, (document_name, user_id, organisation_id, base_name, base_name, organisation_id))
	if not isinstance(result, list) or not result:
		raise Exception("No document with that name found")
	if len(result) == 1:
		document = result[0]
		id = document[0]
		if document[1] is not None:
			content = document[1]
			return str(id), str(content)
		elif document[2] is not None:
			content = document[2]
			return str(id), bytes(content)
	elif len(result) > 1:
		raise Exception("Multiple documents with the same name found")
	raise Exception("No document with that name found")


def get_document(document_id: int, user_id: int, organisation_id: int = None, base_name: str = None):
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
							 AND m.authorisation IN (0, 1, 10)
							 AND (%s IS NULL OR documents.organisationid = %s)
							 AND (%s IS NULL OR documents.documentbaseid = (SELECT id FROM document_bases
							 WHERE name = %s AND organisation_id = %s))
							 """)

	result = execute_query(select_query, (document_id, user_id, organisation_id, organisation_id, base_name, base_name, organisation_id))
	if isinstance(result, list) and result:
		for document in result:
			name = document[0]
			if document[1] is not None:
				content = document[1]
				return str(name), str(content)
			elif document[2] is not None:
				content = document[2]
				return str(name), bytes(content)
	return None, None


def get_document_by_name_and_content(doc_name: str, doc_content: Union[str, bytes], user_id: int, organisation_id: int = None, base_name: str = None):
	"""
	Gets a document by its name and content for a specific user.
 
	:param doc_name: The name of the document to retrieve.
	:type doc_name: str
	:param doc_content: The content of the document to retrieve.
	:type doc_content: Union[str, bytes]
	:param user_id: The ID of the user requesting the document.
	:type user_id: int
	:return: A tuple containing the document name and its content (as str or bytes), or None if not found.
	:rtype: Union[tuple[str, Union[str, bytes]], tuple[None, None]]
	"""
	select_query = sql.SQL("""	SELECT id, name,content,content_byte 
							 	FROM documents 
							 	JOIN membership m ON documents.organisationid = m.organisationid
							 	WHERE name = (%s) AND m.userid = (%s)
								AND m.authorisation IN (0, 1, 10)
								AND (%s IS NULL OR documents.organisationid = %s)
								AND (%s IS NULL OR documents.documentbaseid = (SELECT id FROM document_bases
								WHERE name = %s AND organisation_id = %s))
							 """)
        						#AND content LIKE %(%s)%

	result = execute_query(select_query, (doc_name, user_id, organisation_id, organisation_id, base_name, base_name, organisation_id))
	if isinstance(result, list) and result:
		for document in result:
			name = document[1]
			if document[2] is not None:
				content = document[2]
				if content == doc_content:
					return int(document[0]), str(name), str(content)
			elif document[3] is not None:
				content = document[3]
				if content == doc_content:
					return int(document[0]), str(name), bytes(content)
	return None, None, None


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
	select_query = sql.SQL("""SELECT id, name, attributes, last_modified
						 FROM document_bases

						 WHERE organisation_id = (%s)
						 """)
	result = execute_query(select_query, (organisation_id,))

	if result is None or not result:
		return []

	doc_array = [{"id": id, "name": name, "attributes": attributes, "lastModified": last_modified} for id, name, attributes, last_modified in result]
	return doc_array


def update_document_content(doc_id: int, new_content, organisation_id: int = None, base_id: int = None, user_id: int = None):
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
		scope = sql.SQL("""d.id = %s
			AND (%s IS NULL OR d.organisationid = %s)
			AND (%s IS NULL OR d.documentbaseid IS NOT DISTINCT FROM %s)
			AND (%s IS NULL OR EXISTS (SELECT 1 FROM membership m WHERE m.userid = %s
			AND m.organisationid = d.organisationid AND m.authorisation IN (0, 1, 10)))""")
		params = (doc_id, organisation_id, organisation_id, user_id, base_id, user_id, user_id)
		lookup = sql.SQL("SELECT content FROM documents d WHERE {scope};").format(scope=scope)
		current = execute_query(lookup, params)
		if not isinstance(current, list) or not current:
			return False
		column = sql.Identifier("content" if current[0][0] is not None else "content_byte")
		query = sql.SQL("UPDATE documents d SET {column} = %s WHERE {scope} RETURNING d.id;").format(
			column=column, scope=scope)
		result = execute_transaction(query, (new_content,) + params, commit=True)
		return isinstance(result, list) and bool(result)
	except Exception:
		logger.error("Could not update document content")
		return False


def compare_and_swap_document_content(doc_id: int, new_bytes: bytes, expected_bytes: bytes,
		organisation_id: int, user_id: int, base_id: int = None) -> bool:
	"""Replace a standalone BSON snapshot only while its exact loaded bytes remain current."""
	if not isinstance(new_bytes, bytes) or not isinstance(expected_bytes, bytes):
		return False
	try:
		query = sql.SQL("""UPDATE documents d SET content_byte = %s
			WHERE d.id = %s AND d.organisationid = %s AND d.documentbaseid IS NULL
			AND d.content IS NULL AND d.content_byte = %s
			AND EXISTS (SELECT 1 FROM membership m WHERE m.userid = %s
			AND m.organisationid = d.organisationid AND m.authorisation IN (0, 1, 10))
			AND (%s IS NULL OR EXISTS (SELECT 1 FROM document_bases b
			WHERE b.id = %s AND b.organisation_id = d.organisationid))
			RETURNING d.id;""")
		result = execute_transaction(query, (new_bytes, doc_id, organisation_id, expected_bytes,
			user_id, base_id, base_id), commit=True)
		return isinstance(result, list) and bool(result)
	except Exception:
		logger.error("Could not replace document-base snapshot")
		return False


def delete_document_content(doc_id: int, organisation_id: int = None, base_id: int = None, user_id: int = None):
	"""
	Deletes a document by its ID.
 
	:param doc_id: The ID of the document to delete.
	:type doc_id: int
	:return: True if the deletion was successful, False otherwise.
	:rtype: bool
	"""
	try:
		query = sql.SQL("""DELETE FROM documents d WHERE d.id = %s
			AND (%s IS NULL OR d.organisationid = %s)
			AND (%s IS NULL OR d.documentbaseid IS NOT DISTINCT FROM %s)
			AND (%s IS NULL OR EXISTS (SELECT 1 FROM membership m WHERE m.userid = %s
			AND m.organisationid = d.organisationid AND m.authorisation IN (0, 1, 10)))
			RETURNING d.id;""")
		result = execute_transaction(query, (doc_id, organisation_id, organisation_id,
			user_id, base_id, user_id, user_id), commit=True)
		return isinstance(result, list) and bool(result)
	except Exception:
		logger.error("Could not delete document")
		return False


def get_documents(document_ids: list[int], user_id: int, organisation_id: int = None):
	"""
	Gets multiple documents by their IDs for a specific user.
 
	:param document_ids: A list of document IDs to retrieve.
	:type document_ids: list[int]
	:param user_id: The ID of the user requesting the documents.
	:type user_id: int
	:return: A list of tuples containing document names and their contents (as str or bytes).
	:rtype: list[tuple[str, Union[str, bytes]]]
	"""
	if (not isinstance(document_ids, list) or not document_ids or
		any(type(document_id) is not int or document_id <= 0 for document_id in document_ids)):
		return [(None, None)]
	select_query = sql.SQL("""SELECT d.name, d.content, d.content_byte FROM documents d
		JOIN membership m ON d.organisationid = m.organisationid
		WHERE m.userid = %s AND m.authorisation IN (0, 1, 10) AND d.id = ANY(%s)
		AND (%s IS NULL OR d.organisationid = %s);""")
	result = execute_query(select_query, (user_id, document_ids, organisation_id, organisation_id))
	if not isinstance(result, list) or len(result) != len(set(document_ids)):
		return [(None, None)]
	documents = []
	for name, text, binary in result:
		if text is not None:
			documents.append((str(name), str(text)))
		elif binary is not None:
			documents.append((str(name), bytes(binary)))
		else:
			return [(None, None)]
	return documents


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
