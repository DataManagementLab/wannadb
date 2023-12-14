import psycopg2
from psycopg2 import extensions, IntegrityError, sql
from psycopg2.sql import SQL

DB_NAME = "userManagement"
DB_USER = "postgres"
DB_PASSWORD = "0"
DB_HOST = "postgres"
#DB_HOST = "127.0.0.1"
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
		raise Exception("Connection failed because: \n", e)


def execute_transaction(query, params=None, commit=False ,fetch=True):
	conn = None
	cur = None
	try:
		conn = connectPG()
		cur = conn.cursor()

		cur.execute(query, params)

		if commit:
			conn.commit()

		if fetch:
			result = cur.fetchall()
			return result if result else None
		return True

	except IntegrityError as e:
		raise IntegrityError(f"Query execution failed for transaction: {query} \nParams: {params} \nError: {e}")

	except Exception as e:
		raise Exception(f"Query execution failed for transaction: {query} \nParams: {params} \nError: {e}")

	finally:
		if conn:
			conn.close()
		if cur:
			cur.close()
		return False


def execute_query(query: SQL, params=None):
	conn = None
	cur = None
	try:
		conn = connectPG()
		conn.set_isolation_level(extensions.ISOLATION_LEVEL_AUTOCOMMIT)
		cur = conn.cursor()

		cur.execute(query, params)
		result = cur.fetchall()

		return result if result else None

	except Exception as e:
		raise Exception(f"Query execution failed for query:\n"
						f"{query} \n"
						f"Params: {params} \n"
						f"Error: {e}")
	finally:
		if conn:
			conn.close()
		if cur:
			cur.close()
