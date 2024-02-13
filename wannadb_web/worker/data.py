import abc
import json
import pickle
from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import Any, Union, Optional

from wannadb.data.data import DocumentBase, InformationNugget, Document, Attribute
from wannadb.data.signals import BaseSignal
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache

@dataclass
class _BaseSignal:
	identifier:str
	signal="not serializable"

	def to_json(self):
		return {
			"identifier": self.identifier,
			"signal":self.signal
		}

def convert_signal(signal: BaseSignal) -> _BaseSignal:
	return _BaseSignal(signal.identifier)

@dataclass
class _InformationNugget:
	text:str
	signals:dict[str,BaseSignal]
	document:Document
	end_char:int
	start_char:int

	def to_json(self):
		return {
		"text": self.text,
		"signals": [{"name": name, "signal": convert_signal(signal).to_json()} for name, signal in
					self.signals.items()],
		"document": {"name": self.document.name, "text": self.document.text},
		"end_char": str(self.end_char),
		"start_char": str(self.start_char)}



def convert_to_nugget(nugget: InformationNugget):
	return _InformationNugget(nugget.text,nugget.signals,nugget.document,nugget.end_char,nugget.start_char)


@dataclass
class _InformationNuggets:
	nuggets: list[InformationNugget]

	def to_json(self):
		return {
		str(i): convert_to_nugget(nugget).to_json() for i, nugget in enumerate(self.nuggets)
	}

def convert_to_nuggets(nuggets: list[InformationNugget]):
	return _InformationNuggets(nuggets)


@dataclass
class _Document:
	name:str
	text:str
	attribute_mappings = "not implemented yet"
	signals:dict[str,BaseSignal]
	nuggets:list[InformationNugget]

	def to_json(self):
		return {
		"name": self.name,
		"text": self.text,
		"attribute_mappings": "not implemented yet",
		"signals": [{"name": name, "signal": convert_signal(signal)} for name, signal in
					self.signals.items()],
		"nuggets": [convert_to_nugget(nugget).to_json() for nugget in self.nuggets]
	}


def convert_to_document(document: Document):
	return _Document(document.name,document.text,document.signals,document.nuggets)


@dataclass
class _Attribute:
	name:str
	signals = "not_implemented"

	def to_json(self):
		return {
			"name": self.name,
			"signals": self.signals
		}

def convert_to_attribute(attribute: Attribute):
	return _Attribute(attribute.name)


@dataclass
class _DocumentBase:
	attributes:list[Attribute]
	nuggets:list[InformationNugget]
	documents:list[Document]

	def to_json(self):
		return {
			"attributes": [attribute.name for attribute in self.attributes],
			"nuggets": [convert_to_nugget(nugget).to_json() for nugget in self.nuggets],
			"documents": [convert_to_document(document).to_json() for document in self.documents]
		}

def convert_to_document_base(document_base: DocumentBase):
	return _DocumentBase(document_base.attributes,document_base.nuggets,document_base.documents)


class Signals:
	def __init__(self, user_id: str):
		self.__user_id = user_id
		self.pipeline = _State("pipeline", user_id)
		self.feedback = _Signal("feedback", user_id)
		self.status = _State("status", user_id)
		self.finished = _Signal("finished", user_id)
		self.error = _Error("error", user_id)
		self.document_base_to_ui = _DocumentBaseToUi("document_base_to_ui", user_id)
		self.statistics = _Statistics("statistics_to_ui", user_id)
		self.feedback_request_to_ui = _Feedback("feedback_request_to_ui", user_id)
		self.feedback_request_from_ui = _Feedback("feedback_request_from_ui", user_id)
		self.cache_db_to_ui = _Dump("cache_db_to_ui", user_id)
		self.ordert_nuggets = _Nuggets("ordert_nuggets", user_id)
		self.match_feedback = _MatchFeedback("match_feedback", user_id)

	def to_json(self) -> dict[str, str]:
		return {"user_id": self.__user_id,
				self.feedback.type: self.feedback.to_json(),
				self.error.type: self.error.to_json(),
				self.status.type: self.status.to_json(),
				self.finished.type: self.finished.to_json(),
				self.document_base_to_ui.type: self.document_base_to_ui.to_json(),
				self.statistics.type: self.statistics.to_json(),
				self.feedback_request_to_ui.type: self.feedback_request_to_ui.to_json(),
				self.cache_db_to_ui.type: self.cache_db_to_ui.to_json(),
				self.ordert_nuggets.type: self.ordert_nuggets.to_json()
				}

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


