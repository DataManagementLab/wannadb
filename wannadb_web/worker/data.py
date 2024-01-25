import abc
import json
from abc import abstractmethod
from typing import Any

from wannadb.data.data import DocumentBase, InformationNugget, Document, Attribute
from wannadb.data.signals import BaseSignal
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache


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
		'msg': {"attributes": [attribute.name for attribute in document_base.attributes],
				"nuggets": [nugget_to_json(nugget) for nugget in document_base.nuggets]
				}
	}


class Signals:
	def __init__(self, user_id: str):
		self.__user_id = user_id
		self.pipeline = _State("pipeline", user_id)
		self.feedback = _Signal("feedback", user_id)
		self.status = _State("status", user_id)
		self.finished = _Signal("finished", user_id)
		self.error = _Error("error", user_id)
		self.document_base_to_ui = _DocumentBase("document_base_to_ui", user_id)
		self.statistics = _Statistics("statistics_to_ui", user_id)
		self.feedback_request_to_ui = _Feedback("feedback_request_to_ui", user_id)
		self.feedback_request_from_ui = _Feedback("feedback_request_from_ui", user_id)
		self.cache_db_to_ui = _Dump("cache_db_to_ui", user_id)

	def to_json(self) -> dict[str, str]:
		return {"user_id": self.__user_id,
				self.feedback.type: self.feedback.to_json(),
				self.error.type: self.error.to_json(),
				self.status.type: self.status.to_json(),
				self.finished.type: self.finished.to_json(),
				self.document_base_to_ui.type: self.document_base_to_ui.to_json(),
				self.statistics.type: self.statistics.to_json(),
				self.feedback_request_to_ui.type: self.feedback_request_to_ui.to_json(),
				self.cache_db_to_ui.type: self.cache_db_to_ui.to_json()}

	def reset(self):
		RedisCache(self.__user_id).delete_user_space()


class Emitable(abc.ABC):

	def __init__(self, emitable_type: str, user_id: str):
		self.type = emitable_type
		self.redis = RedisCache(user_id)

	@property
	def msg(self):
		msg = self.redis.get(self.type)
		if msg is None:
			return None
		return msg

	@abstractmethod
	def to_json(self):
		raise NotImplementedError

	@abstractmethod
	def emit(self, status: Any):
		raise NotImplementedError


class _State(Emitable):

	def to_json(self):
		if self.msg is None:
			return ""
		return self.msg.decode("utf-8")

	def emit(self, status: str):
		self.redis.set(self.type, status)


class _Signal(Emitable):

	def to_json(self):
		return str(self.msg)

	def emit(self, status: float):
		self.redis.set(self.type, str(status))


class _Error(Emitable):

	def to_json(self):
		if self.msg is None:
			return ""
		return self.msg.decode("utf-8")

	def emit(self, exception: BaseException):
		self.redis.set(self.type, str(exception))


class _Nugget(Emitable):

	def to_json(self):
		if self.msg is None:
			return {}
		if not isinstance(self.msg, str):
			raise TypeError("_Nugget msg must be of type str")
		return self.msg

	def emit(self, status: InformationNugget):
		self.redis.set(self.type, json.dumps(nugget_to_json(status)))


class _DocumentBase(Emitable):

	def to_json(self):
		if self.msg is None:
			return {}
		return json.loads(self.msg)

	def emit(self, status: DocumentBase):
		self.redis.set(self.type, json.dumps(document_base_to_json(status)))


class _Statistics(Emitable):

	@property
	def msg(self):
		return "not implemented"

	def to_json(self):
		return Statistics(False).to_serializable()

	def emit(self, statistic: Statistics):
		pass


class _Feedback(Emitable):

	def to_json(self):
		if self.msg is None:
			return {}
		return json.loads(self.msg)

	def emit(self, status: dict[str, Any]):
		self.redis.set(self.type, json.dumps(status))


class _Dump(Emitable):

	def to_json(self):
		return self.msg

	def emit(self, status):
		self.redis.set(self.type, json.dumps(status))
