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
from wannadb_web.worker.payload import compact_base, encode_base

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
	text: str
	signals: dict[str, BaseSignal]
	document: Document
	end_char: int
	start_char: int
	nugget_id: Optional[int] = None

	def to_json(self):
		data = {
			"text": self.text,
			"signals": [{"name": name, "signal": convert_signal(signal).to_json()}
				for name, signal in self.signals.items()],
			"document": {"name": self.document.name, "text": self.document.text},
			"end_char": int(self.end_char),
			"start_char": int(self.start_char)
		}
		if self.nugget_id is not None:
			data["id"] = self.nugget_id
		return data


def convert_to_nugget(nugget: InformationNugget, nugget_id: Optional[int] = None):
	return _InformationNugget(nugget.text, nugget.signals, nugget.document,
		nugget.end_char, nugget.start_char, nugget_id)


@dataclass
class _Document:
	name:str
	text:str
	attribute_mappings: dict[str,list[InformationNugget]]
	signals:dict[str,BaseSignal]
	nuggets:list[InformationNugget]

	def to_json(self):
		nuggets = [convert_to_nugget(nugget, index).to_json() for index, nugget in enumerate(self.nuggets)]
		indices = {id(nugget): index for index, nugget in enumerate(self.nuggets)}
		return {
			"name": self.name,
			"text": self.text,
			"attribute_mappings": {name: [nuggets[indices[id(nugget)]] for nugget in matches]
				for name, matches in self.attribute_mappings.items()},
			"signals": [{"name": name, "signal": convert_signal(signal).to_json()}
				for name, signal in self.signals.items()],
			"nuggets": nuggets
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
	documents:list[Document]

	def to_json(self):
		documents = [convert_to_document(document).to_json() for document in self.documents]
		return {
			"attributes": [attribute.name for attribute in self.attributes],
			"nuggets": [nugget for document in documents for nugget in document["nuggets"]],
			"documents": documents
		}

def convert_to_document_base(document_base: DocumentBase):
	return _DocumentBase(document_base.attributes, document_base.documents)


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
				self.cache_db_to_ui.type: serialized(self.cache_db_to_ui) if include_payload else None
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
	not_a_match: Optional[InformationNugget] = None

	def to_json(self):
		return {"message": self.message, "document": convert_to_document(self.document).to_json(), "start": self.start,
				"end": self.end, "not_a_match": convert_to_nugget(self.not_a_match).to_json() if self.not_a_match is not None else None}


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
	nugget: Optional[InformationNugget]
	not_a_match: Optional[InformationNugget]
	document: Optional[Document] = None

	def to_json(self):
		if self.document is not None:
			return {"message": self.message, "document": {"name": self.document.name, "text": self.document.text}}
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
	reset: bool = False

	def to_json(self):
		return {
			"message": self.message,
			"do-attribute": True,
			"reset": self.reset,
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



class _SnapshotCache:
	def __init__(self, values):
		self.values = values

	def get(self, key):
		return self.values.get(key)



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


class _DocumentBaseToUi(Emitable):

	def to_json(self):
		raw = self.redis.get(self.type)
		if raw is None:
			return {}
		if raw.startswith(b"{"):
			return json.loads(raw)
		return compact_base(pickle.loads(raw))

	def emit(self, status: DocumentBase, document_ids=None):
		self.redis.set(self.type, encode_base(status, document_ids))


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
		self.redis.set(self.type, encode_feedback_request(status))


def encode_feedback_request(status: dict[str, Any], *, compact=False):
	# Preserve the matcher-owned request; change annotations are desktop-only.
	status = status.copy()
	status.pop("nugget-updates-context", None)
	if compact:
		status.pop("all-guessed-nugget-matches", None)
	nugget_ids = {}

	def serialize_nugget(nugget):
		document_key = id(nugget.document)
		if document_key not in nugget_ids:
			nugget_ids[document_key] = {id(candidate): index
				for index, candidate in enumerate(nugget.document.nuggets)}
		index = nugget_ids[document_key].get(id(nugget))
		if compact and index is not None:
			return {"document": {"name": nugget.document.name}, "id": index}
		return convert_to_nugget(nugget, index).to_json()

	for key, value in status.items():
		if isinstance(value, Attribute):
			status[key] = value.toJSON()
		if isinstance(value, Iterable) and not isinstance(value, str):
			if all(isinstance(item, InformationNugget) for item in value):
				status[key] = [serialize_nugget(item) for item in value]
	return json.dumps(status)


class _Dump(Emitable):

	def to_json(self):
		return self.msg

	def emit(self, status):
		self.redis.set(self.type, json.dumps(status))
