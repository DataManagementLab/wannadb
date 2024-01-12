import sqlite3
from sqlite3 import Error


def create_connection(db_file, user_id):
	""" create a database connection to the SQLite database
		specified by db_file with user-specific identifier
	:param db_file: general database file
	:param user_id: user-specific identifier
	:return: Connection object or None
	"""
	conn = None
	try:
		db_identifier = f"{db_file}_{user_id}"
		conn = sqlite3.connect(db_identifier, check_same_thread=False)
		conn.row_factory = sqlite3.Row
		return conn
	except Error as e:
		print(e)

	return conn


def alter_table(conn, entry):
	if entry["type"] is None:
		entry["type"] = 'text'
	sql = ''' ALTER TABLE {} ADD COLUMN {} {}'''.format(entry["table"], entry["attribute"], entry["type"])
	cur = conn.cursor()
	cur.execute(sql)
	conn.commit()
	return cur.lastrowid
