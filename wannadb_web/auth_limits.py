"""Atomic authentication budgets and authenticated frontend client identities."""

from hashlib import sha256
import hmac
import ipaddress
import os
import re
import time

from redis.backoff import NoBackoff
from redis.retry import Retry

from wannadb_web.Redis.util import connectRedis
from wannadb_web.limits import _positive_setting

WINDOW_SECONDS = _positive_setting("AUTH_RATE_WINDOW_SECONDS", 60)
REGISTRATIONS_PER_CLIENT = _positive_setting("AUTH_REGISTRATIONS_PER_CLIENT", 15)
LOGINS_PER_CLIENT = _positive_setting("AUTH_LOGINS_PER_CLIENT", 120)
LOGINS_PER_USERNAME = _positive_setting("AUTH_LOGINS_PER_USERNAME", 10)
REGISTRATIONS_GLOBAL = _positive_setting("AUTH_REGISTRATIONS_GLOBAL", 150)
LOGINS_GLOBAL = _positive_setting("AUTH_LOGINS_GLOBAL", 1200)

_PROXY_SECRET = os.environ.get("AUTH_PROXY_SECRET", "")
if _PROXY_SECRET and len(_PROXY_SECRET.encode("utf-8")) < 32:
    raise RuntimeError("AUTH_PROXY_SECRET must contain at least 32 UTF-8 bytes.")
_PROXY_HEADERS = ("X-WannaDB-Auth-Client", "X-WannaDB-Auth-Timestamp", "X-WannaDB-Auth-Signature")

_TAKE_ATTEMPT = """
local retry_after = 0
for index, key in ipairs(KEYS) do
    local count = tonumber(redis.call('GET', key) or '0')
    if count >= tonumber(ARGV[index]) then
        retry_after = math.max(retry_after, math.max(1, redis.call('TTL', key)))
    end
end
if retry_after > 0 then return retry_after end
for _, key in ipairs(KEYS) do
    if redis.call('INCR', key) == 1 then
        redis.call('EXPIRE', key, ARGV[#KEYS + 1])
    end
end
return 0
"""


class AuthProxyError(ValueError):
    """A client context could not be authenticated as coming from the frontend."""


def _normalize_ip(value):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return str(address)


def auth_client_identity(headers, method: str, path: str, peer: str) -> str:
    """Trust signed context, or the direct socket peer when no context is supplied."""
    values = [headers.get(name) for name in _PROXY_HEADERS]
    if not any(value is not None for value in values):
        try:
            return _normalize_ip(peer)
        except ValueError:
            return "unknown"
    client, timestamp, signature = values
    if (not _PROXY_SECRET or method != "POST" or path not in ("/login", "/register")
            or not isinstance(client, str) or len(client) > 64
            or not isinstance(timestamp, str) or not re.fullmatch(r"[0-9]{1,11}", timestamp)
            or not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature)):
        raise AuthProxyError("The authentication gateway could not be verified.")
    try:
        identity = _normalize_ip(client)
    except ValueError:
        raise AuthProxyError("The authentication gateway could not be verified.") from None
    age = time.time() - int(timestamp)
    message = f"v1\n{timestamp}\n{method}\n{path}\n{client}"
    expected = hmac.new(_PROXY_SECRET.encode("utf-8"), message.encode("utf-8"), sha256).hexdigest()
    if not -5 <= age <= 60 or not hmac.compare_digest(signature, expected):
        raise AuthProxyError("The authentication gateway could not be verified.")
    return identity


def auth_retry_after(action: str, identity: str, username=None) -> int:
    """Consume all applicable budgets together only when every budget permits."""
    if action == "register":
        client_maximum, global_maximum = REGISTRATIONS_PER_CLIENT, REGISTRATIONS_GLOBAL
    elif action == "login":
        client_maximum, global_maximum = LOGINS_PER_CLIENT, LOGINS_GLOBAL
    else:
        raise ValueError("Unsupported authentication action.")
    digest = sha256(identity.encode("utf-8")).hexdigest()
    keys = [f"wannadb:auth:{action}-client:{digest}", f"wannadb:auth:{action}-global"]
    maxima = [client_maximum, global_maximum]
    if action == "login" and username is not None:
        digest = sha256(username.encode("utf-8")).hexdigest()
        keys.append(f"wannadb:auth:login-username:{digest}")
        maxima.append(LOGINS_PER_USERNAME)
    with connectRedis(timeout=1, retry=Retry(NoBackoff(), 0)) as redis:
        return redis.eval(_TAKE_ATTEMPT, len(keys), *keys, *maxima, WINDOW_SECONDS)
