"""User-scoped SQLite projection wrapper used by the web worker."""
import logging
from hashlib import sha256
from typing import Optional

from wannadb_parsql.cache_db import SQLiteCacheDB

logger = logging.getLogger(__name__)


def _attribute_table_name(attribute_name: str) -> str:
	"""Hash a display attribute name into a stable internal SQLite identifier.

	:param attribute_name: The attribute display name used to select its projection.
	:type attribute_name: str
	:returns: The attribute table name text or identifier.
	:rtype: str
	"""
	return "attribute_" + sha256(attribute_name.encode("utf-8")).hexdigest()


class SQLiteCacheDBWrapper:
	"""User-scoped SQLite projection and internal attribute-table lifecycle."""
	__cache_db: Optional[SQLiteCacheDB]

	def __init__(self, user_id: int, db_file="wannadb_cache.db"):
		"""Open a user-scoped SQLite projection; :memory: remains connection-local.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param db_file: The SQLite path or :memory: sentinel.
		:type db_file: str
		:raises Exception: If required worker state or a dependency is unavailable.
		"""
		if db_file == ":memory:":
			self.db_identifier = db_file
		else:
			self.db_identifier = f"{user_id}_{db_file}"
		self.__cache_db = SQLiteCacheDB(db_file=self.db_identifier)
		if self.cache_db.conn is None:
			raise Exception("Cache db could not be initialized")

	@property
	def cache_db(self):
		"""Return the initialized SQLite projection wrapper or reject closed state.

		:returns: The cache db result.
		:rtype: SQLiteCacheDB
		:raises Exception: If required worker state or a dependency is unavailable.
		"""
		if self.__cache_db is None:
			raise Exception("Cache db is not initialized")
		return self.__cache_db

	def create_attribute_table(self, attribute_name: str):
		"""Create a projection table using a hashed internal attribute identifier.

		:param attribute_name: The attribute display name used to select its projection.
		:type attribute_name: str
		"""
		self.cache_db.create_table_by_name(_attribute_table_name(attribute_name))

	def delete_attribute_table(self, attribute_name: str):
		"""Drop the projection table for the selected display attribute.

		:param attribute_name: The attribute display name used to select its projection.
		:type attribute_name: str
		"""
		self.cache_db.delete_table(_attribute_table_name(attribute_name))

	def delete(self):
		"""Close and clear the current projection reference.
		"""
		self.cache_db.conn.close()
		self.__cache_db = None
		self.db_identifier = None

	def reset_cache_db(self):
		"""Reopen the selected projection after closing its existing connection.
		"""
		logger.debug("Reset cache db")
		if self.__cache_db is not None:
			self.cache_db.conn.close()
			self.__cache_db = None
		self.__cache_db = SQLiteCacheDB(db_file=self.db_identifier)

	def disconnect(self):
		"""Close the current SQLite connection and report success.

		:returns: True when the operation or predicate succeeds; otherwise False.
		:rtype: bool
		"""
		if self.cache_db is None:
			logger.error(f"Cache db {self.db_identifier} already deleted")
			return False
		logger.debug(f"Disconnect {self.db_identifier} from cache db")
		self.cache_db.conn.close()
		return True
