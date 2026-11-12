import logging
import os

import psycopg2
from flask import g, has_request_context
from psycopg2 import extensions, IntegrityError
from psycopg2.sql import SQL

logger = logging.getLogger(__name__)

DB_NAME = os.environ.get("DATABASE_NAME")
DB_USER = os.environ.get("DATABASE_USER")
DB_PASSWORD = os.environ.get("DATABASE_PASSWORD")
DB_HOST = os.environ.get("DATABASE_HOST")
DB_PORT = os.environ.get("DATABASE_PORT")


def connectPG(*, connect_timeout=None):
	"""Connect to PostgreSQL using the configured credentials."""
	return psycopg2.connect(
		dbname=DB_NAME,
		user=DB_USER,
		password=DB_PASSWORD,
		host=DB_HOST,
		port=DB_PORT,
		connect_timeout=connect_timeout)


def _log_failure(operation, error):
	# PostgreSQL error details may contain values as well as the statement.
	request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
	logger.error("PostgreSQL %s failed (%s, SQLSTATE=%s, request_id=%s).",
		operation, type(error).__name__, getattr(error, "pgcode", None) or "unavailable", request_id)


def execute_transaction(query, params=None, commit=False, fetch=True):
	"""Return rows, None for no rows, True when no rows were requested, or False on failure."""
	conn = None
	cur = None
	try:
		conn = connectPG()
		cur = conn.cursor()
		cur.execute(query, params)
		result = cur.fetchall() if fetch and cur.description is not None else None

		if commit:
			conn.commit()
		return (result or None) if fetch else True
	except IntegrityError as error:
		_log_failure("transaction", error)
		# Keep the exception category for callers, without attaching the original details.
		raise type(error)("Database transaction violated an integrity constraint.") from None
	except Exception as error:
		_log_failure("transaction", error)
		return False
	finally:
		if cur is not None:
			cur.close()
		if conn is not None:
			conn.close()


def execute_query(query: SQL, params=None):
	"""Return rows, None for no rows, or False on failure."""
	conn = None
	cur = None
	try:
		conn = connectPG()
		conn.set_isolation_level(extensions.ISOLATION_LEVEL_AUTOCOMMIT)
		cur = conn.cursor()
		cur.execute(query, params)
		return cur.fetchall() or None
	except Exception as error:
		_log_failure("query", error)
		return False
	finally:
		if cur is not None:
			cur.close()
		if conn is not None:
			conn.close()
