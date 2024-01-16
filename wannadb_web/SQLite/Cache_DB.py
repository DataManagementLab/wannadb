import logging

from wannadb_parsql.cache_db import SQLiteCacheDB

logger = logging.getLogger(__name__)


class SQLiteCacheDBWrapper:

	def __init__(self, user_id: int, db_file="wannadb_cache.db"):
		"""Initialize the RedisCache instance for a specific user."""
		if db_file == ":memory:":
			self.db_identifier = db_file
		else:
			self.db_identifier = f"{user_id}_{db_file}"
		self.cache_db = SQLiteCacheDB(db_file=self.db_identifier)
		if self.cache_db.conn is None:
			raise Exception("Cache db could not be initialized")

	def delete(self):
		self.cache_db.conn.close()
		self.cache_db = None
		self.db_identifier = None

	def reset_cache_db(self):
		logger.debug("Reset cache db")
		if self.cache_db is not None:
			self.cache_db.conn.close()
			self.cache_db = None
		self.cache_db = SQLiteCacheDB(db_file=self.db_identifier)

	def disconnect(self):
		if self.cache_db is None:
			logger.error(f"Cache db {self.db_identifier} already deleted")
			return False
		logger.debug(f"Disconnect {self.db_identifier} from cache db")
		self.cache_db.conn.close()
		return True