@dataclass
class CustomMatchFeedback:
	message = "custom-match"
	document: Document
	start: int
	end: int

	def to_json(self):
		return {"message": self.message, "document": convert_to_document(self.document).to_json(), "start": self.start,
				"end": self.end}


@dataclass
class NuggetMatchFeedback:
	message = "is-match"
	nugget: InformationNugget
	not_a_match: None

	def to_json(self):
		return {"message": self.message, "nugget": convert_to_nugget(self.nugget).to_json(), "not_a_match": self.not_a_match}


@dataclass
class NoMatchFeedback:
	message = "no-match-in-document"
	nugget: InformationNugget
	not_a_match: InformationNugget

	def to_json(self):
		return {"message": self.message, "nugget": convert_to_nugget(self.nugget).to_json(),
				"not_a_match": convert_to_nugget(self.not_a_match).to_json()}


class _MatchFeedback(Emitable):

	@property
	def msg(self) -> Union[CustomMatchFeedback, NuggetMatchFeedback, NoMatchFeedback, None]:
		msg = self.redis.get(self.type)
		if isinstance(msg, str) and msg.startswith("{"):
			m = json.loads(msg)
			if "message" in m and m["message"] == "custom-match":
				return CustomMatchFeedback(m["document"], m["start"], m["end"])
			elif "message" in m and m["message"] == "is-match":
				return NuggetMatchFeedback(m["nugget"], None)
			elif "message" in m and m["message"] == "no-match-in-document":
				return NoMatchFeedback(m["nugget"], m["not_a_match"])
		return None

	def to_json(self):
		if self.msg is None:
			return {}
		return self.msg.to_json()

	def emit(self, status: Union[CustomMatchFeedback, NuggetMatchFeedback, NoMatchFeedback, None]):
		if status is None:
			self.redis.delete(self.type)
			return
		if isinstance(status, CustomMatchFeedback):
			self.redis.set(self.type, json.dumps(
				{"message": status.message, "document": convert_to_document(status.document).to_json(), "start": status.start,
				 "end": status.end}))
		elif isinstance(status, NuggetMatchFeedback):
			self.redis.set(self.type, json.dumps({"message": status.message, "nugget": convert_to_nugget(status.nugget).to_json()}))
		elif isinstance(status, NoMatchFeedback):
			self.redis.set(self.type, json.dumps(
				{"message": status.message, "nugget": convert_to_nugget(status.nugget).to_json(),
				 "not_a_match": convert_to_nugget(status.not_a_match).to_json()}))
		else:
			raise TypeError("status must be of type CustomMatchFeedback or NuggetMatchFeedback or NoMatchFeedback or None")


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


class _Nuggets(Emitable):

	@property
	def msg(self) -> Optional[list[InformationNugget]]:
		msg = self.redis.get(self.type)
		if msg is None:
			return None
		if isinstance(msg,bytes):
			return pickle.loads(msg)
		else:
			raise TypeError("msg is not bytes")


	def to_json(self):
		if self.msg is None:
			return {}
		return convert_to_nuggets(self.msg).to_json()

	def emit(self, status: list[InformationNugget]):
		b:bytes = pickle.dumps(status)
		if isinstance(b,bytes):
			self.redis.set(self.type, b)
		else:
			raise TypeError("b is not bytes")


class _DocumentBaseToUi(Emitable):

	@property
	def msg(self) -> Optional[DocumentBase]:
		msg = self.redis.get(self.type)
		if msg is None:
			return None
		if isinstance(msg,bytes):
			return pickle.loads(msg)
		else:
			raise TypeError("msg is not bytes")

	def to_json(self):
		if self.msg is None:
			return {}
		return convert_to_document_base(self.msg).to_json()

	def emit(self, status: DocumentBase):
		self.redis.set(self.type, pickle.dumps(status))


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
		print("Status: " + str(status))
		for key, value in status.items():
			if isinstance(value, Attribute):
				status[key] = value.toJSON()
		self.redis.set(self.type, json.dumps(status))


class _Dump(Emitable):

	def to_json(self):
		return self.msg

	def emit(self, status):
		self.redis.set(self.type, json.dumps(status))
