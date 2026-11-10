import logging
from contextlib import closing
from typing import Union
from deprecated import deprecated

import bcrypt
from psycopg2 import sql, IntegrityError
from wannadb.data.data import Document, DocumentBase, InformationNugget
from wannadb.data.signals import SentenceStartCharsSignal
from wannadb_web.util import Token, Authorisation, tokenDecode
from wannadb_web.postgres.queries import (
	check_password, document_base_snapshot_query, document_base_snapshot_scope, get_organisation_authorisation, get_organisation_id,
)
from wannadb_web.limits import validate_corpus
from wannadb_web.postgres.util import connectPG, execute_transaction

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

	except Exception:
		logger.error("Could not change password")


class OrganisationLifecycleConflict(RuntimeError):
	"""The current organization membership prevents the requested action."""


def _lock_organisation(cursor, organisation_id: int):
	cursor.execute("SELECT id FROM organisations WHERE id = %s FOR NO KEY UPDATE", (organisation_id,))
	if cursor.fetchone() is None:
		raise PermissionError("Organization access denied.")


def _require_replacement_admin(cursor, user_id: int, organisation_ids: list[int]):
	cursor.execute("""SELECT o.name FROM organisations o JOIN membership m ON m.organisationid = o.id
		WHERE m.userid = %s AND m.organisationid = ANY(%s) AND m.authorisation IN (0, 1)
		AND NOT EXISTS (
			SELECT 1 FROM membership other
			WHERE other.organisationid = o.id AND other.userid <> m.userid AND other.authorisation IN (0, 1)
		)
		ORDER BY o.id LIMIT 1""", (user_id, organisation_ids))
	blocked = cursor.fetchone()
	if blocked:
		raise OrganisationLifecycleConflict(
			f'You are the last administrator of “{blocked[0]}”. Transfer ownership or explicitly delete the organization first.'
		)


def delete_user_transaction(user_id: int):
	"""Delete a verified account after locking every organization it belongs to."""
	with closing(connectPG()) as conn, conn, conn.cursor() as cur:
		# Prevent new memberships referencing this account during the check and cascade.
		cur.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
		if cur.fetchone() is None:
			raise PermissionError("Account access denied.")
		# The order is shared by concurrent deletions of accounts with overlapping memberships.
		cur.execute("""SELECT o.id FROM organisations o
			WHERE EXISTS (SELECT 1 FROM membership m WHERE m.organisationid = o.id AND m.userid = %s)
			ORDER BY o.id FOR NO KEY UPDATE""", (user_id,))
		_require_replacement_admin(cur, user_id, [row[0] for row in cur.fetchall()])
		cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


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

	except Exception:
		logger.error("Could not create organization")
		return None, f"addOrganisation failed because: \n{e}"


def leave_organisation_transaction(organisation_id: int, user_id: int):
	"""Remove a membership while retaining the organization and its data."""
	with closing(connectPG()) as conn, conn, conn.cursor() as cur:
		_lock_organisation(cur, organisation_id)
		_require_replacement_admin(cur, user_id, [organisation_id])
		cur.execute("DELETE FROM membership WHERE organisationid = %s AND userid = %s",
			(organisation_id, user_id))
		if cur.rowcount != 1:
			raise PermissionError("Organization access denied.")


def can_manage_organisation_ownership(actor_role, has_owner):
	"""An administrator can recover an older organization without an owner."""
	return actor_role == 0 or (actor_role == 1 and not has_owner)


def _require_organisation_owner(cursor, organisation_id: int, user_id: int, *, allow_recovery=False):
	cursor.execute("""SELECT m.authorisation, EXISTS (
			SELECT 1 FROM membership owner WHERE owner.organisationid = m.organisationid
				AND owner.authorisation = 0
		)
		FROM membership m WHERE m.organisationid = %s AND m.userid = %s""", (organisation_id, user_id))
	role = cursor.fetchone()
	if role is not None and (role[0] == 0 or (allow_recovery and can_manage_organisation_ownership(*role))):
		return
	raise PermissionError("Organization owner access required.")


