import abc
from collections.abc import Iterable
import json
import pickle
from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import Any, Union, Optional
import logging

from wannadb.data.data import DocumentBase, InformationNugget, Document, Attribute
from wannadb.data.signals import BaseSignal
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache, SessionState, get_signal_scope

logger: logging.Logger = logging.getLogger(__name__)

@dataclass
class _BaseSignal:
	identifier:str
	signal:str

	def to_json(self):
		return {
			"identifier": self.identifier,
			"signal":self.signal
		}

def convert_signal(signal: BaseSignal) -> _BaseSignal:
	return _BaseSignal(identifier=signal.identifier, signal=str(signal))

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
	attribute_mappings: dict[str,list[InformationNugget]]
	signals:dict[str,BaseSignal]
	nuggets:list[InformationNugget]

	def to_json(self):
		return {
		"name": self.name,
		"text": self.text,
		"attribute_mappings": {name: [convert_to_nugget(nugget).to_json() for nugget in nuggets] for name, nuggets in self.attribute_mappings.items()},
		"signals": [{"name": name, "signal": convert_signal(signal)} for name, signal in
					self.signals.items()],
		"nuggets": [convert_to_nugget(nugget).to_json() for nugget in self.nuggets]
	}


def convert_to_document(document: Document):
	return _Document(document.name,document.text,document.attribute_mappings, document.signals,document.nuggets)


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
	def __init__(self, user_id: str, base_id: Optional[int] = None, session_id: Optional[str] = None):
		self.__user_id = user_id
		self.__cache_user_id = f"{user_id}:base:{base_id}:session:{session_id}" if base_id is not None and session_id is not None else user_id
		self.__session = SessionState(user_id, base_id, session_id) if base_id is not None and session_id is not None else None
		self.pipeline = _State("pipeline", self.__cache_user_id)
		self.feedback = _Signal("feedback", self.__cache_user_id)
		self.status = _State("status", self.__cache_user_id)
		self.finished = _Signal("finished", self.__cache_user_id)
		self.error = _Error("error", self.__cache_user_id)
		self.document_base_to_ui = _DocumentBaseToUi("document_base_to_ui", self.__cache_user_id)
		self.statistics = _Statistics("statistics_to_ui", self.__cache_user_id)
		self.feedback_request_to_ui = _Feedback("feedback_request_to_ui", self.__cache_user_id)
		self.feedback_request_from_ui = _Feedback("feedback_request_from_ui", self.__cache_user_id)
		self.cache_db_to_ui = _Dump("cache_db_to_ui", self.__cache_user_id)
		self.ordert_nuggets = _Nuggets("ordert_nuggets", self.__cache_user_id)
		self.match_feedback = _MatchFeedback("match_feedback", self.__cache_user_id)

	def to_json(self, include_payload: bool = True, include_feedback: bool = True, snapshot=None) -> dict[str, Any]:
		if snapshot is None and self.__session is not None:
			snapshot = self.__session.snapshot(include_payload=include_payload, include_feedback=include_feedback)
		def serialized(signal):
			if snapshot is None:
				return signal.to_json()
			# Each serializer keeps its normal decoding, but reads only this atomic snapshot.
			copy = object.__new__(type(signal))
			copy.type = signal.type
			copy.redis = _SnapshotCache(snapshot)
			return copy.to_json()
		return {"user_id": self.__user_id,
				self.feedback.type: serialized(self.feedback),
				self.error.type: serialized(self.error),
				self.status.type: serialized(self.status),
				self.finished.type: serialized(self.finished),
				self.document_base_to_ui.type: serialized(self.document_base_to_ui) if include_payload else {},
				self.statistics.type: serialized(self.statistics),
				self.feedback_request_to_ui.type: serialized(self.feedback_request_to_ui) if include_feedback else {},
				self.cache_db_to_ui.type: serialized(self.cache_db_to_ui) if include_payload else None,
				self.ordert_nuggets.type: serialized(self.ordert_nuggets) if include_payload else {}
				}

	def reset(self):
		# A worker owns a new session; loading a base must never erase its commands.
		scope = get_signal_scope()
		if self.__session is not None:
			self.__session.initialize()
		elif scope is not None:
			SessionState.current(self.__user_id).initialize()


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
		return {"message": self.message, "nugget": convert_to_nugget(self.nugget).to_json(), "not_a_match": convert_to_nugget(self.not_a_match).to_json() if self.not_a_match is not None else None}


@dataclass
class MultiNuggetsMatchFeedback:
	message = "multi-match"
	nuggets: list[InformationNugget]
	not_a_match: None

	def to_json(self):
		return {"message": self.message, "nuggets": [convert_to_nugget(nugget).to_json() for nugget in self.nuggets], "not_a_match": convert_to_nugget(self.not_a_match).to_json() if self.not_a_match is not None else None}


