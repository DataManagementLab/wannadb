from typing import Optional, Union
import logging
import json
from contextvars import ContextVar

from wannadb_web.Redis import util
from wannadb_web.limits import QueueFullError

logger = logging.getLogger(__name__)

_signal_scope = ContextVar("signal_scope", default=None)


def set_signal_scope(user_id=None, base_id=None, session_id=None, command_id=None, expected_version=None):
	if base_id is None or session_id is None:
		_signal_scope.set(None)
		return
	_signal_scope.set({"user_id": str(user_id), "base_id": base_id, "session_id": session_id,
		"command_id": command_id, "expected_version": expected_version})


def get_signal_scope():
	return _signal_scope.get()


class RedisCache:
	def __init__(self, user_id: str) -> None:
		"""Initialize the RedisCache instance for a specific user."""
		self.redis_client = util.connectRedis()
		self.user_space_key = f"user:{user_id}"
		scope = _signal_scope.get()
		if scope is not None and str(user_id) == scope["user_id"]:
			self.user_space_key += f':base:{scope["base_id"]}:session:{scope["session_id"]}'

	def set(self, key: str, value: Union[str, bytes, int, float]) -> None:
		"""Set a key-value pair in the user-specific space."""
		user_key = f"{self.user_space_key}:{key}"
		self.redis_client.set(name=user_key, value=value, ex=86400)

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


class TaskAdmission:
	"""Bound the number of waiting and running tasks in each worker queue."""
	def __init__(self, queue: str, user_id: int, task_id: str):
		self.redis = util.connectRedis()
		self.key = f"wannadb:task-admission:{queue}"
		self.member = f"{user_id}:{task_id}"

	def reserve(self, maximum: int, seconds: int) -> bool:
		script = """
local now = tonumber(redis.call('TIME')[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tostring(now))
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then return 0 end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then return -1 end
local seconds = tonumber(ARGV[3])
redis.call('ZADD', KEYS[1], tostring(now + seconds), ARGV[1])
if redis.call('TTL', KEYS[1]) < seconds then
  redis.call('EXPIRE', KEYS[1], ARGV[3])
end
return 1
"""
		result = self.redis.eval(script, 1, self.key, self.member, maximum, seconds)
		if result == -1:
			raise QueueFullError("The worker queue is full.")
		return result == 1

	def release(self):
		try:
			self.redis.zrem(self.key, self.member)
		except Exception as error:
			logger.warning("Task admission release failed. error_type=%s", type(error).__name__)


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
		key = f"{self.cache.user_space_key}:task:{task_id}"
		encoded = json.dumps(scope, sort_keys=True, separators=(",", ":"))
		result = self.cache.redis_client.eval("local old=redis.call('GET',KEYS[1]); if old then if old~=ARGV[1] then return -1 end; return 0 end; redis.call('SET',KEYS[1],ARGV[1],'EX',86400); return 1", 1, key, encoded)
		if result == -1:
			raise ValueError("Task ID belongs to different request parameters")

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
		if scope.get("creation") is True:
			return scope.get("base_id") == 0 and scope.get("interactive") is False
		base_id = get_base_id(scope.get("base_name"), scope.get("organisation_id"))
		return base_id is not None and base_id == scope.get("base_id")


