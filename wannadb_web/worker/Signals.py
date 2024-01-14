import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any


class Signals:
	def __init__(self):
		self.feedback = Signal("feedback")
		self.status = State("status")
		self.finished = Signal("finished")
		self.error = State("error")
		self.document_base_to_ui = Dump("document_base_to_ui")
		self.statistics = Dump("statistics_to_ui")
		self.feedback_request_to_ui = Dump("feedback_request_to_ui")
		self.cache_db_to_ui = Dump("cache_db_to_ui")

	def to_json(self):
		try:
			return {self.feedback.type: self.feedback.to_json(),
					self.error.type: self.error.to_json(),
					self.status.type: self.status.to_json(),
					self.finished.type: self.finished.to_json(),
					self.document_base_to_ui.type: self.document_base_to_ui.to_json(),
					self.statistics.type: self.statistics.to_json(),
					self.feedback_request_to_ui.type: self.feedback_request_to_ui.to_json(),
					self.cache_db_to_ui.type: self.cache_db_to_ui.to_json()}
		except Exception as e:
			print(e)
			return {}


class Emitable(ABC):
	@abstractmethod
	def __init__(self, emitable_type: str):
		self.type = emitable_type
		self.__msg = None

	@abstractmethod
	def to_json(self):
		raise NotImplementedError

	@abstractmethod
	def emit(self, status: Any):
		raise NotImplementedError


@dataclass
class State(Emitable):
	def __init__(self, state_type: str):
		super().__init__(state_type)
		self.__msg = ""

	@property
	def msg(self):
		return self.__msg

	def to_json(self):
		return {
			'type': self.type,
			'msg': str(self.msg)
		}

	def emit(self, status: str):
		self.__msg = status


@dataclass
class Signal(Emitable):
	__msg: Optional[float]

	def __init__(self, signal_type: str):
		super().__init__(signal_type)
		self.__msg = None

	@property
	def msg(self):
		return self.__msg

	def to_json(self):
		return {
			'type': self.type,
			'msg': str(self.msg)
		}

	def emit(self, status: float):
		self.__msg = status


class Dump(Emitable):
	def __init__(self, dump_type: str):
		super().__init__(dump_type)
		self.__msg = None

	@property
	def msg(self):
		return self.__msg

	def to_json(self):
		return {
			'type': self.type,
			'msg': json.dumps(self.msg)
		}

	def emit(self, status):
		self.__msg = status
