"""Legacy SQLite connection and statement helpers for web projections."""
import logging
import sqlite3
from sqlite3 import Error

logger = logging.getLogger(__name__)

def create_connection(db_file, user_id):
	"""Open the user-scoped SQLite file or in-memory database.

	:param db_file: general database file
	:type db_file: str
	:param user_id: user-specific identifier
	:type user_id: int
	:returns: Connection object or None
	:rtype: sqlite3.Connection
	"""
	conn = None
	try:
		db_identifier = f"{db_file}_{user_id}"
		conn = sqlite3.connect(db_identifier, check_same_thread=False)
		conn.row_factory = sqlite3.Row
		return conn
	except Error as e:
		logger.error(e)

	return conn


def alter_table(conn, entry):
	"""Execute the supplied SQLite statement and return its last inserted row ID.

	:param conn: The SQLite connection owned by the caller.
	:type conn: sqlite3.Connection
	:param entry: The SQLite statement to execute on the supplied connection.
	:type entry: str
	:returns: The alter table result.
	:rtype: int | None
	"""
	if entry["type"] is None:
		entry["type"] = 'text'
	sql = ''' ALTER TABLE {} ADD COLUMN {} {}'''.format(entry["table"], entry["attribute"], entry["type"])
	cur = conn.cursor()
	cur.execute(sql)
	conn.commit()
	return cur.lastrowid
