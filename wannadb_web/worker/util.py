"""Task-state values exposed by web worker status publications."""
import enum


class State(enum.Enum):
	"""Stable task-state names used in web status publications."""
	STARTED = 'STARTED'
	WAITING = 'WAITING'
	PENDING = 'PENDING'
	SUCCESS = 'SUCCESS'
	ERROR = 'ERROR'

