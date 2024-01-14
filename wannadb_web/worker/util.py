import enum
import pickle
from dataclasses import dataclass
from typing import Callable, Any, Optional

from wannadb.interaction import InteractionCallback
from wannadb.status import StatusCallback
from wannadb_web.worker.Signals import Signals


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

	msg: str
	__signals: Signals

	def __init__(self, task_update_fn: Optional[TaskUpdate], state=State.STARTED):
		self.task_update_fn = task_update_fn
		self.__state = state
		self.__signals = Signals()

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

	@property
	def signals(self) -> Signals:
		return self.__signals

	def __set_state(self, state: State):
		if not isinstance(state, State):
			print("update error Invalid state", state)
			raise Exception("update error Invalid state")
		if state is None:
			print("update error State is none", state)
			raise Exception("update error State is none")
		self.__state = state

	def __set_signals(self, signals: Signals):
		self.__signals = signals

	def update(self, state: State, msg=""):
		if isinstance(state, State) and state is not None:
			self.__set_state(state)
			self.msg = msg
			self.task_update_fn(self.state.value, self)
		else:
			raise Exception("update error State is none")

	def to_dump(self):
		state = self.state
		signals = self.signals
		msg = self.msg
		return pickle.dumps((state, signals, msg))

	@staticmethod
	def from_dump(dump: bytes):
		state, signals, msg = pickle.loads(dump)
		to = TaskObject(None, state=state)
		to.__set_signals(signals)
		to.msg = msg
		return to
