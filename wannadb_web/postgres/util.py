import logging
import os
from sqlite3 import OperationalError

import psycopg2
from psycopg2 import extensions, IntegrityError
from psycopg2.sql import SQL

DB_NAME = os.environ.get("DATABASE_NAME")
DB_USER = os.environ.get("DATABASE_USER")
DB_PASSWORD = os.environ.get("DATABASE_PASSWORD")
DB_HOST = os.environ.get("DATABASE_HOST")
DB_PORT = os.environ.get("DATABASE_PORT")


# DB_NAME = "userManagement"
# DB_USER = "postgres"
# DB_PASSWORD = "0"
# DB_HOST = "127.0.0.1"
# DB_PORT = "5432"


def connectPG():
	"""
	Connect to the PostgreSQL database server

	Returns:
		conn (psycopg2 connection object)

	Raise:
		OperationalError (if connection fails)
	"""

	try:
		conn = psycopg2.connect(
			dbname=DB_NAME,
			user=DB_USER,
			password=DB_PASSWORD,
			host=DB_HOST,
			port=DB_PORT)
		return conn
	except OperationalError as e:
		raise OperationalError("Connection failed because: \n", e)


def execute_transaction(query, params=None, commit=False, fetch=True):
	"""Execute a query and return the result

	Returns:
		list of tuples (if successful),
		None (if no result),
		False (if error)
	Raises:
		i IntegrityError
	"""

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
		logging.error(f"Query execution failed for query:\n"
					  f"{query} \n"
					  f"Params: {params} \n"
					  f"Error: {e}")
		return False
	finally:
		if conn:
			conn.close()
		if cur:
			cur.close()


def execute_query(query: SQL, params=None):
	"""Execute a query and return the result

	Returns:
		list of tuples (if successful),
		None (if no result),
		False (if error)
	Raises:
		None
	"""

	conn = None
	cur = None
	try:
		conn = connectPG()
		conn.set_isolation_level(extensions.ISOLATION_LEVEL_AUTOCOMMIT)
		cur = conn.cursor()

		cur.execute(query, params)
		result = cur.fetchall()
		if not result:
			return None

		return result

	except Exception as e:
		logging.error(f"Query execution failed for query:\n"
					  f"{query} \n"
					  f"Params: {params} \n"
					  f"Error: {e}")
		return False

	finally:
		if conn:
			conn.close()
		if cur:
			cur.close()
