import enum
import pickle
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

from wannadb.interaction import InteractionCallback
from wannadb.status import StatusCallback
from wannadb_web.worker.data import Signals


class TaskUpdate:
	"""Task callback that is initialized with a callback function."""

	def __init__(self, callback_fn: Callable[[str, Any], None]):
		"""
		Initialize the Task callback.

		:param callback_fn: callback function that is called whenever the interaction callback is called
		"""
		self._callback_fn: Callable[[str, Any], None] = callback_fn

	def __call__(self, state: str, context: Any) -> None:
		return self._callback_fn(state, context)


class State(enum.Enum):
	STARTED = 'STARTED'
	PENDING = 'PENDING'
	SUCCESS = 'SUCCESS'
	FAILURE = 'FAILURE'
	ERROR = 'ERROR'


@dataclass
class TaskObject:
	"""Class for representing the response of a task."""

	task_update_fn: Optional[TaskUpdate]
	__signals: Signals = field(default_factory=Signals)
	__state: State = State.STARTED

	@property
	def status_callback(self):
		def status_callback_fn(message, progress) -> None:
			m = str(message)
			p = str(progress)

			self.signals.status.emit(m + ":" + p)
			self.update(State.PENDING)

		return StatusCallback(status_callback_fn)

	@property
	def interaction_callback(self):
		def interaction_callback_fn(pipeline_element_identifier, feedback_request):
			feedback_request["identifier"] = pipeline_element_identifier
			self.signals.feedback_request_to_ui.emit(feedback_request)
			self.update(State.PENDING)
			return self.signals.feedback

		return InteractionCallback(interaction_callback_fn)

	@property
	def state(self) -> State:
		return self.__state

	@state.setter
	def state(self, state: State):
		if not isinstance(state, State):
			print("update error Invalid state", state)
			raise Exception("update error Invalid state")
		if state is None:
			print("update error State is none", state)
			raise Exception("update error State is none")
		self.__state = state

	@property
	def signals(self) -> Signals:
		return self.__signals

	@signals.setter
	def signals(self, signals: Signals):
		self.__signals = signals

	def update(self, state: Optional[State]):
		if self.task_update_fn is None:
			raise Exception("update error task_update_fn is None do you want to update here?")
		if isinstance(state, State) and state is not None:
			self.state = state
		self.task_update_fn(self.state.value, self)

	def to_dump(self):
		_state = self.state
		_signals = self.signals
		return pickle.dumps((_state, _signals))

	@staticmethod
	def from_dump(dump: bytes):
		state, signals = pickle.loads(dump)
		to = TaskObject(None,state)
		to.signals = signals
		return to

	def check(self):
		self.update(None)
		if self.signals.error.msg:
			self.update(State.FAILURE)
			raise self.signals.error.msg
