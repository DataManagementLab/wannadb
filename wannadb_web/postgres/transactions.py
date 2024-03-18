import logging
from typing import Union

import bcrypt
from psycopg2 import sql, IntegrityError
from wannadb_web.util import Token, Authorisation, tokenDecode
from wannadb_web.postgres.queries import checkPassword
from wannadb_web.postgres.util import execute_transaction

logger: logging.Logger = logging.getLogger(__name__)


# WARNING: This is only for development purposes!

def createSchema(schema):
	"""
	Returns: None
	"""
	create_schema_query = sql.SQL(f"CREATE SCHEMA IF NOT EXISTS {schema};")
	execute_transaction(create_schema_query, commit=True, fetch=False)
	logger.info(f"Schema {schema} created successfully.")


def dropSchema(schema):
	"""
		Returns: None
	"""
	drop_schema_query = sql.SQL(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")
	execute_transaction(drop_schema_query, commit=True, fetch=False)
	logger.info(f"Schema {schema} dropped successfully.")


def dropTables(schema):
	"""
		Returns: None
	"""
	drop_table_query = sql.SQL(f"DROP TABLE IF EXISTS {schema}.users CASCADE;\n"
							   f"DROP TABLE IF EXISTS {schema}.documents CASCADE;\n"
							   f"DROP TABLE IF EXISTS {schema}.membership CASCADE;\n"
							   f"DROP TABLE IF EXISTS {schema}.organisations CASCADE;")
	execute_transaction(drop_table_query, commit=True)


def createUserTable(schema):
	create_table_query = sql.SQL(f"""CREATE TABLE IF NOT EXISTS {schema}.users
	(
    id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
    username text COLLATE pg_catalog."default" NOT NULL,
    password bytea NOT NULL,
    CONSTRAINT userid PRIMARY KEY (id),
    CONSTRAINT unique_username UNIQUE (username)
	)

	TABLESPACE pg_default;
	""")
	execute_transaction(create_table_query, commit=True, fetch=False)


def createDocumentsTable(schema):
	create_table_query = sql.SQL(f"""CREATE TABLE IF NOT EXISTS  {schema}.documents
	(
		id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
		name text NOT NULL,
		content text ,
		content_byte   bytea,
		organisationid bigint NOT NULL,
		userid bigint NOT NULL,
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
			NOT VALID
	)

	TABLESPACE pg_default;""")
	execute_transaction(create_table_query, commit=True, fetch=False)


def createMembershipTable(schema):
	create_table_query = sql.SQL(f"""CREATE TABLE IF NOT EXISTS {schema}.membership
(
    userid bigint NOT NULL,
    organisationid bigint NOT NULL,
    authorisation bigint NOT NULL DEFAULT 0,
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
    TABLESPACE pg_default;""")
	execute_transaction(create_table_query, commit=True, fetch=False)


def createOrganisationTable(schema):
	create_table_query = sql.SQL(f"""CREATE TABLE IF NOT EXISTS {schema}.organisations
(
    id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
    name text COLLATE pg_catalog."default" NOT NULL,
    CONSTRAINT organisationid PRIMARY KEY (id),
    CONSTRAINT organisations_name_key UNIQUE (name)
)

TABLESPACE pg_default;

""")
	execute_transaction(create_table_query, commit=True, fetch=False)


def addUser(user: str, password: str):
	"""

	Returns: int (user id)

	Raises: Exception

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


def changePassword(user: str, old_password: str, new_password: str):
	try:
		if old_password == new_password:
			return False

		pwcheck = checkPassword(user, old_password)
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
		print("changePassword failed because: \n", e)


def deleteUser(user: str, password: str):
	pwcheck = checkPassword(user, password)
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


def addOrganisation(organisationName: str, sessionToken: str):
	try:
		token: Token = tokenDecode(sessionToken)
		userid = token.id
		insert_query = sql.SQL("with a as (INSERT INTO organisations (name) VALUES (%s) returning id) "
							   "INSERT INTO membership (userid,organisationid) select (%s),id from a returning organisationid")
		organisation_id = execute_transaction(insert_query, (organisationName, userid), commit=True)
		organisation_id = int(organisation_id[0][0])
		return organisation_id, None

	except IntegrityError:
		return None, "name already exists."

	except Exception as e:
		print("addOrganisation failed because: \n", e)


def leaveOrganisation(organisationId: int, sessionToken: str):
	try:
		token: Token = tokenDecode(sessionToken)
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
		print("leaveOrganisation failed because: \n", e)
		return False, e


def addUserToOrganisation(organisationName: str, sessionToken: str, newUser: str):
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
		print("addUserToOrganisation failed because: \n", e)


def addUserToOrganisation2(organisationId: int, newUser: str):
	try:
		select_id_query = sql.SQL("SELECT id FROM users WHERE username = (%s)")
		userid = execute_transaction(select_id_query, (newUser,), commit=True)
		if userid is None:
			return None, "User does not exist"

		insert_query = sql.SQL(
			"INSERT INTO membership (userid, organisationid) VALUES (%s, %s) returning organisationid")
		organisation_id = execute_transaction(insert_query, (userid[0][0], organisationId), commit=True)
		if organisation_id is None:
			return None, "you have no privileges in this organisation"
		return int(organisation_id[0][0]), None
	except IntegrityError:
		return None, "User already in organisation"
	except Exception as e:
		print("addUserToOrganisation2w failed because: \n", e)
		return None, 'Unknown error'


def removeUserFromOrganisation(organisationName: str, sessionToken: str, userToRemove: str):
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
		print("removeUserFromOrganisation failed because: \n", e)


def adjUserAuthorisation(organisationName: str, sessionToken: str, userToAdjust: str, newAuthorisation: int):
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
		print("adjUserAuthorisation failed because: \n", e)


def addDocument(name: str, content: Union[str, bytes], organisationId: int, userid: int):
	try:

		if isinstance(content, str):
			insert_data_query = sql.SQL("INSERT INTO documents (name, content, organisationid, userid) "
										"VALUES (%s, %s, %s, %s) returning id;")
			string_data_to_insert = (name, content, organisationId, userid)
			response = execute_transaction(insert_data_query, string_data_to_insert, commit=True)
			return int(response[0][0])
		elif isinstance(content, bytes):
			insert_data_query = sql.SQL("INSERT INTO documents (name, content_byte, organisationid, userid) "
										"VALUES (%s, %s, %s, %s) returning id;")
			byte_data_to_insert = (name, content, organisationId, userid)
			response = execute_transaction(insert_data_query, byte_data_to_insert, commit=True)
			return int(response[0][0])

	except IntegrityError as i:
		logger.error(str(i))
		return -1

	except Exception as e:
		logger.error(str(e))
