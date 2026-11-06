import logging
from typing import Union
from deprecated import deprecated

import bcrypt
from psycopg2 import sql, IntegrityError
from wannadb_web.util import Token, Authorisation, tokenDecode
from wannadb_web.postgres.queries import check_password, get_organisation_authorisation
from wannadb_web.postgres.util import execute_transaction

logger: logging.Logger = logging.getLogger(__name__)


# Schema tooling is offline administration only, with an explicit schema allowlist.
def _schema_identifier(schema):
	if schema != "public":
		raise ValueError("Schema is not allowed")
	return sql.Identifier(schema)


def create_schema(schema):
	"""
	Creates a new schema in the database if it does not already exist.
	
	:param schema: The name of the schema to create.
	:type schema: str
	:return: None
	"""
	create_schema_query = sql.SQL("CREATE SCHEMA IF NOT EXISTS {schema};").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_schema_query, commit=True, fetch=False)
	logger.info(f"Schema {schema} created successfully.")


def drop_schema(schema):
	"""
	Drops a schema in the database if it exists.
	
	:param schema: The name of the schema to drop.
	:type schema: str
	:return: None
	"""
	drop_schema_query = sql.SQL("DROP SCHEMA IF EXISTS {schema} CASCADE;").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(drop_schema_query, commit=True, fetch=False)
	logger.info(f"Schema {schema} dropped successfully.")


def drop_tables(schema):
	"""
	Drops all tables in the specified schema.
 
	:param schema: The name of the schema containing the tables to drop.
	:type schema: str
	:return: None
	"""
	drop_table_query = sql.SQL("DROP TABLE IF EXISTS {schema}.users CASCADE;\n"
		"DROP TABLE IF EXISTS {schema}.documents CASCADE;\n"
		"DROP TABLE IF EXISTS {schema}.membership CASCADE;\n"
		"DROP TABLE IF EXISTS {schema}.organisations CASCADE;\n"
		"DROP TABLE IF EXISTS {schema}.document_bases CASCADE;\n").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(drop_table_query, commit=True)


def create_user_table(schema):
	"""
	Creates the users table in the specified schema.
 
	:param schema: The name of the schema where the users table will be created.
	:type schema: str
	:return: None
	"""
	create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS {schema}.users
	(
    id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
    username text COLLATE pg_catalog."default" NOT NULL,
    password bytea NOT NULL,
    CONSTRAINT userid PRIMARY KEY (id),
    CONSTRAINT unique_username UNIQUE (username)
	)

	TABLESPACE pg_default;
	""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_table_query, commit=True, fetch=False)


