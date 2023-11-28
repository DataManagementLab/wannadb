from enum import Enum
from dataclasses import dataclass

import jwt


class Authorisation(Enum):
	Owner = 0
	Admin = 1
	Member = 10


jwtkey = "secret"


def encode(obj):
	return jwt.encode(obj, jwtkey, algorithm="HS256")


def decode(string: str):
	token: User = jwt.decode(string, jwtkey, algorithm="HS256")
	return User(token.user, token.id)


@dataclass
class User:
	user: str
	id: int


