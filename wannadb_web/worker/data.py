"""Web signal adapters, legacy serialization DTOs and feedback command payloads."""
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
	"""Legacy web signal DTO containing an identifier and display value."""
	identifier:str
	signal:str

	def to_json(self):
		"""Serialize base signal into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {
			"identifier": self.identifier,
			"signal":self.signal
		}

def convert_signal(signal: BaseSignal) -> _BaseSignal:
	"""Adapt a shared signal to its legacy web display DTO.

	:param signal: The signal object to serialize or read.
	:type signal: BaseSignal
	:returns: The convert signal result.
	:rtype: _BaseSignal
	"""
	return _BaseSignal(identifier=signal.identifier, signal=str(signal))

@dataclass
class _InformationNugget:
	"""Legacy nugget DTO with source reference and Unicode code-point offsets."""
	text: str
	signals: dict[str, BaseSignal]
	document: Document
	end_char: int
	start_char: int
	nugget_id: Optional[int] = None

	def to_json(self):
		"""Serialize information nugget into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
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
	"""Adapt a nugget while retaining its source reference, offsets and optional publication ID.

	:param nugget: The exact selected candidate or custom candidate text.
	:type nugget: InformationNugget
	:param nugget_id: Optional original candidate index in the publication.
	:type nugget_id: Optional[int]
	:returns: The convert to nugget result.
	:rtype: _InformationNugget
	"""
	return _InformationNugget(nugget.text, nugget.signals, nugget.document,
		nugget.end_char, nugget.start_char, nugget_id)


@dataclass
class _Document:
	"""Legacy document DTO preserving candidate references in attribute mappings."""
	name:str
	text:str
	attribute_mappings: dict[str,list[InformationNugget]]
	signals:dict[str,BaseSignal]
	nuggets:list[InformationNugget]

	def to_json(self):
		"""Serialize document into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
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
	"""Adapt a source document without changing its mapping/nugget identities.

	:param document: The selected domain document or serialized source record.
	:type document: Document
	:returns: The convert to document result.
	:rtype: _Document
	"""
	return _Document(document.name,document.text,document.attribute_mappings, document.signals,document.nuggets)


@dataclass
class _Attribute:
	"""Legacy attribute DTO with its display name."""
	name:str
	signals = "not_implemented"

	def to_json(self):
		"""Serialize attribute into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {
			"name": self.name,
			"signals": self.signals
		}

def convert_to_attribute(attribute: Attribute):
	"""Adapt an attribute name for the legacy web transport.

	:param attribute: The selected attribute name or domain attribute, as required here.
	:type attribute: Attribute
	:returns: The convert to attribute result.
	:rtype: _Attribute
	"""
	return _Attribute(attribute.name)


@dataclass
class _DocumentBase:
	"""Legacy base DTO for attributes, documents and candidate publications."""
	attributes:list[Attribute]
	documents:list[Document]

	def to_json(self):
		"""Serialize document base into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		documents = [convert_to_document(document).to_json() for document in self.documents]
		return {
			"attributes": [attribute.name for attribute in self.attributes],
			"nuggets": [nugget for document in documents for nugget in document["nuggets"]],
			"documents": documents
		}

def convert_to_document_base(document_base: DocumentBase):
	"""Adapt base attributes and documents for the legacy web transport.

	:param document_base: The worker-local domain base.
	:type document_base: DocumentBase
	:returns: The convert to document base result.
	:rtype: _DocumentBase
	"""
	return _DocumentBase(document_base.attributes, document_base.documents)


class Signals:
	"""Session-scoped adapters for worker status, errors and atomic UI publications."""
	def __init__(self, user_id: str, base_id: Optional[int] = None, session_id: Optional[str] = None):
		"""Initialize Signals with its supplied dependencies and scope.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: str
		:param base_id: The selected document-base database ID.
		:type base_id: Optional[int]
		:param session_id: The parent feedback-session UUID.
		:type session_id: Optional[str]
		"""
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
		"""Serialize signals into its web transport representation.

		:param include_payload: Whether to include the document-base publication.
		:type include_payload: bool
		:param include_feedback: Whether to include the feedback-request publication.
		:type include_feedback: bool
		:param snapshot: The encoded canonical BSON snapshot.
		:type snapshot: bytes | None
		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, Any]
		"""
		if snapshot is None and self.__session is not None:
			snapshot = self.__session.snapshot(include_payload=include_payload, include_feedback=include_feedback)
		def serialized(signal):
			"""Decode a signal from the same atomic publication snapshot as its siblings.

			:param signal: The signal object to serialize or read.
			:type signal: BaseSignal | Emitable
			:returns: The serialized result.
			:rtype: object
			"""
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
		"""Initialize this task session without erasing unrelated reviewers' command state.
		"""
		scope = get_signal_scope()
		if self.__session is not None:
			self.__session.initialize()
		elif scope is not None:
			SessionState.current(self.__user_id).initialize()


class Emitable(abc.ABC):

	"""Abstract cached signal interface implemented by web publication adapters."""
	def __init__(self, emitable_type: str, user_id: str):
		"""Initialize Emitable with its supplied dependencies and scope.

		:param emitable_type: The cached signal/publication channel name.
		:type emitable_type: str
		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: str
		"""
		self.type = emitable_type
		self.redis = RedisCache(user_id)

	@property
	def msg(self):
		"""Read the current msg from this scoped adapter.

		:returns: The msg result.
		:rtype: bytes | None
		"""
		msg = self.redis.get(self.type)
		if msg is None:
			return None
		return msg

	@abstractmethod
	def to_json(self):
		"""Serialize emitable into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: object
		"""
		raise NotImplementedError

	@abstractmethod
	def emit(self, status: Any):
		"""Publish the emitable value in the current user/base/session namespace.

		:param status: The state, HTTP status or emitted value required here.
		:type status: Any
		:returns: The emit result.
		:rtype: object
		"""
		raise NotImplementedError


@dataclass
class CustomMatchFeedback:
	"""An explicit custom span and optional negative candidate decision."""
	message = "custom-match"
	document: Document
	start: int
	end: int
	not_a_match: Optional[InformationNugget] = None

	def to_json(self):
		"""Serialize custom match feedback into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {"message": self.message, "document": convert_to_document(self.document).to_json(), "start": self.start,
				"end": self.end, "not_a_match": convert_to_nugget(self.not_a_match).to_json() if self.not_a_match is not None else None}