class SessionState:
	"""Session-scoped publications and FIFO commands, committed atomically in Redis."""
	TTL = 86400
	SIGNALS = ("feedback", "error", "status", "finished", "document_base_to_ui", "statistics_to_ui",
		"feedback_request_to_ui", "cache_db_to_ui", "ordert_nuggets")

	def __init__(self, user_id, base_id, session_id):
		if base_id is None or not isinstance(session_id, str) or not session_id:
			raise ValueError("A base and session are required")
		self.user_id = user_id
		self.base_id = base_id
		self.session_id = session_id
		self.cache = RedisCache(f"{user_id}:base:{base_id}:session:{session_id}")
		self.redis = self.cache.redis_client
		self.prefix = self.cache.user_space_key

	@classmethod
	def current(cls, user_id):
		scope = get_signal_scope()
		if scope is None or scope["user_id"] != str(user_id):
			raise ValueError("No task session is selected")
		return cls(user_id, scope["base_id"], scope["session_id"])

	def _keys(self):
		return [f"{self.prefix}:{name}" for name in (
			"publication", "document_base_to_ui", "feedback_request_to_ui", "published_document", "published_feedback",
			"commands", "command_queue", "command_processing")]

	def _empty(self):
		return {"session_id": self.session_id, "version": 0, "phase": "loading", "attribute": None,
			"closed": False, "error": None}

	def claim_execution(self, execution_id):
		return bool(self.redis.set(f"{self.prefix}:execution", execution_id, nx=True, ex=self.TTL))

	def initialize(self):
		self.redis.set(self._keys()[0], json.dumps(self._empty()), nx=True, ex=self.TTL)
		return self.metadata()

	def metadata(self):
		value = self.redis.get(self._keys()[0])
		return json.loads(value) if value is not None else self._empty()

	def command(self, command_id):
		value = self.redis.hget(self._keys()[5], command_id)
		return json.loads(value) if value is not None else None

	def reject(self, command_id, error):
		script = r'''
local raw=redis.call('HGET',KEYS[6],ARGV[1]); if not raw then return nil end
local record=cjson.decode(raw)
if record.state~='published' and record.state~='rejected' then
 record.state='rejected';record.error=ARGV[2]
 redis.call('HSET',KEYS[6],ARGV[1],cjson.encode(record));redis.call('EXPIRE',KEYS[6],ARGV[3])
 redis.call('LREM',KEYS[7],0,ARGV[1]);redis.call('LREM',KEYS[8],0,ARGV[1])
end
return cjson.encode(record)
'''
		value = self.redis.eval(script, 8, *self._keys(), command_id, str(error), self.TTL)
		return json.loads(value) if value is not None else None

	def enqueue(self, command_id, expected_version, payload):
		if not isinstance(command_id, str) or not command_id or len(command_id) > 200:
			raise ValueError("A command ID is required")
		if type(expected_version) is not int or expected_version < 1 or not isinstance(payload, dict):
			raise ValueError("A command requires its published version and payload")
		canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
		script = r'''
local existing = redis.call('HGET', KEYS[6], ARGV[1])
if existing then
 local record = cjson.decode(existing)
 if record.fingerprint ~= ARGV[3] or record.expected_version ~= tonumber(ARGV[2]) then
  return cjson.encode({command_id=ARGV[1],state='rejected',error='COMMAND_ID_REUSED',expected_version=tonumber(ARGV[2])})
 end
 return existing
end
local record = {command_id=ARGV[1],expected_version=tonumber(ARGV[2]),fingerprint=ARGV[3],payload=cjson.decode(ARGV[3]),state='accepted'}
local raw = redis.call('GET',KEYS[1])
local publication = raw and cjson.decode(raw) or nil
local message = record.payload.message
local controls = message=='reload-document-base' or message=='stop-interactive-matching'
local allowed = publication and ((publication.phase=='selection' and (message=='start-ranking' or message=='skip-ranking' or controls)) or
 (publication.phase=='ranking' and (message=='custom-match' or message=='is-match' or message=='no-match-in-document' or message=='multi-match' or controls)))
if not publication or publication.closed then record.state='rejected'; record.error='SESSION_CLOSED'
elseif publication.version ~= record.expected_version then record.state='rejected'; record.error='STALE_VERSION'
elseif not allowed then record.state='rejected'; record.error='INVALID_PHASE'
elseif (message=='start-ranking' or message=='skip-ranking') and publication.attribute~=record.payload.attribute then
 record.state='rejected'; record.error='WRONG_ATTRIBUTE'
else redis.call('RPUSH',KEYS[7],ARGV[1]); redis.call('EXPIRE',KEYS[7],ARGV[4]) end
local encoded = cjson.encode(record)
redis.call('HSET',KEYS[6],ARGV[1],encoded); redis.call('EXPIRE',KEYS[6],ARGV[4])
return encoded
'''
		return json.loads(self.redis.eval(script, 8, *self._keys(), command_id, expected_version, canonical, self.TTL))

	def claim(self):
		script = r'''
local raw = redis.call('GET',KEYS[1])
local publication = raw and cjson.decode(raw) or nil
while true do
 local command_id = redis.call('LPOP',KEYS[7])
 if not command_id then return nil end
 local raw_command = redis.call('HGET',KEYS[6],command_id)
 if raw_command then
  local record = cjson.decode(raw_command)
  if record.state=='accepted' then
   local message=record.payload.message
   local controls=message=='reload-document-base' or message=='stop-interactive-matching'
   local allowed=publication and ((publication.phase=='selection' and (message=='start-ranking' or message=='skip-ranking' or controls)) or
    (publication.phase=='ranking' and (message=='custom-match' or message=='is-match' or message=='no-match-in-document' or message=='multi-match' or controls)))
   if not publication or publication.closed then record.state='rejected'; record.error='SESSION_CLOSED'
   elseif publication.version ~= record.expected_version then record.state='rejected'; record.error='STALE_VERSION'
   elseif not allowed then record.state='rejected'; record.error='INVALID_PHASE'
   elseif (message=='start-ranking' or message=='skip-ranking') and publication.attribute~=record.payload.attribute then
    record.state='rejected'; record.error='WRONG_ATTRIBUTE'
   else
    record.state='consumed'; record.consumed_version=publication.version
    publication.phase='processing';redis.call('SET',KEYS[1],cjson.encode(publication),'EX',ARGV[1])
    redis.call('RPUSH',KEYS[8],command_id); redis.call('EXPIRE',KEYS[8],ARGV[1])
    local encoded=cjson.encode(record)
    redis.call('HSET',KEYS[6],command_id,encoded); redis.call('EXPIRE',KEYS[6],ARGV[1])
    return encoded
   end
   redis.call('HSET',KEYS[6],command_id,cjson.encode(record)); redis.call('EXPIRE',KEYS[6],ARGV[1])
  end
 end
end
'''
		value = self.redis.eval(script, 8, *self._keys(), self.TTL)
		return json.loads(value) if value is not None else None

	def publish(self, phase, attribute=None, command_id=None):
		return self._publish(phase, attribute, command_id, False, None)

	def close(self, error=None, command_id=None):
		return self._publish("failed" if error else "finished", None, command_id, True, error)

	def _publish(self, phase, attribute, command_id, closed, error):
		script = r'''
local prior = redis.call('GET',KEYS[1])
local publication = prior and cjson.decode(prior) or {version=0}
if publication.closed then return publication.version end
publication = {session_id=ARGV[1],version=publication.version+1,phase=ARGV[2],attribute=cjson.decode(ARGV[3]),closed=ARGV[5]=='1',error=cjson.decode(ARGV[6])}
if publication.error == cjson.null then
 for i=2,3 do
  local payload=redis.call('GET',KEYS[i])
  if payload then redis.call('SET',KEYS[i+2],payload,'EX',ARGV[7]) else redis.call('DEL',KEYS[i+2]) end
 end
end
if ARGV[4] ~= '' then
 local raw=redis.call('HGET',KEYS[6],ARGV[4])
 if raw then
  local record=cjson.decode(raw)
  if record.state=='consumed' then
   if publication.error ~= cjson.null then record.state='rejected';record.error=publication.error
   else record.state='published';record.published_version=publication.version end
   redis.call('HSET',KEYS[6],ARGV[4],cjson.encode(record));redis.call('EXPIRE',KEYS[6],ARGV[7])
   redis.call('LREM',KEYS[8],0,ARGV[4])
  end
 end
end
if publication.closed then
 local commands=redis.call('HGETALL',KEYS[6])
 for i=1,#commands,2 do
  local record=cjson.decode(commands[i+1])
  if record.state=='accepted' or record.state=='consumed' then
   record.state='rejected';record.error=publication.error ~= cjson.null and publication.error or 'SESSION_CLOSED'
   redis.call('HSET',KEYS[6],commands[i],cjson.encode(record))
  end
 end
 redis.call('DEL',KEYS[7],KEYS[8]);redis.call('EXPIRE',KEYS[6],ARGV[7])
end
redis.call('SET',KEYS[1],cjson.encode(publication),'EX',ARGV[7])
return publication.version
'''
		return int(self.redis.eval(script, 8, *self._keys(), self.session_id, phase,
			json.dumps(attribute), command_id or "", "1" if closed else "0", json.dumps(error), self.TTL))

	def snapshot(self, include_payload=True, include_feedback=True):
		keys = self._keys()
		names = [name for name in self.SIGNALS if name not in ("document_base_to_ui", "feedback_request_to_ui")
			and (include_payload or name not in ("cache_db_to_ui", "ordert_nuggets"))]
		read_keys = [keys[0]] + [f"{self.prefix}:{name}" for name in names]
		if include_payload:
			names.append("document_base_to_ui"); read_keys.append(keys[3])
		if include_feedback:
			names.append("feedback_request_to_ui"); read_keys.append(keys[4])
		values = self.redis.eval("return redis.call('MGET',unpack(KEYS))", len(read_keys), *read_keys)
		publication = json.loads(values[0]) if values[0] is not None else self._empty()
		result = dict(zip(names, values[1:]))
		result["publication"] = publication
		return result
