import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Any

import jwt


class Authorisation(Enum):
	Owner = 0
	Admin = 1
	Member = 10


jwtkey = "secret"


def encode(obj: dict[str, Any]):
	return jwt.encode(obj, jwtkey, algorithm="HS256")


def decode(string: str):
	token: Token = jwt.decode(string, jwtkey, leeway=datetime.timedelta(minutes=1), algorithm="HS256", verify=True)
	return Token(token.user, token.id, token.exp)


@dataclass
class Token:
	user: str
	id: int
	exp = datetime.datetime.now() + datetime.timedelta(hours=1)

	def dict(self):
		return {"user": self.user, "id": self.id}
