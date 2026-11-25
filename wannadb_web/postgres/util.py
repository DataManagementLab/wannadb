"""PostgreSQL connection pooling, query execution and safe failure reporting."""
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
	"""Connect to PostgreSQL using the configured credentials.

	:param connect_timeout: The database connection establishment limit in seconds.
	:type connect_timeout: int | None
	:returns: The connect pg result.
	:rtype: psycopg2.extensions.connection
	"""
	return psycopg2.connect(
		dbname=DB_NAME,
		user=DB_USER,
		password=DB_PASSWORD,
		host=DB_HOST,
		port=DB_PORT,
		connect_timeout=connect_timeout)


def _log_failure(operation, error):
	# PostgreSQL error details may contain values as well as the statement.
	"""Log operation/error classification without sensitive SQL parameter values.

	:param operation: The operation selector or callable invoked by this helper.
	:type operation: str | Callable[..., object]
	:param error: The failure object or safe error text/code handled here.
	:type error: BaseException | str
	"""
	request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
	logger.error("PostgreSQL %s failed (%s, SQLSTATE=%s, request_id=%s).",
		operation, type(error).__name__, getattr(error, "pgcode", None) or "unavailable", request_id)


def execute_transaction(query, params=None, commit=False, fetch=True):
	"""Return rows, None for no rows, True when no rows were requested, or False on failure.

	:param query: The SQL statement validated by the calling layer.
	:type query: str | psycopg2.sql.Composable
	:param params: Bound SQL parameters; values are not interpolated into SQL text.
	:type params: tuple[object, ...] | dict[str, object]
	:param commit: Whether this helper commits its database changes.
	:type commit: bool
	:param fetch: Whether to fetch and return result rows.
	:type fetch: bool
	:returns: Fetched rows, a statement success flag, or the legacy empty/error sentinel when
	    not raising.
	:rtype: list[tuple[object, ...]] | bool | None
	"""
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
	"""Reuse connections in the HTTP worker; background jobs use their own connection.

	:returns: A database connection and its owning pool, or None when the caller must close the
	    connection directly.
	:rtype: tuple[psycopg2.extensions.connection, ThreadedConnectionPool | None]
	"""
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
	"""Return rows, None for no rows, or False on failure.

	:param query: The SQL statement validated by the calling layer.
	:type query: SQL
	:param params: Bound SQL parameters; values are not interpolated into SQL text.
	:type params: tuple[object, ...] | dict[str, object]
	:returns: Fetched rows, a statement success flag, or the legacy empty/error sentinel when
	    not raising.
	:rtype: list[tuple[object, ...]] | bool | None
	"""
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
