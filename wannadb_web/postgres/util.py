import logging
import os
from threading import Lock

import psycopg2
from flask import g, has_request_context
from psycopg2 import extensions, IntegrityError
from psycopg2.sql import SQL
from psycopg2.pool import PoolError, ThreadedConnectionPool

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


_pool_lock = Lock()
_read_pool = None


def _read_connection():
	"""Reuse connections in the HTTP worker; background jobs use their own connection."""
	global _read_pool
	if not has_request_context():
		return connectPG(), None
	with _pool_lock:
		if _read_pool is None:
			_read_pool = ThreadedConnectionPool(1, 8, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
				host=DB_HOST, port=DB_PORT, connect_timeout=5)
		pool = _read_pool
	try:
		return pool.getconn(), pool
	except PoolError:
		# A full pool must not fail otherwise valid requests.
		return connectPG(connect_timeout=5), None


def execute_query(query: SQL, params=None):
	"""Return rows, None for no rows, or False on failure."""
	conn = pool = None
	discard = False
	try:
		conn, pool = _read_connection()
		conn.set_isolation_level(extensions.ISOLATION_LEVEL_AUTOCOMMIT)
		with conn.cursor() as cur:
			cur.execute(query, params)
			return cur.fetchall() or None
	except Exception as error:
		discard = isinstance(error, (psycopg2.InterfaceError, psycopg2.OperationalError))
		_log_failure("query", error)
		return False
	finally:
		if conn is not None:
			if pool is not None:
				pool.putconn(conn, close=discard)
			else:
				conn.close()
