import datetime
import logging
import math
import os
from enum import Enum
from typing import Any

import jwt

logger: logging.Logger = logging.getLogger(__name__)


class Authorisation(Enum):
	Owner = 0
	Admin = 1
	Member = 10


_jwtkey = os.environ.get("WANNA_DB_JWT_SECRET", "")
if len(_jwtkey.encode("utf-8")) < 32:
	raise RuntimeError("WANNA_DB_JWT_SECRET must be configured with at least 32 bytes")


def tokenEncode(obj: dict[str, Any]):
	now = datetime.datetime.now(datetime.timezone.utc)
	payload = dict(obj, iat=now, exp=now + datetime.timedelta(hours=1))
	return jwt.encode(payload, _jwtkey, algorithm="HS256")


def tokenDecode(string: str):
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
	user: str
	id: int

	def __init__(self, user: str, _id: int, exp=None):
		self.user = user
		self.id = _id
		self.exp = exp if exp is not None else datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)

	def json(self):
		return {"user": self.user, "id": self.id}
