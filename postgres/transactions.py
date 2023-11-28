import psycopg2
from psycopg2 import sql
import bcrypt
import jwt
from config import jwtkey, JWTFormat, Authorisation
from postgres.queries import checkPassword

# Replace these values with your own
DB_NAME = "userManagement"
DB_USER = "postgres"
DB_PASSWORD = "0"
DB_HOST = "127.0.0.1"
DB_PORT = "5432"


def connectPG():
	try:
		conn = psycopg2.connect(
			dbname=DB_NAME,
			user=DB_USER,
			password=DB_PASSWORD,
			host=DB_HOST,
			port=DB_PORT)
		return conn
	except Exception as e:
		print("Connection failed because: \n", e)


def execute_query(query, params=None, commit=False):
	conn = None
	cur = None
	try:
		conn = connectPG()
		cur = conn.cursor()

		cur.execute(query, params)

		if commit:
			conn.commit()

	except Exception as e:
		raise Exception(f"Query execution failed for query: {query} \nParams: {params} \nError: {e}")

	finally:
		if conn:
			conn.close()
		if cur:
			cur.close()


def addUser(user: str, password: str):
	try:
		pwBytes = password.encode('utf-8')
		salt = bcrypt.gensalt()
		pwHash = bcrypt.hashpw(pwBytes, salt)

		insert_data_query = sql.SQL("INSERT INTO users (username, password) VALUES (%s, %s);")
		data_to_insert = (user, pwHash)
		execute_query(insert_data_query, data_to_insert, commit=True)


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
		execute_query(update_query, (pwHash, user), commit=True)

	except Exception as e:
		print("changePassword failed because: \n", e)


def deleteUser(user: str, password: str):
	try:
		pwcheck = checkPassword(user, password)
		if not pwcheck:
			raise Exception("wrong password")

		delete_query = sql.SQL("DELETE FROM users WHERE username = %s;")
		execute_query(delete_query, (user,), commit=True)

	except Exception as e:
		print("deleteUser failed because: \n", e)


def addOrganisation(organisationName: str, sessionToken: str):
	try:
		token: JWTFormat = jwt.decode(sessionToken, jwtkey, algorithm="HS256")
		userid = token.id

		insert_query = sql.SQL("with a as (INSERT INTO organisations (name) VALUES (%s) returning id) "
							   "INSERT INTO membership (userid,organisationid) select (%s),id from a")
		execute_query(insert_query, (organisationName, userid), commit=True)


	except Exception as e:
		print("addOrganisation failed because: \n", e)


def addUserToOrganisation(organisationName: str, sessionToken: str, newUser: str):
	try:
		token: JWTFormat = jwt.decode(sessionToken, jwtkey, algorithm="HS256")
		userid = token.id

		# Combine the two queries into a single query
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

		execute_query(insert_query, (organisationName, newUser, userid, userid, str(Authorisation.Admin.value), userid),
					  commit=True)

	except Exception as e:
		print("addUserToOrganisation failed because: \n", e)