@dataclass
class NoMatchFeedback:
	message = "no-match-in-document"
	nugget: InformationNugget
	not_a_match: InformationNugget

	def to_json(self):
		return {"message": self.message, "nugget": convert_to_nugget(self.nugget).to_json(),
				"not_a_match": convert_to_nugget(self.not_a_match).to_json() if self.not_a_match is not None else None}
	

@dataclass
class StopMatching:
	message = "stop-interactive-matching"

	def to_json(self):
		return {"message": self.message}
	

@dataclass
class DoAttributeRanking:
	message = "start-ranking"

	def to_json(self):
		return {
			"message": self.message,
			"do-attribute": True,
		}
	
@dataclass
class SkipAttributeRanking:
	message = "skip-ranking"

	def to_json(self):
		return {
			"message": self.message,
			"do-attribute": False,
		}
	
class ReloadDocumentBase:
	message = "reload-document-base"

	def to_json(self):
		return {"message": self.message}

class StopMatching:
	message = "stop-interactive-matching"

	def to_json(self):
		return {"message": self.message}


def decode_feedback(payload):
	message = payload.get("message")
	if message == "custom-match":
		return CustomMatchFeedback(payload["document"], payload["start"], payload["end"])
	if message == "is-match":
		return NuggetMatchFeedback(payload["nugget"], payload.get("not_a_match"))
	if message == "multi-match":
		return MultiNuggetsMatchFeedback(payload["nuggets"], payload.get("not_a_match"))
	if message == "no-match-in-document":
		return NoMatchFeedback(payload["nugget"], payload.get("not_a_match"))
	classes = {"stop-interactive-matching": StopMatching, "start-ranking": DoAttributeRanking,
		"skip-ranking": SkipAttributeRanking, "reload-document-base": ReloadDocumentBase}
	if message in classes:
		return classes[message]()
	raise ValueError("Unsupported feedback message")


class _SnapshotCache:
	def __init__(self, values):
		self.values = values

	def get(self, key):
		return self.values.get(key)


class _MatchFeedback(Emitable):
	def _session(self):
		scope = get_signal_scope()
		if scope is None:
			raise ValueError("A feedback session is required")
		return SessionState(scope["user_id"], scope["base_id"], scope["session_id"])

	def claim(self):
		return self._session().claim()

	@property
	def msg(self):
		command = self.claim()
		return decode_feedback(command["payload"]) if command is not None else None

	def to_json(self):
		# Status reads must never consume commands.
		return {}

	def emit(self, status):
		if status is None:
			return None
		payload = status if isinstance(status, dict) else status.to_json()
		scope = get_signal_scope()
		if scope is None:
			raise ValueError("A feedback session is required")
		return self._session().enqueue(scope["command_id"], scope["expected_version"], payload)


class _State(Emitable):

	def to_json(self):
		msg = self.msg
		if msg is None:
			return ""
		return msg.decode("utf-8")

	def emit(self, status: str):
		self.redis.set(self.type, status)


class _Signal(Emitable):

	def to_json(self):
		return str(self.msg)

	def emit(self, status: float):
		self.redis.set(self.type, str(status))


class _Error(Emitable):

	def to_json(self):
		msg = self.msg
		if msg is None:
			return ""
		return msg.decode("utf-8")

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
		msg = self.msg
		if msg is None:
			return {}
		return convert_to_nuggets(msg).to_json()

	def emit(self, status: list[InformationNugget]):
		logger.info("emitting Nuggets")
		b:bytes = pickle.dumps(status)
		if isinstance(b,bytes):
			self.redis.set(self.type, b)
		elif len(status)< 2:
			raise TypeError("status smaller than 2")
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
		msg = self.msg
		if msg is None:
			return {}
		return convert_to_document_base(msg).to_json()

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
		msg = self.msg
		if msg is None:
			return {}
		return json.loads(msg)

	def emit(self, status: dict[str, Any]):
		# Preserve the matcher-owned request; change annotations are desktop-only.
		status = status.copy()
		status.pop("nugget-updates-context", None)
		for key, value in status.items():
			if isinstance(value, Attribute):
				status[key] = value.toJSON()
			if isinstance(value, Iterable) and not isinstance(value, str):
				if all(isinstance(item, InformationNugget) for item in value):
					status[key] = [convert_to_nugget(item).to_json() for item in value]
		self.redis.set(self.type, json.dumps(status))


class _Dump(Emitable):

	def to_json(self):
		return self.msg

	def emit(self, status):
		self.redis.set(self.type, json.dumps(status))
