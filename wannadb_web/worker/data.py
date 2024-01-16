import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any

from wannadb.data.data import DocumentBase, InformationNugget, Document, Attribute
from wannadb.data.signals import BaseSignal
from wannadb.statistics import Statistics


def signal_to_json(signal: BaseSignal):
	return {
		"name": signal.identifier,
		"signal": "not serializable"
	}


def nugget_to_json(nugget: InformationNugget):
	return {
		"text": nugget.text,
		"signals": [{"name": name, "signal": signal_to_json(signal)} for name, signal in
					nugget.signals.items()],
		"document": {"name": nugget.document.name, "text": nugget.document.text},
		"end_char": str(nugget.end_char),
		"start_char": str(nugget.start_char)}


def document_to_json(document: Document):
	return {
		"name": document.name,
		"text": document.text,
		"attribute_mappings": "not implemented yet",
		"signals": [{"name": name, "signal": signal_to_json(signal)} for name, signal in
					document.signals.items()],
		"nuggets": [nugget_to_json(nugget) for nugget in document.nuggets]
	}


def attribute_to_json(attribute: Attribute):
	return {
		"name": attribute.name
	}


def document_base_to_json(document_base: DocumentBase):
	return {
		'msg': {"attributes ": [attribute.name for attribute in document_base.attributes],
				"nuggets": [nugget_to_json(nugget) for nugget in document_base.nuggets]
				}
	}


class Signals:
	def __init__(self):
		self.feedback = _Signal("feedback")
		self.status = _State("status")
		self.finished = _Signal("finished")
		self.error = _Error("error")
		self.document_base_to_ui = _DocumentBase("document_base_to_ui")
		self.statistics = _Statistics("statistics_to_ui")
		self.feedback_request_to_ui = _Dump("feedback_request_to_ui")
		self.cache_db_to_ui = _Dump("cache_db_to_ui")

	def to_json(self) -> dict[str, str]:
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
			return {"error": "signals to json error"}


class Emitable(ABC):
	__msg: Optional[Any]

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
class _State(Emitable):
	__msg: Optional[str]

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
class _Signal(Emitable):
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
			'msg': self.msg
		}

	def emit(self, status: float):
		self.__msg = status


@dataclass
class _Error(Emitable):
	__msg: Optional[BaseException]

	def __init__(self, error_type: str):
		super().__init__(error_type)
		self.__msg = None

	@property
	def msg(self):
		return self.__msg

	def to_json(self):
		return {
			'type': self.type,
			'msg': str(self.msg)
		}

	def emit(self, exception: BaseException):
		self.__msg = exception


@dataclass
class _Nugget(Emitable):
	__msg: Optional[InformationNugget]

	def __init__(self, nugget_type: str):
		super().__init__(nugget_type)
		self.__msg = None

	@property
	def msg(self):
		return self.__msg

	def to_json(self):
		if self.msg is None:
			return {}
		return nugget_to_json(self.msg)

	def emit(self, status):
		self.__msg = status


@dataclass
class _DocumentBase(Emitable):
	__msg: Optional[DocumentBase]

	def __init__(self, document_type: str):
		super().__init__(document_type)
		self.__msg = None

	@property
	def msg(self):
		return self.__msg

	def to_json(self):
		if self.msg is None:
			return {}
		return document_base_to_json(self.msg)

	def emit(self, status):
		self.__msg = status


class _Statistics(Emitable):
	__msg: Statistics

	def __init__(self, statistics_type: str):
		super().__init__(statistics_type)
		self.__msg = Statistics(False)

	@property
	def msg(self):
		return self.__msg

	def to_json(self):
		return {
			'type': self.type,
			'msg': self.__msg.to_serializable()
		}

	def emit(self, statistic: Statistics):
		self.__msg = statistic


class _Dump(Emitable):
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
