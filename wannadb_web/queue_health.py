"""Queue consumer leases and bounded broker monitoring for API readiness."""

import logging
import os

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from wannadb_web.Redis.util import connectRedis

from wannadb_web.limits import _positive_setting

logger = logging.getLogger(__name__)

REQUIRED_QUEUES = ("celery", "feedback")
HEARTBEAT_INTERVAL = _positive_setting("WORKER_HEARTBEAT_INTERVAL_SECONDS", 10)
HEARTBEAT_TTL = _positive_setting("WORKER_HEARTBEAT_TTL_SECONDS", 45)
QUEUE_WAIT_WARNING = _positive_setting("QUEUE_WAIT_WARNING_SECONDS", 60)
if HEARTBEAT_TTL <= HEARTBEAT_INTERVAL:
    raise RuntimeError("WORKER_HEARTBEAT_TTL_SECONDS must exceed WORKER_HEARTBEAT_INTERVAL_SECONDS.")

_HEARTBEAT_KEYS = tuple(f"wannadb:queue-health:{queue}" for queue in REQUIRED_QUEUES)
_HEARTBEAT_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
for index, key in ipairs(KEYS) do
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
    redis.call('ZREM', key, ARGV[1])
    if ARGV[index + 2] == '1' then
        redis.call('ZADD', key, now + tonumber(ARGV[2]), ARGV[1])
        redis.call('EXPIRE', key, tonumber(ARGV[2]) * 2)
    end
end
"""
_CONSUMERS_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local counts = {}
for index, key in ipairs(KEYS) do
    counts[index] = redis.call('ZCOUNT', key, '(' .. now, '+inf')
end
return counts
"""
_BROKER_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local count, oldest, unknown = 0, now, 0
for _, key in ipairs(KEYS) do
    count = count + redis.call('LLEN', key)
    local tail = redis.call('LINDEX', key, -1)
    if tail then
        -- Kombu stores the task body as base64. Read the numeric header without
        -- decoding or returning a potentially large body.
        local queued_at = tonumber(string.match(tail,
            '"wannadb_queued_at"%s*:%s*([%d%.eE%+%-]+)'))
        if queued_at and queued_at > 0 then
            oldest = math.min(oldest, queued_at)
        else
            unknown = 1
        end
    end
end
return {count, math.floor(math.max(0, now - oldest)), unknown}
"""


def connect_monitor():
    """Bound health-check connections independently of normal task clients."""
    return connectRedis(timeout=1, retry=Retry(NoBackoff(), 0))


def publish_heartbeat(redis, consumer_id: str, queues) -> None:
    """Refresh only this consumer's live queue subscriptions using Redis time."""
    redis.eval(_HEARTBEAT_SCRIPT, len(_HEARTBEAT_KEYS), *_HEARTBEAT_KEYS,
               consumer_id, HEARTBEAT_TTL, *(int(queue in queues) for queue in REQUIRED_QUEUES))


def remove_heartbeat(redis, consumer_id: str) -> None:
    with redis.pipeline() as pipeline:
        for key in _HEARTBEAT_KEYS:
            pipeline.zrem(key, consumer_id)
        pipeline.execute()


def queue_health(redis) -> dict:
    """Read consumer freshness and broker waiting metrics without task contents."""
    counts = redis.eval(_CONSUMERS_SCRIPT, len(_HEARTBEAT_KEYS), *_HEARTBEAT_KEYS)
    result = {}
    with Redis.from_url(os.environ["CELERY_BROKER_URL"],
                        socket_connect_timeout=1, socket_timeout=1, retry=Retry(NoBackoff(), 0)) as broker:
        for queue, consumers in zip(REQUIRED_QUEUES, counts):
            # Kombu's Redis transport uses these four priority lists by default.
            keys = [queue, *(f"{queue}\x06\x16{priority}" for priority in (3, 6, 9))]
            queued, wait, unknown = broker.eval(_BROKER_SCRIPT, len(keys), *keys)
            status = "ready"
            if not consumers:
                status = "missing_consumer"
            elif wait >= QUEUE_WAIT_WARNING:
                status = "delayed"
            result[queue] = {"consumers": consumers, "queued": queued,
                             "oldest_wait_seconds": None if unknown else wait, "status": status}
            if status != "ready" or unknown:
                logger.warning("Queue health. queue=%s status=%s queued=%s oldest_wait_seconds=%s",
                               queue, status, queued, result[queue]["oldest_wait_seconds"])
    return result