def transfer_organisation_ownership(organisation_id: int, user_id: int, replacement: str):
	"""Transfer ownership to an existing member and leave the former owner as an administrator."""
	with closing(connectPG()) as conn, conn, conn.cursor() as cur:
		_lock_organisation(cur, organisation_id)
		_require_organisation_owner(cur, organisation_id, user_id, allow_recovery=True)
		cur.execute("""UPDATE membership m SET authorisation = 0 FROM users u
			WHERE m.userid = u.id AND u.username = %s AND m.organisationid = %s
			AND m.userid <> %s AND m.authorisation IN (0, 1, 10)""", (replacement, organisation_id, user_id))
		if cur.rowcount != 1:
			raise OrganisationLifecycleConflict("Choose another existing organization member.")
		cur.execute("UPDATE membership SET authorisation = 1 WHERE organisationid = %s AND userid = %s",
			(organisation_id, user_id))


def delete_organisation_transaction(organisation_id: int, user_id: int):
	"""Delete an organization after explicit confirmation at the API boundary."""
	with closing(connectPG()) as conn, conn, conn.cursor() as cur:
		_lock_organisation(cur, organisation_id)
		_require_organisation_owner(cur, organisation_id, user_id)
		cur.execute("DELETE FROM organisations WHERE id = %s", (organisation_id,))


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

	except Exception:
		logger.error("Could not add organization member")


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
	"""Resolve the legacy name-based request through the owner-only removal."""
	try:
		token = tokenDecode(sessionToken)
		if token is None:
			return
		organisations = get_organisation_id(organisationName)
		if isinstance(organisations, list) and len(organisations) == 1:
			remove_user_from_organisation_new(organisations[0][0], userToRemove, token.id)
	except Exception:
		logger.error("Could not remove organization member")


def remove_user_from_organisation_new(organisationId: int, userToRemove: str, actor_user_id: int):
	"""Allow only an owner to remove a non-owner under the organization lock."""
	with closing(connectPG()) as conn, conn, conn.cursor() as cur:
		_lock_organisation(cur, organisationId)
		cur.execute("""DELETE FROM membership target USING users u, membership actor
			WHERE target.userid = u.id AND u.username = %s
			AND target.organisationid = %s AND actor.organisationid = target.organisationid
			AND actor.userid = %s AND actor.authorisation = 0
			AND target.authorisation IN (1, 10);""",
			(userToRemove, organisationId, actor_user_id))
		if cur.rowcount != 1:
			raise PermissionError("Only an organization owner can remove a non-owner member.")


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

	except Exception:
		logger.error("Could not change organization authorization")


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


