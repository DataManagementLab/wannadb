"""Backend authorization roles and fixed-lifetime signed account credentials."""
import datetime
import logging
import math
import os
from enum import Enum
from typing import Any

import jwt

logger: logging.Logger = logging.getLogger(__name__)


class Authorisation(Enum):
	"""Stable owner, administrator and member role values used by the web backend."""
	Owner = 0
	Admin = 1
	Member = 10


_jwtkey = os.environ.get("WANNA_DB_JWT_SECRET", "")
if len(_jwtkey.encode("utf-8")) < 32:
	raise RuntimeError("WANNA_DB_JWT_SECRET must be configured with at least 32 bytes")


def tokenEncode(obj: dict[str, Any]):
	"""Sign account claims with a fixed one-hour expiry using the backend signing key.

	:param obj: The account claims to sign.
	:type obj: dict[str, Any]
	:returns: The token encode text or identifier.
	:rtype: str
	"""
	now = datetime.datetime.now(datetime.timezone.utc)
	payload = dict(obj, iat=now, exp=now + datetime.timedelta(hours=1))
	return jwt.encode(payload, _jwtkey, algorithm="HS256")


def tokenDecode(string: str):
	"""Validate a backend credential and reconstruct its account identity, or return None.

	:param string: The optional Bearer-prefixed backend credential.
	:type string: str
	:returns: The token decode result.
	:rtype: Token | None
	"""
	if not isinstance(string, str) or not string.strip():
		return None
	string = string.strip()
	if string.lower().startswith("bearer "):
		string = string[7:].strip()
	try:
		decoded_token = jwt.decode(string, _jwtkey, algorithms=["HS256"],
								   options={"require": ["user", "id", "exp"]})
	except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError):
		return None
	user = decoded_token.get('user')
	_id = decoded_token.get('id')
	exp = decoded_token.get('exp')
	if (not isinstance(user, str) or not user.strip()
			or type(_id) is not int or _id <= 0
			or type(exp) not in (int, float) or (type(exp) is float and not math.isfinite(exp))):
		return None
	return Token(user, _id, exp)


class Token:
	"""Validated account identity and expiry associated with a backend credential."""
	user: str
	id: int

	def __init__(self, user: str, _id: int, exp=None):
		"""Initialize Token with its supplied dependencies and scope.

		:param user: The account username.
		:type user: str
		:param _id: The database ID supplied in this layer's expected representation.
		:type _id: int
		:param exp: The credential expiry timestamp or datetime.
		:type exp: float | datetime.datetime | None
		"""
		self.user = user
		self.id = _id
		self.exp = exp if exp is not None else datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

	def json(self):
		"""Return account claims without copying the expiry into the unsigned claim dictionary.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {"user": self.user, "id": self.id}
