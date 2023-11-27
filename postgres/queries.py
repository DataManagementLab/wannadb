import psycopg2
from psycopg2 import sql
import bcrypt

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


def execute_select_query(query, params=None):
	conn = None
	cur = None
	try:
		conn = connectPG()
		cur = conn.cursor()

		cur.execute(query, params)
		result = cur.fetchall()

		return result if result else None

	except Exception as e:
		print(f"Query execution failed for query:\n"
			  f"{query} \n"
			  f"Params: {params} \n"
			  f"Error: {e}")
	finally:
		if conn:
			conn.close()
		if cur:
			cur.close()


def getUserID(user: str):
	select_query = sql.SQL("SELECT id FROM users WHERE username = %s;")
	return execute_select_query(select_query, (user,))


def getOrganisationID(organisation_name: str):
	select_query = sql.SQL("SELECT id FROM organisations WHERE name = %s;")
	return execute_select_query(select_query, (organisation_name,))


def getMemberIDsFromOrganisationID(organisationID: int):
	select_query = sql.SQL("SELECT userid FROM membership WHERE organisationid = %s;")
	return execute_select_query(select_query, (organisationID,))


def getOrganisationIDsFromUserId(userID: int):
	select_query = sql.SQL("SELECT organisationid FROM membership WHERE userid = %s;")
	return execute_select_query(select_query, (userID,))


def checkPassword(user: str, password: str) -> bool:
	select_query = sql.SQL("SELECT password FROM users WHERE username = %s;")
	result = execute_select_query(select_query, (user,))
	try:
		if result[0]:
			stored_password = result[0].tobytes()  # sketchy conversion but works
			return bcrypt.checkpw(password.encode('utf-8'), stored_password)

		return False

	except Exception as e:
		print("checkPassword failed because: \n", e)
		return False


def checkOrganisationAuthorisation(organisationName: str, userName: str) -> int:
	select_query = sql.SQL("SELECT membership from membership "
						   "where userid == (SELECT id from users where username == (%s)) "
						   "and "
						   "organisationid == (Select id from organisations where name == (%s))")

	result = execute_select_query(select_query, (organisationName, userName))
	try:
		if result[0]:
			authorisation = result[0]
			return int(authorisation)  # sketchy conversion but works

	except Exception as e:
		print("checkOrganisationAuthorisation failed because: \n", e)
		return 99
