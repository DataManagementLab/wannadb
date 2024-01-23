import logging
import os

import redis

CACHE_HOST = os.environ.get("CACHE_HOST", "127.0.0.1")
CACHE_PORT = int(os.environ.get("CACHE_PORT", 6379))
CACHE_DB = int(os.environ.get("CACHE_DB", 0))
CACHE_PASSWORD = int(os.environ.get("CACHE_PASSWORD", 0))

print(CACHE_HOST, CACHE_PORT, CACHE_DB, CACHE_PASSWORD)

logger = logging.getLogger(__name__)


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
