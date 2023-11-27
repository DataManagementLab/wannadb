jwtkey = "secret"


class JWTFormat:
	def __init__(self, user: str,id:int):
		self.user = user
		self.id = id