def mutate_base_documents(base_name, base_id, organisation_id, user_id, *,
		additions=(), replacement=None, removal=None):
	"""Commit preprocessed documents and their raw rows together against the latest base."""
	with closing(connectPG()) as conn, conn, conn.cursor() as cur:
		# Lock the base before its snapshot. Parallel batches wait only for this short
		# transaction, and each reads the snapshot left by its predecessor.
		cur.execute("""SELECT b.id FROM document_bases b WHERE b.id = %s
			AND b.name = %s AND b.organisation_id = %s
			AND EXISTS (SELECT 1 FROM membership m WHERE m.userid = %s
			AND m.organisationid = b.organisation_id AND m.authorisation IN (0, 1, 10))
			FOR UPDATE;""", (base_id, base_name, organisation_id, user_id))
		if cur.fetchone() is None:
			raise PermissionError("Document base access denied.")

		cur.execute(document_base_snapshot_query(lock=True), (base_name, base_id, organisation_id, user_id))
		snapshots = cur.fetchall()
		if len(snapshots) != 1:
			raise RuntimeError("The document base has no unique saved snapshot.")
		snapshot_id, content_byte = snapshots[0]
		base = DocumentBase.from_bson(bytes(content_byte))

		if additions:
			cur.execute("SELECT name FROM documents WHERE organisationid = %s;", (organisation_id,))
			used_names = {row[0] for row in cur.fetchall()} | {doc.name for doc in base.documents}
			for document in additions:
				name = document.name
				counter = 0
				while name in used_names:
					counter += 1
					name = f"{document.name}({counter})"
				used_names.add(name)

				cur.execute("""INSERT INTO documents (name, content, organisationid, userid, documentbaseid)
					VALUES (%s, %s, %s, %s, %s);""", (name, document.text, organisation_id, user_id, base_id))
				if name != document.name:
					renamed = Document(name, document.text)
					renamed.signals.update(document.signals)
					for nugget in document.nuggets:
						clone = InformationNugget(renamed, nugget.start_char, nugget.end_char)
						clone.signals.update(nugget.signals)
						renamed.nuggets.append(clone)
					document = renamed
				base.documents.append(document)

		if replacement is not None:
			document_id, old_text, document = replacement
			cur.execute("""UPDATE documents SET content = %s WHERE id = %s AND name = %s
				AND organisationid = %s AND documentbaseid = %s AND content = %s RETURNING id;""",
				(document.text, document_id, document.name, organisation_id, base_id, old_text))
			if cur.fetchone() is None:
				raise ValueError("The document changed or was deleted. Reload the base before editing again.")
			if document.text != old_text:
				# These offsets describe the previous text.
				cur.execute("""DELETE FROM document_feedback WHERE documentid = %s
					AND (feedback_start IS NOT NULL OR feedback_end IS NOT NULL);""", (document_id,))
			for index, existing in enumerate(base.documents):
				if existing.name == document.name:
					if existing.text != document.text or SentenceStartCharsSignal.identifier not in existing.signals:
						base.documents[index] = document
					break
			else:
				# Older uploads could write the raw row without saving the snapshot.
				base.documents.append(document)

		if removal is not None:
			document_id, name = removal
			cur.execute("""DELETE FROM documents WHERE id = %s AND name = %s
				AND organisationid = %s AND documentbaseid = %s AND content IS NOT NULL RETURNING id;""",
				(document_id, name, organisation_id, base_id))
			if cur.fetchone() is None:
				raise ValueError("The document was already deleted. Reload the base.")
			base.documents[:] = [doc for doc in base.documents if doc.name != name]

		if additions or replacement is not None:
			validate_corpus(document.text for document in base.documents)
		cur.execute("UPDATE documents SET content_byte = %s WHERE id = %s;",
			(base.to_bson(), snapshot_id))
		if cur.rowcount != 1:
			raise RuntimeError("The document base snapshot could not be updated.")
		cur.execute("UPDATE document_bases SET last_modified = now() WHERE id = %s;", (base_id,))
		if cur.rowcount != 1:
			raise RuntimeError("The document base metadata could not be updated.")
	return base


class DocumentBaseCreationConflict(ValueError):
	pass


def create_document_base_with_snapshot(name: str, attributes: list[str], organisation_id: int,
		expected_docs: list[tuple[int, str, str]], user_id: int, snapshot: bytes) -> tuple[int, int]:
	"""Publish a processed base, its source associations and its snapshot in one commit."""
	document_ids = [document_id for document_id, _, _ in expected_docs]
	if not document_ids or len(document_ids) != len(set(document_ids)):
		raise ValueError("Choose distinct source documents.")
	if not isinstance(snapshot, bytes) or not snapshot:
		raise RuntimeError("The processed snapshot is missing.")

	with closing(connectPG()) as conn, conn, conn.cursor() as cur:
		cur.execute("""SELECT 1 FROM membership WHERE userid = %s AND organisationid = %s
			AND authorisation IN (0, 1, 10) FOR SHARE;""", (user_id, organisation_id))
		if cur.fetchone() is None:
			raise PermissionError("Document base access denied.")

		# Lock source rows in a consistent order. Concurrent workers may preprocess
		# the same inputs, but only one may attach them, and only if text is unchanged.
		cur.execute("""SELECT id, name, content FROM documents
			WHERE id = ANY(%s) AND organisationid = %s AND documentbaseid IS NULL AND content IS NOT NULL
			ORDER BY id FOR UPDATE;""", (document_ids, organisation_id))
		if cur.fetchall() != sorted(expected_docs, key=lambda document: document[0]):
			raise ValueError("The source documents changed or are no longer available.")

		cur.execute("""INSERT INTO document_bases (name, attributes, organisation_id) VALUES (%s, %s, %s)
			ON CONFLICT (name, organisation_id) DO NOTHING RETURNING id;""", (name, attributes, organisation_id))
		new_base = cur.fetchone()
		if new_base is None:
			raise DocumentBaseCreationConflict("A document base with that name already exists.")
		base_id = new_base[0]

		cur.execute("""UPDATE documents SET documentbaseid = %s
			WHERE id = ANY(%s) AND organisationid = %s AND documentbaseid IS NULL AND content IS NOT NULL;""",
			(base_id, document_ids, organisation_id))
		if cur.rowcount != len(document_ids):
			raise RuntimeError("The source documents could not all be attached.")

		cur.execute("""INSERT INTO documents (name, content_byte, organisationid, userid, documentbaseid)
			VALUES (%s, %s, %s, %s, %s) RETURNING id;""", (name, snapshot, organisation_id, user_id, base_id))
		artifact = cur.fetchone()
		if artifact is None:
			raise RuntimeError("The processed snapshot could not be saved.")
		return base_id, artifact[0]