def create_documents_table(schema):
	"""
	Creates the documents table in the specified schema.
 
	:param schema: The name of the schema where the documents table will be created.
	:type schema: str
	:return: None
	"""
	create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS  {schema}.documents
	(
		id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
		name text NOT NULL,
		content text ,
		content_byte   bytea,
		organisationid bigint NOT NULL,
		userid bigint NOT NULL,
		documentbaseid bigint NULL,
		CONSTRAINT dokumentid PRIMARY KEY (id),
		CONSTRAINT documents_organisationid_fkey FOREIGN KEY (organisationid)
			REFERENCES {schema}.organisations (id) MATCH SIMPLE
			ON UPDATE CASCADE 
			ON DELETE CASCADE 
			NOT VALID,
		CONSTRAINT documents_userid_fkey FOREIGN KEY (userid)
			REFERENCES {schema}.users (id) MATCH SIMPLE
			ON UPDATE CASCADE 
			ON DELETE CASCADE 
			NOT VALID,
		CONSTRAINT douments_documentbase_fkey FOREIGN KEY (documentbaseid)
			REFERENCES {schema}.document_bases (id) MATCH SIMPLE
			ON UPDATE CASCADE
			ON DELETE CASCADE
	)

	TABLESPACE pg_default;""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_table_query, commit=True, fetch=False)

	add_docBase_column_query = sql.SQL("""
	DO $$ 
	BEGIN
		IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
				WHERE table_schema = {schema_name} 
				AND table_name = 'documents' 
				AND column_name = 'documentbaseid') THEN
			ALTER TABLE {schema}.documents ADD COLUMN documentbaseid bigint;
			ALTER TABLE {schema}.documents ADD CONSTRAINT douments_documentbase_fkey FOREIGN KEY (documentbaseid)
				REFERENCES {schema}.document_bases (id) MATCH SIMPLE
				ON UPDATE CASCADE
				ON DELETE CASCADE;
		END IF;
	END $$;
	""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(add_docBase_column_query, commit=True, fetch=False)


def create_document_feedback_table(schema):
	"""
	Creates the document_feedback table in the specified schema.
 
	:param schema: The name of the schema where the document_feedback table will be created.
	:type schema: str
	:return: None
	"""
	create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS {schema}.document_feedback
	(
	id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
	documentid bigint NOT NULL,
	userid bigint NOT NULL,
	positive boolean NOT NULL,
	attribute text NOT NULL,
	feedback_start int NULL,
	feedback_end int NULL,
	CONSTRAINT documentfeedbackid PRIMARY KEY (id),
	CONSTRAINT documentfeedback_documentid_fkey FOREIGN KEY (documentid)
		REFERENCES {schema}.documents (id) MATCH SIMPLE
		ON UPDATE CASCADE 
		ON DELETE CASCADE 
		NOT VALID,
	CONSTRAINT documentfeedback_userid_fkey FOREIGN KEY (userid)
		REFERENCES {schema}.users (id) MATCH SIMPLE
		ON UPDATE CASCADE 
		ON DELETE CASCADE 
		NOT VALID
)
TABLESPACE pg_default;
""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_table_query, commit=True, fetch=False)


def create_membership_table(schema):
	"""
	Creates the membership table in the specified schema.
 
	:param schema: The name of the schema where the membership table will be created.
	:type schema: str
	:return: None
	"""
	create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS {schema}.membership
(
    userid bigint NOT NULL,
    organisationid bigint NOT NULL,
    authorisation bigint NOT NULL DEFAULT 10,
    CONSTRAINT membership_pkey PRIMARY KEY (userid, organisationid),
    CONSTRAINT membership_organisationid_fkey FOREIGN KEY (organisationid)
        REFERENCES {schema}.organisations (id) MATCH SIMPLE
        ON UPDATE CASCADE 
        ON DELETE CASCADE 
        NOT VALID,
    CONSTRAINT membership_userid_fkey FOREIGN KEY (userid)
        REFERENCES {schema}.users (id) MATCH SIMPLE
        ON UPDATE CASCADE 
        ON DELETE CASCADE 
        NOT VALID
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS {schema}.membership
    OWNER to postgres;
-- Index: fki_organisationid

-- DROP INDEX IF EXISTS {schema}.fki_organisationid;

CREATE INDEX IF NOT EXISTS fki_organisationid
    ON {schema}.membership USING btree
    (organisationid ASC NULLS LAST)
    TABLESPACE pg_default;""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_table_query, commit=True, fetch=False)


def create_document_base_table(schema):
	"""
	Creates the document_bases table in the specified schema.
 
	:param schema: The name of the schema where the document_bases table will be created.
	:type schema: str
	:return: None
	"""
	create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS {schema}.document_bases
		(
			id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
			name text COLLATE pg_catalog."default" NOT NULL,
			attributes text NOT NULL DEFAULT '[]',
			organisation_id bigint NOT NULL,
			last_modified timestamp without time zone NOT NULL DEFAULT now(),
			CONSTRAINT documentbaseid PRIMARY KEY (id),
			CONSTRAINT documentbase_name_key UNIQUE (name, organisation_id),
			CONSTRAINT documentbase_organisationid_fkey FOREIGN KEY (organisation_id)
				REFERENCES {schema}.organisations (id) MATCH SIMPLE
				ON UPDATE CASCADE 
				ON DELETE CASCADE
		)

		TABLESPACE pg_default;

		""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_table_query, commit=True, fetch=False)

	add_last_modified_column_query = sql.SQL("""
	DO $$
	BEGIN
		IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
				WHERE table_schema = {schema_name} 
				AND table_name = 'document_bases' 
				AND column_name = 'last_modified') THEN
			ALTER TABLE {schema}.document_bases ADD COLUMN last_modified timestamp without time zone NOT NULL DEFAULT now();
		END IF;
	END $$;
	""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(add_last_modified_column_query, commit=True, fetch=False)
 
	create_function_query = sql.SQL("""
		CREATE OR REPLACE FUNCTION {schema}.update_last_modified()
		RETURNS TRIGGER AS $$
		BEGIN
		NEW.last_modified = now();
		RETURN NEW;
		END;
		$$ LANGUAGE plpgsql;
	""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_function_query, commit=True, fetch=False)
 
	create_trigger_query = sql.SQL("""
		DROP TRIGGER IF EXISTS update_last_modified_trigger ON {schema}.document_bases;
		
  		CREATE TRIGGER update_last_modified_trigger
		BEFORE UPDATE ON {schema}.document_bases
		FOR EACH ROW
		EXECUTE FUNCTION {schema}.update_last_modified();
	""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_trigger_query, commit=True, fetch=False)


