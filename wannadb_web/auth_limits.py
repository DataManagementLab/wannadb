from hashlib import sha256

from wannadb_web.Redis.util import connectRedis

WINDOW_SECONDS = 60
REGISTRATIONS_PER_PEER = 15
LOGINS_PER_PEER = 120
LOGINS_PER_USERNAME = 10

_TAKE_ATTEMPT = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
if count >= tonumber(ARGV[1]) then
  return math.max(1, redis.call('TTL', KEYS[1]))
end
if redis.call('INCR', KEYS[1]) == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


def auth_retry_after(scope: str, identity: str, maximum: int) -> int:
	digest = sha256(identity.encode("utf-8")).hexdigest()
	with connectRedis() as redis:
		return redis.eval(_TAKE_ATTEMPT, 1, f"wannadb:auth:{scope}:{digest}", maximum, WINDOW_SECONDS)