@dataclass
class NuggetMatchFeedback:
	"""An existing candidate match and optional negative candidate decision."""
	message = "is-match"
	nugget: InformationNugget
	not_a_match: None

	def to_json(self):
		"""Serialize nugget match feedback into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {"message": self.message, "nugget": convert_to_nugget(self.nugget).to_json(), "not_a_match": convert_to_nugget(self.not_a_match).to_json() if self.not_a_match is not None else None}


@dataclass
class MultiNuggetsMatchFeedback:
	"""A batch of one selected candidate per document."""
	message = "multi-match"
	nuggets: list[InformationNugget]
	not_a_match: None

	def to_json(self):
		"""Serialize multi nuggets match feedback into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {"message": self.message, "nuggets": [convert_to_nugget(nugget).to_json() for nugget in self.nuggets], "not_a_match": convert_to_nugget(self.not_a_match).to_json() if self.not_a_match is not None else None}


@dataclass
class NoMatchFeedback:
	"""A candidate rejection or an explicit whole-document No Match decision."""
	message = "no-match-in-document"
	nugget: Optional[InformationNugget]
	not_a_match: Optional[InformationNugget]
	document: Optional[Document] = None

	def to_json(self):
		"""Serialize no match feedback into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		if self.document is not None:
			return {"message": self.message, "document": {"name": self.document.name, "text": self.document.text}}
		return {"message": self.message, "nugget": convert_to_nugget(self.nugget).to_json(),
				"not_a_match": convert_to_nugget(self.not_a_match).to_json() if self.not_a_match is not None else None}
	

@dataclass
class StopMatching:
	"""Command payload for stopping the current attribute."""
	message = "stop-interactive-matching"

	def to_json(self):
		"""Serialize stop matching into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {"message": self.message}
	

@dataclass
class DoAttributeRanking:
	"""Command payload for starting or resetting the waiting attribute."""
	message = "start-ranking"
	reset: bool = False

	def to_json(self):
		"""Serialize do attribute ranking into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {
			"message": self.message,
			"do-attribute": True,
			"reset": self.reset,
		}
	
@dataclass
class SkipAttributeRanking:
	"""Command payload for skipping the waiting attribute."""
	message = "skip-ranking"

	def to_json(self):
		"""Serialize skip attribute ranking into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {
			"message": self.message,
			"do-attribute": False,
		}
	
class ReloadDocumentBase:
	"""Command payload for refreshing the current matching step."""
	message = "reload-document-base"

	def to_json(self):
		"""Serialize reload document base into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {"message": self.message}

class StopMatching:
	"""Command payload for stopping the current attribute."""
	message = "stop-interactive-matching"

	def to_json(self):
		"""Serialize stop matching into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {"message": self.message}



class _SnapshotCache:
	"""Read-only adapter over one atomic Redis publication snapshot."""
	def __init__(self, values):
		"""Initialize _SnapshotCache with its supplied dependencies and scope.

		:param values: The values supplied to the scoped cache operation.
		:type values: tuple[object, ...]
		"""
		self.values = values

	def get(self, key):
		"""Read a raw cached channel from the previously captured atomic snapshot.

		:param key: The cache key within the already selected namespace.
		:type key: str
		:returns: The get result.
		:rtype: bytes | None
		"""
		return self.values.get(key)