def create_organisation_table(schema):
	"""
	Creates the organisations table in the specified schema.
 
	:param schema: The name of the schema where the organisations table will be created.
	:type schema: str
	:return: None
	"""
	create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS {schema}.organisations
(
    id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
    name text COLLATE pg_catalog."default" NOT NULL,
    CONSTRAINT organisationid PRIMARY KEY (id),
    CONSTRAINT organisations_name_key UNIQUE (name)
)

TABLESPACE pg_default;

""").format(schema=_schema_identifier(schema), schema_name=sql.Literal(schema))
	execute_transaction(create_table_query, commit=True, fetch=False)


def add_user(user: str, password: str):
	"""
	Adds a new user to the database.
 
	:param user: the username of the new user
	:type user: str
	:param password: the password of the new user
	:type password: str
	:return: int (user id)
	:raises: Exception if the user could not be added
	"""

	pwBytes = password.encode('utf-8')
	salt = bcrypt.gensalt()
	pwHash = bcrypt.hashpw(pwBytes, salt)
	# Needed this for the correct password check don't know why...
	pwHashcode = pwHash.decode('utf-8')

	insert_data_query = sql.SQL("INSERT INTO users (username, password) VALUES (%s, %s) returning id;")
	data_to_insert = (user, pwHashcode)
	response = execute_transaction(insert_data_query, data_to_insert, commit=True)
	if response is IntegrityError:
		raise IntegrityError("User already exists")
	if isinstance(response[0][0], int):
		return int(response[0][0])
	raise Exception("addUser failed because: \n", response)


def change_password(user: str, old_password: str, new_password: str):
	"""
	Changes the password of an existing user.
 
	:param user: the username of the user
	:type user: str
	:param old_password: the current password of the user
	:type old_password: str
	:param new_password: the new password of the user
	:type new_password: str
	:return: bool
	:raises: Exception if the password could not be changed
	"""
	try:
		if old_password == new_password:
			return False

		pwcheck = check_password(user, old_password)
		if isinstance(pwcheck, Exception):
			raise pwcheck
		if isinstance(pwcheck, bool):
			return bool(pwcheck)
		if isinstance(pwcheck, int):
			_ = int(pwcheck)

			pwBytes = new_password.encode('utf-8')
			salt = bcrypt.gensalt()
			pwHash = bcrypt.hashpw(pwBytes, salt)

			update_query = sql.SQL("UPDATE users SET password = %s WHERE username = %s;")
			execute_transaction(update_query, (pwHash, user), commit=True)

	except Exception as e:
		logger.error(f"changePassword failed because: \n{e}")


def delete_user_transaction(user: str, password: str):
	"""
	Deletes an existing user from the database.
 
	:param user: the username of the user
	:type user: str
	:param password: the password of the user
	:type password: str
	:return: bool
	:raises: Exception if the user could not be deleted
	"""
	pwcheck = check_password(user, password)
	if isinstance(pwcheck, Exception):
		raise pwcheck
	if isinstance(pwcheck, bool):
		return bool(pwcheck)
	if isinstance(pwcheck, int):
		user_id = int(pwcheck)
		delete_query = sql.SQL("""DELETE FROM users WHERE id = %s""")
		response = execute_transaction(delete_query, (user_id,), commit=True, fetch=False)
		if isinstance(response, bool):
			return response


def add_organisation(organisationName: str, sessionToken: str):
	"""
	Adds a new organisation to the database.
 
	:param organisationName: Name of the organisation
	:type organisationName: str
	:param sessionToken: Session token of the user adding the organisation
	:type sessionToken: str
	:return: organisation id or error message
	:rtype: Union[int, str]
	"""
	try:
		token: Token = tokenDecode(sessionToken)
		if token is None:
			return None, "Authentication failed."
		userid = token.id
		insert_query = sql.SQL("with a as (INSERT INTO organisations (name) VALUES (%s) returning id) "
							   "INSERT INTO membership (userid,organisationid,authorisation) select (%s),id,0 from a returning organisationid")
		organisation_id = execute_transaction(insert_query, (organisationName, userid), commit=True)
		organisation_id = int(organisation_id[0][0])
		return organisation_id, None

	except IntegrityError:
		return None, "name already exists."

	except Exception as e:
		logger.error("addOrganisation failed because: \n", e)
		return None, f"addOrganisation failed because: \n{e}"


def leave_organisation_transaction(organisationId: int, sessionToken: str):
	"""
	Allows a user to leave an organisation. If the user is the last member, the organisation is deleted.
 
	:param organisationId: ID of the organisation to leave
	:type organisationId: int
	:param sessionToken: Session token of the user leaving the organisation
	:type sessionToken: str
	:return: Tuple indicating success status and an optional error message
	:rtype: Tuple[bool, Union[None, str]]
	"""
	try:
		token: Token = tokenDecode(sessionToken)
		if token is None:
			return False, "Authentication failed."
		userid = token.id

		count_query = sql.SQL("SELECT COUNT(*) FROM membership WHERE userid = (%s) AND organisationid = (%s)")
		count = execute_transaction(count_query, (userid, organisationId,), commit=True)
		count = int(count[0][0])
		if count != 1:
			return False, "You are not in this organisation"

		delete_query = sql.SQL(
			"DELETE FROM membership WHERE userid = (%s) AND organisationid = (%s) returning organisationid")
		execute_transaction(delete_query, (userid, organisationId,), commit=True)

		count_query = sql.SQL("SELECT COUNT(*) FROM membership WHERE organisationid = (%s)")
		count = execute_transaction(count_query, [organisationId], commit=True)
		count = int(count[0][0])
		if count > 0:
			return True, None

		delete_query = sql.SQL("DELETE FROM organisations WHERE id = (%s)")
		execute_transaction(delete_query, [organisationId], commit=True, fetch=False)
		return True, None
	except Exception as e:
		logger.error(f"leaveOrganisation failed because: \n{e}")
		return False, e


@deprecated
def add_user_to_organisation(organisationName: str, sessionToken: str, newUser: str):
	"""
	Add a user to an organisation.
 
	:param organisationName: Name of the organisation
	:type organisationName: str
	:param sessionToken: Session token of the admin user making the change
	:type sessionToken: str
	:param newUser: Username of the user to be added
	:type newUser: str
	:return: organisation id or error message
	:rtype: Union[int, str]
	"""
	try:
		token: Token = tokenDecode(sessionToken)
		userid = token.id

		insert_query = sql.SQL("""WITH addUser AS (
				SELECT id
				FROM users
				WHERE username = (%s)  -- new User string
			),
            ismemberandadmin as (
                SELECT organisationid
                from membership
                WHERE organisationid = (SELECT id FROM organisations WHERE name = (%s)) -- org name string
                and   userid = (%s)  -- user id int
                and   authorisation < (%s) -- is minimum permission
            )
