from typing import Optional, Union
import logging
import json
import time
from hashlib import sha256
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
	"""Track queue and running deadlines independently of the Celery result."""
	_SCRIPT = """
local queue, user, job, access = unpack(KEYS)
local operation, member = ARGV[1], ARGV[2]
local state = redis.call('GET', job)
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000

local function admit(next_state, seconds)
  local deadline_ms = math.floor(now * 1000) + seconds * 1000
  for _, key in ipairs({queue, user}) do
    redis.call('ZADD', key, deadline_ms / 1000, member)
    if redis.call('TTL', key) < seconds + 60 then
      redis.call('EXPIRE', key, seconds + 60)
    end
  end
  redis.call('SET', job, next_state, 'EX', 86400)
  return deadline_ms
end

local function finish(next_state)
  redis.call('ZREM', queue, member)
  redis.call('ZREM', user, member)
  redis.call('SET', job, next_state, 'EX', 86400)
  return next_state
end

if operation == 'reserve' then
  local scope = redis.call('GET', access)
  if scope then
    if scope ~= ARGV[3] then return -3 end
    return 0
  end
  if state then return -3 end
  redis.call('ZREMRANGEBYSCORE', queue, '-inf', now)
  redis.call('ZREMRANGEBYSCORE', user, '-inf', now)
  if redis.call('ZCARD', user) >= tonumber(ARGV[5]) then return -2 end
  if redis.call('ZCARD', queue) >= tonumber(ARGV[4]) then return -1 end
  local deadline = admit('QUEUED', tonumber(ARGV[6]))
  redis.call('SET', access, ARGV[3], 'EX', 86400)
  return deadline
end

if operation == 'legacy_release' then
  if not state then redis.call('ZREM', queue, member) end
  return
end

local active = state == 'QUEUED' or state == 'STARTED'
if operation == 'finish' then
  if active and (ARGV[4] == '' or state == ARGV[4]) then return finish(ARGV[3]) end
  return
end

local broker = ARGV[3]
if active and operation == 'status' and broker == 'SUCCESS' then return finish(broker) end
if active then
  local deadline = redis.call('ZSCORE', queue, member)
  if not deadline or tonumber(deadline) <= now then
    state = finish(state == 'QUEUED' and 'EXPIRED' or 'FAILURE')
  end
end
if operation == 'start' then
  if state ~= 'QUEUED' then return 0 end
  return admit('STARTED', tonumber(ARGV[3]))
end

if state == 'QUEUED' or state == 'STARTED' then
  if broker == 'FAILURE' or (state == 'QUEUED' and broker == 'REVOKED') then
    return finish(broker)
  end
  if broker == 'PENDING' or broker == 'REVOKED' then return state end
elseif state and state ~= 'SUCCESS' then
  if broker ~= 'SUCCESS' then return state end
end
return broker
"""

	def __init__(self, queue: str, user_id: int, task_id: str):
		self.key = f"wannadb:task-admission:{queue}"
		self.user_key = f"{self.key}:user:{user_id}"
		self.member = f"{user_id}:{task_id}"
		self.job_key = f"{self.key}:job:{self.member}"
		self.access_key = TaskAccess.task_key(user_id, task_id)

	def _execute(self, operation, *args):
		with util.connectRedis() as redis:
			return redis.eval(self._SCRIPT, 4, self.key, self.user_key, self.job_key, self.access_key,
				operation, self.member, *args)

	def reserve(self, scope, maximum: int, per_user: int, queue_seconds: int) -> int:
		encoded = json.dumps(scope, sort_keys=True, separators=(",", ":"))
		result = self._execute("reserve", encoded, maximum, per_user, queue_seconds)
		if result == -1:
			raise QueueFullError("The worker queue is full. Try again shortly.")
		if result == -2:
			raise QueueFullError("You have too many queued or running tasks. Wait for one to finish and try again.")
		if result == -3:
			raise ValueError("Task ID belongs to different request parameters")
		return result

	def start(self, running_seconds: int) -> bool:
		return bool(self._execute("start", running_seconds))

	def status(self, broker_status: str) -> str:
		return self._execute("status", broker_status).decode()

	def finish(self, status: str, *, expected_state: str = "", legacy: bool = False):
		try:
			if legacy:
				self._execute("legacy_release")
			else:
				self._execute("finish", status, expected_state)
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

	@staticmethod
	def task_key(user_id, task_id):
		return f"user:access:{user_id}:task:{task_id}"

	def register(self, task_id, scope):
		key = self.task_key(self.user_id, task_id)
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
	"""Session publications and fenced command steps cached in Redis."""
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
			"commands")]

	def _empty(self):
		return {"session_id": self.session_id, "version": 0, "phase": "loading", "attribute": None,
			"closed": False, "error": None}

	def claim_execution(self, execution_id):
		return bool(self.redis.set(f"{self.prefix}:execution", execution_id, nx=True, ex=self.TTL))

	def initialize(self):
		self.redis.set(self._keys()[0], json.dumps(self._empty()), nx=True, ex=self.TTL)
		return self.metadata()

	@staticmethod
	def _visible_publication(publication):
		if publication.get("phase") == "processing" and publication.get("lease_until", float("inf")) <= time.time():
			publication["phase"] = publication["waiting_phase"]
		for key in ("lease", "waiting_phase", "lease_until", "processing_command"):
			publication.pop(key, None)
		return publication

	def metadata(self):
		value = self.redis.get(self._keys()[0])
		return self._visible_publication(json.loads(value)) if value is not None else self._empty()

	def command(self, command_id):
		value = self.redis.hget(self._keys()[5], command_id)
		if value is None:
			return None
		record = json.loads(value)
		if record["state"] == "consumed" and record.get("lease_until", float("inf")) <= time.time():
			record.update(state="rejected", error="Feedback processing expired. Try the action again.")
		return record

	def begin_step(self, command_id, expected_version, payload, lease, lease_seconds):
		"""Admit this exact command once and fence publication to its processing lease."""
		fingerprint = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
		script = r'''
local command_id, expected_version, fingerprint, lease = ARGV[1], tonumber(ARGV[2]), ARGV[3], ARGV[4]
local now = tonumber(redis.call('TIME')[1])
local raw_command = redis.call('HGET', KEYS[6], command_id)
local existing = raw_command and cjson.decode(raw_command) or nil
if existing then
 if existing.fingerprint ~= fingerprint or existing.expected_version ~= expected_version then
  return cjson.encode({state='rejected', error='This command ID belongs to a different request.'})
 end
 if existing.state~='consumed' or not existing.lease_until or existing.lease_until>now then return raw_command end
end
local raw = redis.call('GET', KEYS[1])
local publication = raw and cjson.decode(raw) or nil
if publication and publication.phase=='processing' and publication.lease_until and publication.lease_until<=now then
 local expired_id = publication.processing_command
 if expired_id~=command_id then
  local old = redis.call('HGET', KEYS[6], expired_id)
  if old then
   local expired = cjson.decode(old)
   expired.state='rejected';expired.error='Feedback processing expired. Try the action again.'
   redis.call('HSET',KEYS[6],expired_id,cjson.encode(expired))
  end
 end
 publication.phase=publication.waiting_phase
end
local message, attribute = ARGV[7], ARGV[8]
local controls = message=='reload-document-base' or message=='stop-interactive-matching'
local select_attribute = message=='start-ranking' or message=='skip-ranking'
local rank = message=='custom-match' or message=='is-match' or message=='no-match-in-document' or message=='multi-match'
local error_message = nil
if not publication or publication.closed then error_message='This feedback session has closed.'
elseif publication.version~=expected_version then error_message='Feedback has changed. Reload the current session.'
elseif not ((publication.phase=='selection' and (select_attribute or controls)) or
             (publication.phase=='ranking' and (rank or controls))) then
 error_message='The session is not waiting for this action.'
elseif select_attribute and publication.attribute~=attribute then
 error_message='This session is waiting for a different attribute.'
end
local record = {command_id=command_id, expected_version=expected_version, fingerprint=fingerprint}
if error_message then
 record.state='rejected';record.error=error_message
else
 record.state='consumed';record.consumed_version=expected_version
 record.lease=lease;record.lease_until=now+tonumber(ARGV[5])
 publication.waiting_phase=publication.phase;publication.phase='processing'
 publication.lease=lease;publication.lease_until=record.lease_until;publication.processing_command=command_id
 redis.call('SET',KEYS[1],cjson.encode(publication),'EX',ARGV[6])
end
local encoded = cjson.encode(record)
redis.call('HSET',KEYS[6],command_id,encoded);redis.call('EXPIRE',KEYS[6],ARGV[6])
return encoded
'''
		return json.loads(self.redis.eval(script, 6, *self._keys(), command_id, expected_version,
			fingerprint, lease, lease_seconds, self.TTL, payload["message"], payload.get("attribute", "")))

	def fail_step(self, command_id, lease, error):
		"""Release an uncommitted step's lease without closing the waiting session."""
		script = r'''
local raw = redis.call('GET',KEYS[1]); if not raw then return 0 end
local publication = cjson.decode(raw)
if publication.phase~='processing' or publication.processing_command~=ARGV[1] or publication.lease~=ARGV[2] then
 return 0
end
local raw_command=redis.call('HGET',KEYS[6],ARGV[1])
if raw_command then
 local record=cjson.decode(raw_command)
 record.state='rejected';record.error=ARGV[3]
 redis.call('HSET',KEYS[6],ARGV[1],cjson.encode(record));redis.call('EXPIRE',KEYS[6],ARGV[4])
end
publication.phase=publication.waiting_phase
publication.waiting_phase=nil;publication.lease=nil;publication.lease_until=nil;publication.processing_command=nil
redis.call('SET',KEYS[1],cjson.encode(publication),'EX',ARGV[4])
return 1
'''
		return bool(self.redis.eval(script, 6, *self._keys(), command_id, lease, error, self.TTL))

	def publish_step(self, version, phase, attribute, document, feedback, *, command_id=None, lease=None,
			propagation_limited=False):
		"""Publish the committed checkpoint's payload only from its owning step."""
		script = r'''
local raw = redis.call('GET', KEYS[1]); if not raw then return 0 end
local publication = cjson.decode(raw)
local version, phase = tonumber(ARGV[1]), ARGV[2]
if publication.closed or publication.version~=version-1 then return 0 end
local command_id=ARGV[4]
if command_id~='' then
 if publication.phase~='processing' or publication.processing_command~=command_id or publication.lease~=ARGV[5] then
  return 0
 end
 local raw_command=redis.call('HGET',KEYS[6],command_id)
 if not raw_command then return 0 end
 local record=cjson.decode(raw_command)
 record.state='published';record.published_version=version
 if ARGV[9]=='1' then record.propagation_limited=true end
 redis.call('HSET',KEYS[6],command_id,cjson.encode(record));redis.call('EXPIRE',KEYS[6],ARGV[8])
elseif publication.phase~='loading' then return 0 end
redis.call('SET',KEYS[4],ARGV[6],'EX',ARGV[8])
if ARGV[7]~='' then redis.call('SET',KEYS[5],ARGV[7],'EX',ARGV[8]) else redis.call('DEL',KEYS[5]) end
publication={session_id=publication.session_id,version=version,phase=phase,
 attribute=cjson.decode(ARGV[3]),closed=phase=='finished',error=cjson.null}
redis.call('SET',KEYS[1],cjson.encode(publication),'EX',ARGV[8])
return 1
'''
		return bool(self.redis.eval(script, 6, *self._keys(), version, phase, json.dumps(attribute),
			command_id or "", lease or "", document, feedback or "", self.TTL, int(propagation_limited)))

	def close(self, error=None):
		"""Close a one-off task, promoting its staged payload on success."""
		script = r'''
local raw = redis.call('GET',KEYS[1])
local prior = raw and cjson.decode(raw) or {version=0}
if prior.closed then return prior.version end
local error_message = cjson.decode(ARGV[2])
if error_message==cjson.null then
 for i=2,3 do
  local payload=redis.call('GET',KEYS[i])
  if payload then redis.call('SET',KEYS[i+2],payload,'EX',ARGV[3]) else redis.call('DEL',KEYS[i+2]) end
 end
end
local publication = {session_id=ARGV[1],version=prior.version+1,
 phase=error_message==cjson.null and 'finished' or 'failed',
 attribute=cjson.null,closed=true,error=error_message}
redis.call('SET',KEYS[1],cjson.encode(publication),'EX',ARGV[3])
return publication.version
'''
		return int(self.redis.eval(script, 6, *self._keys(), self.session_id, json.dumps(error), self.TTL))

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
		publication = self._visible_publication(json.loads(values[0])) if values[0] is not None else self._empty()
		result = dict(zip(names, values[1:]))
		result["publication"] = publication
		return result
