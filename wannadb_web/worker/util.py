import enum


class State(enum.Enum):
	STARTED = 'STARTED'
	WAITING = 'WAITING'
	PENDING = 'PENDING'
	SUCCESS = 'SUCCESS'
	ERROR = 'ERROR'