INSERT INTO membership (userid, organisationid)
			SELECT  a.id, m.organisationid
			FROM addUser a, ismemberandadmin m
			returning organisationid""")

		organisation_id = execute_transaction(insert_query,
											  (newUser, organisationName, userid,
											   str(Authorisation.Admin.value)), commit=True)
		if organisation_id is None:
			return None, "you have no privileges in this organisation"

		return int(organisation_id), None

	except IntegrityError:
		return None, "name already exists."

	except Exception as e:
		logger.error(f"addUserToOrganisation failed because: \n{e}")


def add_user_to_organisation_new(organisationId: int, newUser: str, actor_user_id: int):
	"""
	Add a user to an organisation.
	Reworked version without session token.
 
	:param organisationId: ID of the organisation
	:type organisationId: int
	:param newUser: Username of the user to be added
	:type newUser: str
	:return: organisation id or error message
	:rtype: Union[int, str]
	"""
	try:
		query = sql.SQL("""INSERT INTO membership (userid, organisationid, authorisation)
			SELECT u.id, m.organisationid, 10 FROM users u CROSS JOIN membership m
			WHERE u.username = %s AND m.userid = %s AND m.organisationid = %s
			AND m.authorisation IN (0, 1) RETURNING organisationid;""")
		result = execute_transaction(query, (newUser, actor_user_id, organisationId), commit=True)
		if isinstance(result, list) and result:
			return int(result[0][0]), None
		return None, "User does not exist or administrator access is required"
	except IntegrityError:
		return None, "User already in organisation"
	except Exception:
		logger.error("Could not add organization member")
		return None, "Could not add organization member"


@deprecated
def remove_user_from_organisation(organisationName: str, sessionToken: str, userToRemove: str):
	"""
	Remove a user from an organisation.
 
	:param organisationName: Name of the organisation
	:type organisationName: str
	:param sessionToken: Session token of the admin user making the change
	:type sessionToken: str
	:param userToRemove: Username of the user to be removed
	:type userToRemove: str
	:return: None
	"""
	try:
		token: Token = tokenDecode(sessionToken)
		userid = token.id

		delete_query = sql.SQL("""
			DELETE FROM membership
			USING (
				SELECT userid, organisationid 
				FROM membership 
				WHERE organisationid = (SELECT id FROM organisations WHERE name = %s)
			) AS org
			WHERE membership.organisationid = org.organisationid 
				AND membership.userid = (SELECT id FROM users WHERE username = %s)
				AND membership.authorisation >= %s
				AND %s >= %s
		""")

		execute_transaction(delete_query, (organisationName, userToRemove, userid, userid,
										   str(Authorisation.Admin.value), userid),
							commit=True)

	except Exception as e:
		logger.error(f"removeUserFromOrganisation failed because: \n{e}")
  
  
def remove_user_from_organisation_new(organisationId: int, userToRemove: str, actor_user_id: int):
	"""
	Remove a user from an organisation.
	Reworked version without session token.
 
	:param organisationId: ID of the organisation
	:type organisationId: int
	:param userToRemove: Username of the user to be removed
	:type userToRemove: str
	:return: None
	"""
	try:
		query = sql.SQL("""DELETE FROM membership target USING users u, membership actor
			WHERE target.userid = u.id AND u.username = %s
			AND target.organisationid = %s AND actor.organisationid = target.organisationid
			AND actor.userid = %s AND actor.authorisation IN (0, 1)
			AND target.authorisation > actor.authorisation AND target.authorisation IN (1, 10)
			RETURNING target.organisationid;""")
		result = execute_transaction(query, (userToRemove, organisationId, actor_user_id), commit=True)
		if isinstance(result, list) and result:
			return True, None
		return False, "Member not found or insufficient administrator privileges"
	except Exception:
		logger.error("Could not remove organization member")
		return False, "Could not remove organization member"


def adjust_user_authorization(organisationName: str, sessionToken: str, userToAdjust: str, newAuthorisation: int):
	"""
	Adjust the authorization level of a user within an organisation.
 
	:param organisationName: Name of the organisation
	:type organisationName: str
	:param sessionToken: Session token of the admin user making the change
	:type sessionToken: str
	:param userToAdjust: Username of the user whose authorization is to be adjusted
	:type userToAdjust: str
	:param newAuthorisation: New authorization level to be set
	:type newAuthorisation: int
	:return: None
	"""
	try:
		token: Token = tokenDecode(sessionToken)
		author_userid = token.id

		update_query = sql.SQL("""
		            UPDATE membership
		            SET authorisation = %s
		            FROM (
		                SELECT userid, organisationid, authorisation
		                FROM membership 
		                WHERE organisationid = (SELECT id FROM organisations WHERE name = %s)
		            ) AS org
		            WHERE membership.organisationid = org.organisationid 
		                AND membership.userid = (SELECT id FROM users WHERE username = %s)
		                AND org.authorisation >= %s  -- Ensure the admin has higher or equal authorization
		                AND org.authorisation > %s  -- Ensure the admin has higher authorization than Member
		                AND org.authorisation >= %s  -- Ensure the new authorization is not higher than admin's
		        """)

		execute_transaction(update_query, (newAuthorisation, organisationName, userToAdjust,
										   str(Authorisation.Admin.value), str(Authorisation.Member.value),
										   author_userid),
							commit=True)

	except Exception as e:
		logger.error(f"adjUserAuthorisation failed because: \n{e}")


def add_document(name: str, content: Union[str, bytes], organisationId: int, userid: int, base_id: int = None):
	"""
	Add a new document to the database.
 
	:param name: Name of the document
	:type name: str
	:param content: Content of the document (either as a string or bytes)
	:type content: Union[str, bytes]
	:param organisationId: ID of the organisation the document belongs to
	:type organisationId: int
	:param userid: ID of the user adding the document
	:type userid: int
	:param base_id: Optional ID of the document base to associate with the document
	:type base_id: int
	:return: ID of the newly created document and its name, or None if an error occurred
	:rtype: Union[Tuple[int, str], Tuple[None, None]]
	"""
	try:
		if get_organisation_authorisation(userid, organisationId) is None:
			return None, None
		check_query = sql.SQL("SELECT id FROM documents WHERE name = %s AND organisationid = %s;")
		check_result = execute_transaction(check_query, (name, organisationId), commit=True)
		counter = 0
		original_name = name
		while check_result:
			counter += 1
			name = f"{original_name}({counter})"
			check_result = execute_transaction(check_query, (name, organisationId), commit=True)
		if not isinstance(content, (str, bytes)):
			return None, None
		content_column = sql.Identifier("content" if isinstance(content, str) else "content_byte")
		query = sql.SQL("""INSERT INTO documents (name, {content}, organisationid, userid, documentbaseid)
			SELECT %s, %s, %s, %s, %s
			WHERE EXISTS (SELECT 1 FROM membership WHERE userid = %s AND organisationid = %s
			AND authorisation IN (0, 1, 10))
			AND (%s IS NULL OR EXISTS (SELECT 1 FROM document_bases WHERE id = %s AND organisation_id = %s))
			RETURNING id;""").format(content=content_column)
		result = execute_transaction(query, (name, content, organisationId, userid, base_id,
			userid, organisationId, base_id, base_id, organisationId), commit=True)
		if isinstance(result, list) and result:
			return int(result[0][0]), name
	except Exception:
		logger.error("Could not add document")
	return None, None


def add_document_base(name: str, attributes: list[str], orgId: int, documents: list[int], user_id: int):
	"""
	Add a new document base and associate documents with it.
 
	:param name: Name of the document base
	:type name: str
	:param attributes: List of attributes for the document base
	:type attributes: list[str]
	:param orgId: ID of the organisation the document base belongs to
	:type orgId: int
	:param documents: List of document IDs to associate with the document base
	:type documents: list[int]
	:return: ID of the newly created document base or an error code (-400 invalid IDs, -403 forbidden selection, -409 conflict, -500 failure)
	:rtype: int
	"""
	if (not isinstance(documents, list) or
		any(type(document_id) is not int or document_id <= 0 for document_id in documents) or
		len(set(documents)) != len(documents)):
		return -400
	try:
		query = sql.SQL("""WITH selected_documents AS (
			SELECT d.id FROM documents d WHERE d.id = ANY(%s)
			AND d.organisationid = %s AND d.documentbaseid IS NULL FOR UPDATE
		), new_base AS (
			INSERT INTO document_bases (name, attributes, organisation_id)
			SELECT %s, %s, %s WHERE EXISTS (SELECT 1 FROM membership m
			WHERE m.userid = %s AND m.organisationid = %s AND m.authorisation IN (0, 1, 10))
			AND (SELECT count(*) FROM selected_documents) = %s RETURNING id
		), associated AS (
			UPDATE documents d SET documentbaseid = b.id FROM new_base b
			WHERE d.id IN (SELECT id FROM selected_documents) AND d.organisationid = %s
			RETURNING d.id
		) SELECT id FROM new_base;""")
		result = execute_transaction(query, (documents, orgId, name, attributes, orgId,
			user_id, orgId, len(documents), orgId), commit=True)
		if isinstance(result, list) and result:
			return int(result[0][0])
		return -403
	except IntegrityError:
		return -409
	except Exception:
		logger.error("Could not create document base")
		return -500


def delete_document_base_data(base_name: str, organisation_id: int, user_id: int):
	"""
	Delete a document base and disassociate documents from it.
 
	:param base_name: Name of the document base to delete
	:type base_name: str
	:param organisation_id: ID of the organisation the document base belongs to
	:type organisation_id: int
	:return: True if deletion was successful, False otherwise
	:rtype: bool
	"""
	try:
		delete_query = sql.SQL(
			"DELETE FROM document_bases b "
			"WHERE b.name = %s AND b.organisation_id = %s "
			"AND EXISTS (SELECT 1 FROM membership m WHERE m.userid = %s "
			"AND m.organisationid = b.organisation_id AND m.authorisation IN (0, 1)) RETURNING b.id;"
		)
		data = (base_name, organisation_id, user_id)
		result = execute_transaction(delete_query, data, commit=True)
		return isinstance(result, list) and bool(result)

	except Exception as e:
		logger.error(str(e))
		return False

def add_feedback(document_id: int, user_id: int, positive: bool, attribute: str, feedback_start: int = None, feedback_end: int = None, organisation_id: int = None):
	"""
	Add a public feedback for a certain attribute to a document.
 
	:param document_id: ID of the document to which the feedback belongs
	:type document_id: int
	:param user_id: ID of the user providing the feedback
	:type user_id: int
	:param positive: Boolean indicating if the feedback is positive or negative
	:param positive: bool
	:param attribute: The attribute the feedback is about
	:type attribute: str
	:param feedback_start: Optional start index of the feedback in the document
	:type feedback_start: int
	:param feedback_end: Optional end index of the feedback in the document
	:type feedback_end: int
	:return: ID of the newly created feedback entry or error code (-409 for IntegrityError, -500 for other exceptions)
	:rtype: int
	"""
	try:
		insert_data_query = sql.SQL(
			"INSERT INTO document_feedback (documentid, userid, positive, attribute, feedback_start, feedback_end) "
			"SELECT %s, %s, %s, %s, %s, %s WHERE EXISTS (SELECT 1 FROM documents d "
			"JOIN membership m ON m.organisationid = d.organisationid WHERE d.id = %s "
			"AND m.userid = %s AND m.authorisation IN (0, 1, 10) "
			"AND (%s IS NULL OR d.organisationid = %s)) RETURNING id;"
		)
		data = (document_id, user_id, positive, attribute, feedback_start, feedback_end,
			document_id, user_id, organisation_id, organisation_id)
		response = execute_transaction(insert_data_query, data, commit=True)
		if not isinstance(response, list) or not response:
			return -403
		feedback_id = int(response[0][0])
		return feedback_id

	except IntegrityError as i:
		logger.error(str(i))
		return -409
	except Exception as e:
		logger.error(str(e))
		return -500
