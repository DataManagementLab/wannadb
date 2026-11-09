import logging
from hashlib import sha256
from typing import Optional

from wannadb_parsql.cache_db import SQLiteCacheDB

logger = logging.getLogger(__name__)


def _attribute_table_name(attribute_name: str) -> str:
	"""Keep display names separate from internal tables and SQLite's case folding."""
	return "attribute_" + sha256(attribute_name.encode("utf-8")).hexdigest()


class SQLiteCacheDBWrapper:
	__cache_db: Optional[SQLiteCacheDB]

	def __init__(self, user_id: int, db_file="wannadb_cache.db"):
		"""Initialize the RedisCache instance for a specific user."""
		if db_file == ":memory:":
			self.db_identifier = db_file
		else:
			self.db_identifier = f"{user_id}_{db_file}"
		self.__cache_db = SQLiteCacheDB(db_file=self.db_identifier)
		if self.cache_db.conn is None:
			raise Exception("Cache db could not be initialized")

	@property
	def cache_db(self):
		if self.__cache_db is None:
			raise Exception("Cache db is not initialized")
		return self.__cache_db

	def create_attribute_table(self, attribute_name: str):
		self.cache_db.create_table_by_name(_attribute_table_name(attribute_name))

	def delete_attribute_table(self, attribute_name: str):
		self.cache_db.delete_table(_attribute_table_name(attribute_name))

	def delete(self):
		self.cache_db.conn.close()
		self.__cache_db = None
		self.db_identifier = None

	def reset_cache_db(self):
		logger.debug("Reset cache db")
		if self.__cache_db is not None:
			self.cache_db.conn.close()
			self.__cache_db = None
		self.__cache_db = SQLiteCacheDB(db_file=self.db_identifier)

	def disconnect(self):
		if self.cache_db is None:
			logger.error(f"Cache db {self.db_identifier} already deleted")
			return False
		logger.debug(f"Disconnect {self.db_identifier} from cache db")
		self.cache_db.conn.close()
		return True
