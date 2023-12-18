import datetime
from enum import Enum
from typing import Any

import jwt


class Authorisation(Enum):
	Owner = 0
	Admin = 1
	Member = 10


_jwtkey = "secret"


def tokenEncode(obj: dict[str, Any]):
	return jwt.encode(obj, _jwtkey, algorithm="HS256")


def tokenDecode(string: str):
	if string is None or len(string) < 2:
		raise ValueError("string value is: ", string)
	try:
		decoded_token = jwt.decode(string, _jwtkey, leeway=datetime.timedelta(minutes=1), algorithms="HS256",
								   verify=True)
	except jwt.ExpiredSignatureError:
		return False
	user = decoded_token.get('user')
	_id = int(decoded_token.get('id'))
	exp = decoded_token.get('exp')
	return Token(user, _id, exp)


class Token:
	user: str
	id: int

	def __init__(self, user: str, _id: int, exp=datetime.datetime.now() + datetime.timedelta(hours=1)):
		self.user = user
		self.id = _id
		self.exp = exp

	def json(self):
		return {"user": self.user, "id": self.id}