class _State(Emitable):

	"""UTF-8 text state backed by a scoped Redis value."""
	def to_json(self):
		"""Serialize state into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: str
		"""
		msg = self.msg
		if msg is None:
			return ""
		return msg.decode("utf-8")

	def emit(self, status: str):
		"""Publish the state value in the current user/base/session namespace.

		:param status: The state, HTTP status or emitted value required here.
		:type status: str
		"""
		self.redis.set(self.type, status)


class _Signal(Emitable):

	"""Legacy scalar signal backed by a scoped Redis value."""
	def to_json(self):
		"""Serialize signal into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: str
		"""
		return str(self.msg)

	def emit(self, status: float):
		"""Publish the signal value in the current user/base/session namespace.

		:param status: The state, HTTP status or emitted value required here.
		:type status: float
		"""
		self.redis.set(self.type, str(status))


class _Error(Emitable):

	"""Cached safe worker error code/message exposed to task polling."""
	def to_json(self):
		"""Serialize error into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: str
		"""
		msg = self.msg
		if msg is None:
			return ""
		return msg.decode("utf-8")

	def emit(self, exception: BaseException):
		"""Publish the error value in the current user/base/session namespace.

		:param exception: The worker failure to classify without exposing sensitive details.
		:type exception: BaseException
		"""
		self.redis.set(self.type, str(exception))


class _DocumentBaseToUi(Emitable):

	"""Compact JSON base publications with compatibility for old cached values."""
	def to_json(self):
		"""Serialize document base to ui into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		raw = self.redis.get(self.type)
		if raw is None:
			return {}
		if raw.startswith(b"{"):
			return json.loads(raw)
		return compact_base(pickle.loads(raw))

	def emit(self, status: DocumentBase, document_ids=None):
		"""Publish the document base to ui value in the current user/base/session namespace.

		:param status: The state, HTTP status or emitted value required here.
		:type status: DocumentBase
		:param document_ids: The selected source IDs or publication name-to-ID map.
		:type document_ids: list[int] | dict[str, int] | None
		"""
		self.redis.set(self.type, encode_base(status, document_ids))


class _Statistics(Emitable):

	"""Legacy statistics adapter that currently publishes an empty statistics view."""
	@property
	def msg(self):
		"""Return the legacy not-implemented statistics placeholder.

		:returns: The msg text or identifier.
		:rtype: str
		"""
		return "not implemented"

	def to_json(self):
		"""Return the empty serializable statistics view currently supported by the web adapter.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return Statistics(False).to_serializable()

	def emit(self, statistic: Statistics):
		"""Ignore statistics emission in the current legacy web adapter.

		:param statistic: The statistics value supplied to the legacy adapter.
		:type statistic: Statistics
		"""
		pass


class _Feedback(Emitable):

	"""JSON feedback request/response adapter backed by scoped cache state."""
	def to_json(self):
		"""Serialize feedback into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		msg = self.msg
		if msg is None:
			return {}
		return json.loads(msg)

	def emit(self, status: dict[str, Any]):
		"""Publish the feedback value in the current user/base/session namespace.

		:param status: The state, HTTP status or emitted value required here.
		:type status: dict[str, Any]
		"""
		self.redis.set(self.type, encode_feedback_request(status))


def encode_feedback_request(status: dict[str, Any], *, compact=False):
	# Preserve the matcher-owned request; change annotations are desktop-only.
	"""Serialize a feedback request with compact or legacy candidate references.

	:param status: The state, HTTP status or emitted value required here.
	:type status: dict[str, Any]
	:param compact: Whether candidate references omit repeated source text.
	:type compact: bool
	:returns: The encode feedback request text or identifier.
	:rtype: str
	"""
	status = status.copy()
	status.pop("nugget-updates-context", None)
	if compact:
		status.pop("all-guessed-nugget-matches", None)
	nugget_ids = {}

	def serialize_nugget(nugget):
		"""Serialize a candidate using its original publication index and source identity.

		:param nugget: The exact selected candidate or custom candidate text.
		:type nugget: InformationNugget | str
		:returns: The serialize nugget mapping.
		:rtype: dict[str, object]
		"""
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

	"""Legacy raw cache-dump publication adapter."""
	def to_json(self):
		"""Serialize dump into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: bytes | None
		"""
		return self.msg

	def emit(self, status):
		"""Publish the dump value in the current user/base/session namespace.

		:param status: The state, HTTP status or emitted value required here.
		:type status: str | int | object
		"""
		self.redis.set(self.type, json.dumps(status))