def delete_document_base_data(base_name: str, organisation_id: int, user_id: int):
	"""Delete the authorized base and its linked artifacts, including a unique legacy snapshot."""
	try:
		with closing(connectPG()) as conn, conn, conn.cursor() as cur:
			cur.execute("""SELECT b.id FROM document_bases b WHERE b.name = %s AND b.organisation_id = %s
				AND EXISTS (SELECT 1 FROM membership m WHERE m.userid = %s
					AND m.organisationid = b.organisation_id AND m.authorisation IN (0, 1))
				FOR UPDATE;""", (base_name, organisation_id, user_id))
			base = cur.fetchone()
			if base is None:
				return False
			base_id = base[0]

			legacy_snapshot = sql.SQL("""SELECT min(d.id) FROM document_bases b JOIN documents d ON {scope}
				WHERE b.id = %s AND d.documentbaseid IS NULL HAVING count(*) = 1;""").format(
				scope=document_base_snapshot_scope())
			cur.execute(legacy_snapshot, (base_id,))
			legacy = cur.fetchone()
			if legacy is not None:
				cur.execute("DELETE FROM documents WHERE id = %s;", (legacy[0],))
				if cur.rowcount != 1:
					raise RuntimeError("The legacy document base snapshot could not be removed.")
			cur.execute("DELETE FROM document_bases WHERE id = %s;", (base_id,))
			if cur.rowcount != 1:
				raise RuntimeError("The document base could not be removed.")
			return True
	except Exception:
		logger.error("Could not delete document base")
		return False


def add_feedback(document_id: int, user_id: int, positive: bool, attribute: str, feedback_start: int = None, feedback_end: int = None, organisation_id: int = None, *, expected_content: str = None, base_name: str = None):
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
		# Share-lock the source row through the insert. Editing a document then
		# either invalidates this feedback or makes the old text fail the check.
		insert_data_query = sql.SQL("""INSERT INTO document_feedback
			(documentid, userid, positive, attribute, feedback_start, feedback_end)
			SELECT %s, %s, %s, %s, %s, %s FROM documents d
			WHERE d.id = %s AND d.content IS NOT NULL
			AND (%s IS NULL OR d.organisationid = %s)
			AND (%s IS NULL OR d.content = %s)
			AND (%s IS NULL OR d.documentbaseid = (
				SELECT b.id FROM document_bases b WHERE b.name = %s AND b.organisation_id = d.organisationid
			))
			AND EXISTS (SELECT 1 FROM membership m WHERE m.organisationid = d.organisationid
				AND m.userid = %s AND m.authorisation IN (0, 1, 10))
			FOR SHARE OF d RETURNING id;""")
		data = (document_id, user_id, positive, attribute, feedback_start, feedback_end,
			document_id, organisation_id, organisation_id, expected_content, expected_content, base_name, base_name, user_id)
		response = execute_transaction(insert_data_query, data, commit=True)
		if response is False:
			return -500
		if not isinstance(response, list) or len(response) != 1:
			return -409 if expected_content is not None else -403
		feedback_id = int(response[0][0])
		return feedback_id

	except IntegrityError:
		logger.error("Feedback write conflicted")
		return -409
	except Exception:
		logger.error("Could not save feedback")
		return -500
