from typing import Optional, Union
import logging
import json
from contextvars import ContextVar

from wannadb_web.Redis import util

logger = logging.getLogger(__name__)

_signal_scope = ContextVar("signal_scope", default=None)


def set_signal_scope(user_id=None, base_id=None):
	_signal_scope.set((str(user_id), base_id) if base_id is not None else None)


class RedisCache:
	def __init__(self, user_id: str) -> None:
		"""Initialize the RedisCache instance for a specific user."""
		self.redis_client = util.connectRedis()
		self.user_space_key = f"user:{user_id}"
		scope = _signal_scope.get()
		if scope is not None and str(user_id) == scope[0]:
			self.user_space_key += f":base:{scope[1]}"

	def set(self, key: str, value: Union[str, bytes, int, float]) -> None:
		"""Set a key-value pair in the user-specific space."""
		user_key = f"{self.user_space_key}:{key}"
		self.redis_client.set(name=user_key, value=value)

	def sadd(self, key: str, *values: Union[str, bytes, int, float]) -> None:
		"""Set a key-value pair in the user-specific space."""
		user_key = f"{self.user_space_key}:{key}"
		self.redis_client.sadd(name=user_key, value=values)

	def spop(self, key: str) -> Optional[set]:
		"""Set a key-value pair in the user-specific space."""
		user_key = f"{self.user_space_key}:{key}"
		return self.redis_client.smembers(name=user_key)

	def get(self, key: str) -> Optional[Union[str, bytes, int, float]]:
		"""Get the value associated with a key in the user-specific space."""
		user_key = f"{self.user_space_key}:{key}"
		return self.redis_client.get(user_key)

	def delete(self, key: str) -> None:
		"""Delete the key-value pair associated with a key in the user-specific space."""
		user_key = f"{self.user_space_key}:{key}"
		self.redis_client.delete(user_key)

	def delete_user_space(self) -> None:
		"""Delete all entries associated with the user-specific space."""
		user_space_pattern = f"{self.user_space_key}:*"

		# Use SCAN to get all keys matching the pattern
		keys_to_delete = []
		cursor = '0'
		while cursor != 0:
			cursor, keys = self.redis_client.scan(cursor=cursor, match=user_space_pattern)
			keys_to_delete.extend(keys)

		# Delete all keys found
		if keys_to_delete:
			self.redis_client.delete(*keys_to_delete)

	def close(self) -> None:
		"""Close the Redis connection for the user-specific space."""
		self.redis_client.close()
		self.redis_client = None


class TaskAccess:
	"""Keep authorization metadata separate from resettable worker signals."""
	def __init__(self, user_id: int):
		self.cache = RedisCache(f"access:{user_id}")
		self.user_id = user_id

	def _get(self, key):
		value = self.cache.get(key)
		try:
			return json.loads(value) if value is not None else None
		except (ValueError, TypeError):
			return None

	def _set(self, key, scope):
		self.cache.redis_client.set(
			name=f"{self.cache.user_space_key}:{key}", value=json.dumps(scope), ex=86400)

	def register(self, task_id, scope):
		self._set(f"task:{task_id}", scope)

	def task(self, task_id):
		return self._get(f"task:{task_id}")

	def active(self):
		return self._get("active")

	def activate(self, scope):
		self._set("active", scope)

	def permitted(self, scope):
		from wannadb_web.postgres.queries import get_base_id, get_organisation_authorisation
		if not isinstance(scope, dict):
			return False
		if get_organisation_authorisation(self.user_id, scope.get("organisation_id")) is None:
			return False
		base_id = get_base_id(scope.get("base_name"), scope.get("organisation_id"))
		return base_id is not None and base_id == scope.get("base_id")
