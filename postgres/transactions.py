import bcrypt
import jwt
from psycopg2 import sql
from config import jwtkey, Token, Authorisation
from postgres.queries import checkPassword
from postgres.util import execute_transaction

# WARNING: This is only for development purposes!
def dropTables():
	try:
		drop_table_query = sql.SQL("""DROP TABLE IF EXISTS users;""")
		execute_transaction(drop_table_query, commit=True)
	except Exception as e:
		print("dropTables failed because: \n", e)


def createUserTable():
	try:
		create_table_query = sql.SQL("""CREATE TABLE IF NOT EXISTS users (
			id SERIAL PRIMARY KEY,
			username VARCHAR(100) UNIQUE NOT NULL,
			password VARCHAR(1000) NOT NULL
		);""")
		execute_transaction(create_table_query, commit=True)
	except Exception as e:
		print("createUserTable failed because: \n", e)

def addUser(user: str, password: str):
	createTables()
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
		token: Token = jwt.decode(sessionToken, jwtkey, algorithm="HS256")
		userid = token.id

		insert_query = sql.SQL("with a as (INSERT INTO organisations (name) VALUES (%s) returning id) "
							   "INSERT INTO membership (userid,organisationid) select (%s),id from a")
		execute_transaction(insert_query, (organisationName, userid), commit=True)

	except Exception as e:
		print("addOrganisation failed because: \n", e)


def addUserToOrganisation(organisationName: str, sessionToken: str, newUser: str):
	try:
		token: Token = jwt.decode(sessionToken, jwtkey, algorithm="HS256")
		userid = token.id

		insert_query = sql.SQL("""
			WITH org AS (
				SELECT userid, organisationid 
				FROM membership 
				WHERE organisationid = (SELECT id FROM organisations WHERE name = %s)
			), user_info AS (
				SELECT id 
				FROM users 
				WHERE username = %s
			)
			INSERT INTO membership (userid, organisationid)
			SELECT %s, org.organisationid 
			FROM org, user_info, membership AS m
			WHERE org.organisationid = m.organisationid 
			AND user_info.id = m.userid 
			AND m.authorisation >= %s 
			AND %s >= %s
		""")

		execute_transaction(insert_query, (organisationName, newUser, userid, userid,
										   str(Authorisation.Admin.value), userid),
							commit=True)

	except Exception as e:
		print("addUserToOrganisation failed because: \n", e)


def removeUserFromOrganisation(organisationName: str, sessionToken: str, userToRemove: str):
	try:
		token: Token = jwt.decode(sessionToken, jwtkey, algorithm="HS256")
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
		token: Token = jwt.decode(sessionToken, jwtkey, algorithm="HS256")
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


def addDocument(name: str, content: str, organisationid: int, userid: int):
	try:
		insert_data_query = sql.SQL("INSERT INTO documents (name,content,organisationid,userid) "
									"VALUES (%s, %s,%s, %s) returning id;")
		data_to_insert = (name, content, organisationid, userid)
		response = execute_transaction(insert_data_query, data_to_insert, commit=True)
		return int(response[0][0])

	except Exception as e:
		print("addDocument failed because: \n", e)
