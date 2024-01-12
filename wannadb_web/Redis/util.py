import os
from typing import Optional
import logging

import redis

CACHE_HOST = os.environ.get("CACHE_HOST", "127.0.0.1")
CACHE_PORT = int(os.environ.get("CACHE_PORT", 6379))
CACHE_DB = int(os.environ.get("CACHE_DB", 0))
CACHE_PASSWORD = os.environ.get("CACHE_PASSWORD")

logger = logging.getLogger(__name__)

Redis_Connection: Optional["RedisConnection"] = None


def connectRedis():
	try:
		redis_client = redis.Redis(
			host=CACHE_HOST,
			port=CACHE_PORT,
			db=CACHE_DB,
			password=CACHE_PASSWORD,
		)
		return redis_client
	except Exception as e:
		raise Exception("Redis connection failed because:", e)


class RedisConnection:
	def __init__(self) -> None:
		"""Initialize the Redis_Connection manager."""
		global Redis_Connection
		if Redis_Connection is not None:
			logger.error("There can only be one Redis_Connection!")
			raise RuntimeError("There can only be one Redis_Connection!")
		else:
			Redis_Connection = self
			self.redis_client = connectRedis()
			logger.info("Initialized the Redis_Connection.")

	def __enter__(self) -> "RedisConnection":
		"""Enter the Redis_Connection context."""
		logger.info("Entered the Redis_Connection.")
		return self

	def __exit__(self, exc_type, exc_val, exc_tb) -> None:
		"""Exit the Redis_Connection context."""
		logger.info("Kill all Redis connections")
		global Redis_Connection
		if Redis_Connection is None:
			logger.error("Redis_Connection is None!")
			raise RuntimeError("Redis_Connection is None!")
		Redis_Connection.redis_client.close()
		Redis_Connection = None
		logger.info("Exited the resource manager.")
