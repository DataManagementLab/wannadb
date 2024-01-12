from dataclasses import dataclass
from typing import Any


class Signals:
	def __init__(self):
		self.feedback = Signal("feedback")
		self.status = Signal("status")
		self.finished = Signal("finished")
		self.error = Signal("error")
		self.document_base_to_ui = Signal("document_base_to_ui")
		self.statistics_to_ui = Signal("statistics_to_ui")
		self.feedback_request_to_ui = Signal("feedback_request_to_ui")
		self.cache_db_to_ui = Signal("cache_db_to_ui")

	def print(self):
		print(self.feedback)
		print(self.status)
		print(self.finished)
		print(self.error)
		print(self.document_base_to_ui)
		print(self.statistics_to_ui)
		print(self.feedback_request_to_ui)
		print(self.cache_db_to_ui)

	def to_json(self):
		try:
			return {self.feedback.type: self.feedback.to_json(),
					self.error.type: self.error.to_json(),
					self.status.type: self.status.to_json(),
					self.finished.type: self.finished.to_json(),
					self.document_base_to_ui.type: self.document_base_to_ui.to_json(),
					self.statistics_to_ui.type: self.statistics_to_ui.to_json(),
					self.feedback_request_to_ui.type: self.feedback_request_to_ui.to_json(),
					self.cache_db_to_ui.type: self.cache_db_to_ui.to_json()}
		except Exception as e:
			print(e)
			return {}


@dataclass
class Signal:
	type: str
	__msg: list[Any]

	def __init__(self, signal_type: str):
		self.type = signal_type
		self.__msg = []

	@property
	def msg(self):
		return self.__msg

	def to_json(self):
		return {
			'type': self.type,
			'msg': str(self.msg)
		}

	def emit(self, *args: Any):
		for arg in args:
			self.msg.append(arg)
