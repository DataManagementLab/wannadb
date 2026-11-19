import os

import redis

CACHE_HOST = os.environ.get("CACHE_HOST", "127.0.0.1")
CACHE_PORT = int(os.environ.get("CACHE_PORT", 6379))
CACHE_DB = int(os.environ.get("CACHE_DB", 0))
# Older deployments use 0 to mean that the cache does not require authentication.
CACHE_PASSWORD = os.environ.get("CACHE_PASSWORD") or None
if CACHE_PASSWORD == "0":
	CACHE_PASSWORD = None


def connectRedis(*, timeout=5, **options):
	return redis.Redis(
		host=CACHE_HOST,
		port=CACHE_PORT,
		db=CACHE_DB,
		password=CACHE_PASSWORD,
		socket_connect_timeout=timeout,
		socket_timeout=timeout,
		**options,
	)
