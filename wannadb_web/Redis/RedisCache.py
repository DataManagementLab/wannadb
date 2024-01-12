from typing import Optional
import logging

from wannadb_web.Redis import util

logger = logging.getLogger(__name__)


class RedisCache:
	def __init__(self, user_id: int) -> None:
		"""Initialize the RedisCache instance for a specific user."""
		self.redis_client = util.Redis_Connection.redis_client
		self.user_space_key = f"user:{str(user_id)}"

	def set(self, key: str, value: str) -> None:
		"""Set a key-value pair in the user-specific space."""
		user_key = f"{self.user_space_key}:{key}"
		self.redis_client.set(user_key, value)

	def get(self, key: str) -> Optional[str]:
		"""Get the value associated with a key in the user-specific space."""
		user_key = f"{self.user_space_key}:{key}"
		return self.redis_client.get(user_key)

	def close(self) -> None:
		"""Close the Redis connection for the user-specific space."""
		self
		pass
