import bcrypt
from psycopg2 import sql, IntegrityError
from config import Token, Authorisation, tokenDecode
from postgres.queries import checkPassword
from postgres.util import execute_transaction


# WARNING: This is only for development purposes!
def dropTables():
	try:
		drop_table_query = sql.SQL("DROP TABLE IF EXISTS public.users CASCADE;\n"
								   "DROP TABLE IF EXISTS public.documents CASCADE;\n"
								   "DROP TABLE IF EXISTS public.membership CASCADE;\n"
								   "DROP TABLE IF EXISTS public.organisations CASCADE;")
		execute_transaction(drop_table_query, commit=True)
	except Exception as e:
		print("dropTables failed because: \n", e)


def createUserTable():
	try:
		create_table_query = sql.SQL("""CREATE TABLE public.users
(
    id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
    username text COLLATE pg_catalog."default" NOT NULL,
    password bytea NOT NULL,
    CONSTRAINT userid PRIMARY KEY (id),
    CONSTRAINT unique_username UNIQUE (username)
)

TABLESPACE pg_default;
""")
		execute_transaction(create_table_query, commit=True)
	except Exception as e:
		print("createUserTable failed because: \n", e)


def createDocumentsTable():
	try:
		create_table_query = sql.SQL("""CREATE TABLE public.documents
(
    id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
    name text COLLATE pg_catalog."default" NOT NULL,
    content text COLLATE pg_catalog."default" NOT NULL,
    organisationid bigint NOT NULL,
    userid bigint NOT NULL,
    CONSTRAINT dokumentid PRIMARY KEY (id),
    CONSTRAINT documents_organisationid_fkey FOREIGN KEY (organisationid)
        REFERENCES public.organisations (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
        NOT VALID,
    CONSTRAINT documents_userid_fkey FOREIGN KEY (userid)
        REFERENCES public.users (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
        NOT VALID
)

TABLESPACE pg_default;""")
		execute_transaction(create_table_query, commit=True)
	except Exception as e:
		print("createUserTable failed because: \n", e)


def createMembershipTable():
	try:
		create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS public.membership
(
    userid bigint NOT NULL,
    organisationid bigint NOT NULL,
    authorisation bigint NOT NULL DEFAULT 0,
    CONSTRAINT membership_pkey PRIMARY KEY (userid, organisationid),
    CONSTRAINT membership_organisationid_fkey FOREIGN KEY (organisationid)
        REFERENCES public.organisations (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
        NOT VALID,
    CONSTRAINT membership_userid_fkey FOREIGN KEY (userid)
        REFERENCES public.users (id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
        NOT VALID
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.membership
    OWNER to postgres;
-- Index: fki_organisationid

-- DROP INDEX IF EXISTS public.fki_organisationid;

CREATE INDEX IF NOT EXISTS fki_organisationid
    ON public.membership USING btree
    (organisationid ASC NULLS LAST)
    TABLESPACE pg_default;""")
		execute_transaction(create_table_query, commit=True)
	except Exception as e:
		print("createUserTable failed because: \n", e)


def createOrganisationTable():
	try:
		create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS public.organisations
(
    id bigint NOT NULL GENERATED ALWAYS AS IDENTITY ( INCREMENT 1 START 1 MINVALUE 1 MAXVALUE 9223372036854775807 CACHE 1 ),
    name text COLLATE pg_catalog."default" NOT NULL,
    CONSTRAINT organisationid PRIMARY KEY (id),
    CONSTRAINT organisations_name_key UNIQUE (name)
)

TABLESPACE pg_default;

""")
		execute_transaction(create_table_query, commit=True)
	except Exception as e:
		print("createUserTable failed because: \n", e)


def addUser(user: str, password: str):
	try:
		pwBytes = password.encode('utf-8')
		salt = bcrypt.gensalt()
		pwHash = bcrypt.hashpw(pwBytes, salt)
		# Needed this for the correct password check dont know why...
		pwHash = pwHash.decode('utf-8')

		insert_data_query = sql.SQL("INSERT INTO users (username, password) VALUES (%s, %s) returning id;")
		data_to_insert = (user, pwHash)
		response = execute_transaction(insert_data_query, data_to_insert, commit=True)
		return int(response[0][0])

	except Exception as e:
		print("addUser failed because: \n", e)


def changePassword(user: str, old_password: str, new_password: str):
	try:
		if old_password == new_password:
			raise Exception("same password")

		pwcheck = checkPassword(user, old_password)
		if not pwcheck:
			raise Exception("wrong password")

		pwBytes = new_password.encode('utf-8')
		salt = bcrypt.gensalt()
		pwHash = bcrypt.hashpw(pwBytes, salt)

		update_query = sql.SQL("UPDATE users SET password = %s WHERE username = %s;")
		execute_transaction(update_query, (pwHash, user), commit=True)

	except Exception as e:
		print("changePassword failed because: \n", e)


def deleteUser(user: str, password: str):
	try:
		pwcheck = checkPassword(user, password)
		if not pwcheck:
			raise Exception("wrong password")

		delete_query = sql.SQL("DELETE FROM users WHERE username = %s;")
		execute_transaction(delete_query, (user,), commit=True)

	except Exception as e:
		print("deleteUser failed because: \n", e)


def addOrganisation(organisationName: str, sessionToken: str):
	try:
		token: Token = tokenDecode(sessionToken)
		userid = token.id

		insert_query = sql.SQL("with a as (INSERT INTO organisations (name) VALUES (%s) returning id) "
							   "INSERT INTO membership (userid,organisationid) select (%s),id from a returning organisationid")
		organisation_id = execute_transaction(insert_query, (organisationName, userid), commit=True)
		organisation_id = int(organisation_id)
		return organisation_id, None

	except IntegrityError:
		return None, "name already exists."

	except Exception as e:
		print("addOrganisation failed because: \n", e)


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


def addDocument(name: str, content: str, organisationId: int, userid: int):
	try:
		insert_data_query = sql.SQL("INSERT INTO documents (name,content,organisationid,userid) "
									"VALUES (%s, %s,%s, %s) returning id;")
		data_to_insert = (name, content, organisationId, userid)
		response = execute_transaction(insert_data_query, data_to_insert, commit=True)
		return int(response[0][0])

	except Exception as e:
		print("addDocument failed because: \n", e)
