from enum import Enum


class Authorisation(Enum):
	Owner = 0
	Admin = 1
	Member = 10


jwtkey = "secret"


class JWTFormat:
	def __init__(self, user: str, id: int):
		self.user = user
		self.id = id
