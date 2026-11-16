import csv
import io
import json
import logging
import time
from typing import Optional, Any

from bson import decode, encode

import wannadb
from wannadb import resources
from wannadb.configuration import Pipeline
from wannadb.data.data import Attribute, Document, DocumentBase, InformationNugget
from wannadb.data.signals import CachedDistanceSignal, LabelEmbeddingSignal, SentenceStartCharsSignal
from wannadb.interaction import EmptyInteractionCallback
from wannadb.matching.distance import SignalsMeanDistance
from wannadb.matching.matching import RankingBasedMatcher
from wannadb.preprocessing.embedding import BERTContextSentenceEmbedder, RelativePositionEmbedder, \
	SBERTTextEmbedder, SBERTLabelEmbedder
from wannadb.preprocessing.extraction import StanzaNERExtractor, SpacyNERExtractor
from wannadb.preprocessing.label_paraphrasing import OntoNotesLabelParaphraser, \
	SplitAttributeNameLabelParaphraser
from wannadb.preprocessing.normalization import CopyNormalizer
from wannadb.preprocessing.other_processing import ContextSentenceCacher
from wannadb.statistics import Statistics
from wannadb.status import StatusCallback
from wannadb_web.SQLite.Cache_DB import SQLiteCacheDBWrapper
from wannadb_web.postgres.queries import get_document_base_snapshot, get_document_by_name_and_content, compare_and_swap_document_content, \
	get_document, get_document_ids_for_snapshot
from wannadb_web.postgres.transactions import DocumentBaseCreationConflict, create_document_base_with_snapshot, mutate_base_documents
from wannadb_web.limits import validate_attribute_count, validate_corpus
from wannadb_web.Redis.RedisCache import SessionState, get_signal_scope
from wannadb_web.postgres.feedback_sessions import FeedbackSessionConflict, FeedbackSnapshotConflict, load_session, save_session
from wannadb_web.worker.custom_match_extraction import WebMatchPropagation
from wannadb_web.worker.data import Signals, encode_feedback_request
from wannadb_web.worker.payload import encode_base
from wannadb_web.worker.feedback_reconciliation import (
	clear_replaced_decisions, compact_proposal, compare_feedback, conflict_review, observe_documents, proposed_previews,
)

logger = logging.getLogger(__name__)

INPUT_DOCS_COLUMN_NAME = "input_document"
_MATCHING_COMMIT_ATTEMPTS = 3


class WannaDB_WebAPI:

	def __init__(self, user_id: int, document_base_name: str, organisation_id: int, build_query_cache: bool = True):
		self._document_id: Optional[int] = None
		self._document_base: Optional[DocumentBase] = None
		self.user_id = user_id
		self._feedback: Optional[dict[str, Any]] = None
		self._expected_bson: Optional[bytes] = None
		self._attribute_schema_version: Optional[str] = None
		self.matching_step_saved = False
		self.session = SessionState.current(user_id)

		self.signals = Signals(str(self.user_id))
		self.sqLiteCacheDBWrapper = SQLiteCacheDBWrapper(user_id, db_file=":memory:") if build_query_cache else None
		self.document_base_name = document_base_name
		self.organisation_id = organisation_id

		def status_callback_fn(message, progress):
			self.signals.status.emit(str(message) + " " + str(progress))

		self.status_callback = StatusCallback(status_callback_fn)

		if wannadb.resources.MANAGER is None:
			self.signals.error.emit(Exception("Resource Manager not initialized!"))
			raise Exception("Resource Manager not initialized!")
		if self.sqLiteCacheDBWrapper is not None and self.sqLiteCacheDBWrapper.cache_db.conn is None:
			self.signals.error.emit(Exception("Cache db could not be initialized!"))
			raise Exception("Cache db could not be initialized!")
		logger.info("WannaDB_WebAPI initialized")

	@property
	def feedback(self):
		if self._feedback is None:
			raise Exception("Feedback is not set!")
		return self._feedback

	@feedback.setter
	def feedback(self, value: dict):
		self._feedback = value

	@property
	def document_id(self):
		if self._document_id is None:
			raise Exception("Document ID not set!")
		return self._document_id

	@document_id.setter
	def document_id(self, value: int):
		self._document_id = value

	@property
	def document_base(self):
		if self._document_base is None:
			raise Exception("Document base not loaded!")
		return self._document_base

	@document_base.setter
	def document_base(self, value: DocumentBase):
		if not isinstance(value, DocumentBase):
			raise TypeError("Document base must be of type DocumentBase!")
		self._document_base = value
		self._stage_document_base(value)
		return

	def get_ordert_nuggets(self, document_id: int):
		logger.warning("get_ordert_nuggets is deprecated, use get_ordered_nuggets_by_doc_name instead!")
		document = get_document(document_id, self.user_id, self.organisation_id, self.document_base_name)
		if document[0] is None:
			self.signals.error.emit(RuntimeError("Document not found."))
			return
		document_name = document[0]
		logger.debug("get_ordert_nuggets")
		self.signals.status.emit("get_ordert_nuggets")
		for document in self.document_base.documents:
			if document.name == document_name:
				self.signals.ordert_nuggets.emit(list(sorted(document.nuggets, key=lambda x: x[CachedDistanceSignal])))
				return
		self.signals.error.emit(RuntimeError("Document not found in the base."))

	def get_ordered_nuggets_by_doc_name(self, document_name: str, document_content: str):
		logger.warning("It is recommended to not use get_ordered_nuggets_by_doc_name!")
		document = get_document_by_name_and_content(document_name, document_content, self.user_id,
			organisation_id=self.organisation_id, base_name=self.document_base_name)
		if document[0] is None:
			self.signals.error.emit(RuntimeError("Document not found."))
			return
		logger.debug("get_ordered_nuggets_by_doc_name")
		self.signals.status.emit("get_ordered_nuggets_by_doc_name")
		for document in self.document_base.documents:
			if document.name == document_name:
				return
		self.signals.error.emit(RuntimeError("Document not found in the base."))

	def _report_error(self, code: str, error: Exception) -> None:
		logger.warning("Worker operation failed. code=%s error_type=%s", code, type(error).__name__)
		if self.signals.error.msg is None:
			self.signals.error.emit(RuntimeError(code))

	def create_document_base(self, source_documents: list[tuple[int, str, str]],
			attributes: list[Attribute], statistics: Statistics) -> int:
		started = time.monotonic()
		try:
			documents = [Document(name, content) for _, name, content in source_documents]
			document_base = DocumentBase(documents, attributes)
			if not document_base.validate_consistency():
				raise ValueError("Document base is inconsistent.")
			self._preprocess(document_base, statistics)
			serialized = document_base.to_bson()
		except Exception as error:
			self._report_error("CREATE_FAILED", error)
			raise

		self.signals.status.emit("Saving document base.")
		try:
			base_id, _ = create_document_base_with_snapshot(
				self.document_base_name, [attribute.name for attribute in attributes],
				self.organisation_id, source_documents, self.user_id, serialized)
		except DocumentBaseCreationConflict as error:
			self._report_error("CREATE_CONFLICT", error)
			raise
		except PermissionError as error:
			self._report_error("CREATE_ACCESS_DENIED", error)
			raise
		except ValueError as error:
			self._report_error("CREATE_INPUT_CHANGED", error)
			raise
		except Exception as error:
			self._report_error("CREATE_FAILED", error)
			raise
		logger.info("Document base creation committed. duration_seconds=%.3f", time.monotonic() - started)
		return base_id

	def _preprocess(self, document_base: DocumentBase, statistics: Statistics):
		validate_corpus(document.text for document in document_base.documents)
		validate_attribute_count(len(document_base.attributes))
		# load default preprocessing phase
		self.signals.status.emit("Loading preprocessing phase...")

		# noinspection PyTypeChecker
		preprocessing_phase = Pipeline([
			StanzaNERExtractor(),
			SpacyNERExtractor("SpacyEnCoreWebLg"),
			ContextSentenceCacher(),
			CopyNormalizer(),
			OntoNotesLabelParaphraser(),
			SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
			SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
			SBERTTextEmbedder("SBERTBertLargeNliMeanTokensResource"),
			BERTContextSentenceEmbedder("BertLargeCasedResource"),
			RelativePositionEmbedder()
		])

		preprocessing_phase(document_base, EmptyInteractionCallback(), self.status_callback, statistics)

	def load_document_base_from_bson(self, *, publish_to_ui=True):
		logger.debug("Loading document base snapshot.")
		try:
			if self.sqLiteCacheDBWrapper is not None:
				self.sqLiteCacheDBWrapper.reset_cache_db()

			scope = get_signal_scope()
			snapshot = get_document_base_snapshot(self.document_base_name, scope["base_id"],
				self.organisation_id, self.user_id, include_attribute_schema=True)
			if snapshot is None:
				self.signals.error.emit(RuntimeError("Document base snapshot not found."))
				return

			document_id, document, self._attribute_schema_version, _ = snapshot
			document_base = DocumentBase.from_bson(document)
			if self.sqLiteCacheDBWrapper is not None:
				for attribute in document_base.attributes:
					self.sqLiteCacheDBWrapper.create_attribute_table(attribute.name)
				self.sqLiteCacheDBWrapper.cache_db.create_input_docs_table(INPUT_DOCS_COLUMN_NAME, document_base.documents)

			self._document_base = document_base
			if publish_to_ui:
				self._stage_document_base(document_base)
			self.document_id = document_id
			self._expected_bson = document
		except Exception as error:
			self._report_error("BASE_LOAD_FAILED", error)
			raise

	def update_document_base_to_bson(self, *, update_attributes=False):
		if self._document_id is None or self._expected_bson is None:
			self.signals.error.emit(RuntimeError("PERSISTENCE_FAILED"))
			raise RuntimeError("Document base has no persistence snapshot")
		serialized = self.document_base.to_bson()
		scope = get_signal_scope()
		metadata = {"attributes": [attribute.name for attribute in self.document_base.attributes]} if update_attributes else {}
		status = compare_and_swap_document_content(self.document_id, serialized, self._expected_bson,
			self.organisation_id, self.user_id, scope["base_id"],
			expected_attribute_version=self._attribute_schema_version, **metadata)
		if not status:
			self.signals.error.emit(RuntimeError("STALE_BASE"))
			raise RuntimeError("The base changed or access was lost; reload before editing again.")
		self._expected_bson = serialized
		self.signals.status.emit("Changes saved.")

	def _document_ids(self, base):
		return get_document_ids_for_snapshot(self.session.base_id, self.organisation_id, self.user_id,
			{document.name: document.text for document in base.documents})

	def _stage_document_base(self, base):
		self.signals.document_base_to_ui.emit(base, self._document_ids(base))

	def complete_session(self):
		self._stage_document_base(self.document_base)
		self.session.close()

	# todo: below not implemented yet
	def save_table_to_csv(self):
		logger.debug("Called function 'save_table_to_csv'.")

		try:
			buffer = io.StringIO()

			# check that the table is complete
			for attribute in self.document_base.attributes:
				for document in self.document_base.documents:
					if attribute.name not in document.attribute_mappings.keys():
						logger.error("Cannot save a table with unpopulated attributes!")
						self.signals.error.emit(
							Exception("Cannot save a table with unpopulated attributes!"))

			# TODO: currently stores the text of the first matching nugget (if there is one)
			table_dict = self.document_base.to_table_dict("text")
			headers = list(table_dict.keys())
			rows = []
			for ix in range(len(table_dict[headers[0]])):
				row = []
				for header in headers:
					if header == "document-name":
						row.append(table_dict[header][ix])
					elif not table_dict[header][ix]:
						row.append(None)
					else:
						row.append(table_dict[header][ix][0])  # type: ignore
				rows.append(row)
				writer = csv.writer(buffer, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL)
				writer.writerow(headers)
				writer.writerows(rows)
		except Exception as error:
			self._report_error("TABLE_EXPORT_FAILED", error)
			raise

	def mutate_documents(self, *, additions=(), replacement=None, removal=None):
		documents = list(additions)
		if replacement is not None:
			documents.append(replacement[2])
		scope = get_signal_scope()
		try:
			if documents:
				self._preprocess(DocumentBase(documents, []), Statistics(False))
			self.document_base = mutate_base_documents(self.document_base_name, scope["base_id"],
				self.organisation_id, self.user_id, additions=additions, replacement=replacement, removal=removal)
		except PermissionError as error:
			self._report_error("STALE_BASE", error)
			raise
		except Exception as error:
			self._report_error("PERSISTENCE_FAILED", error)
			raise
		self.signals.status.emit("Changes saved.")

	def add_attributes(self, attributes: list[Attribute]):
		existing = {attribute.name for attribute in self.document_base.attributes}
		self.update_attributes(self.document_base.attributes + [
			attribute for attribute in attributes if attribute.name not in existing
		])

	def remove_attributes(self, attributes: list[Attribute]):
		names = {attribute.name for attribute in attributes}
		remaining = [attribute for attribute in self.document_base.attributes if attribute.name not in names]
		if len(self.document_base.attributes) - len(remaining) != len(names):
			raise ValueError("Attribute name does not exist!")
		self.update_attributes(remaining)

	def update_attributes(self, attributes: list[Attribute]):
		validate_attribute_count(len(attributes))
		existing = {attribute.name: attribute for attribute in self.document_base.attributes}
		names = {attribute.name for attribute in attributes}
		for document in self.document_base.documents:
			for removed in document.attribute_mappings.keys() - names:
				del document.attribute_mappings[removed]
		self.document_base.attributes[:] = [existing.get(attribute.name, attribute) for attribute in attributes]

	def forget_matches_for_attribute(self, attribute: Attribute):
		logger.debug("Called function 'forget_matches_for_attribute'.")

		self.sqLiteCacheDBWrapper.delete_attribute_table(attribute.name)
		try:
			if attribute in self.document_base.attributes:
				for document in self.document_base.documents:
					if attribute.name in document.attribute_mappings.keys():
						del document.attribute_mappings[attribute.name]
				self.signals.status.emit("Matches forgotten.")
				self._stage_document_base(self.document_base)
			else:
				logger.error("Attribute name does not exist!")
				self.signals.error.emit(Exception("Attribute name does not exist!"))
		except Exception as error:
			self._report_error("RESET_FAILED", error)
			raise

	def forget_matches(self):
		logger.debug("Called function 'forget_matches'.")
		for attribute in self.document_base.attributes:
			self.sqLiteCacheDBWrapper.delete_attribute_table(attribute.name)
			self.sqLiteCacheDBWrapper.create_attribute_table(attribute.name)
		try:
			for document in self.document_base.documents:
				document.attribute_mappings.clear()
			self._stage_document_base(self.document_base)
			self.signals.finished.emit(1)
		except Exception as error:
			self._report_error("RESET_FAILED", error)
			raise

	## todo: below not implemented yet

	def save_statistics_to_json(self):
		logger.debug("Called function 'save_statistics_to_json'.")
		try:
			return json.dumps(self.signals.statistics.to_json(), indent=2)
		except Exception as error:
			self._report_error("STATISTICS_EXPORT_FAILED", error)
			raise

	@staticmethod
	def _matcher(propagation=None):
		return RankingBasedMatcher(
			distance=SignalsMeanDistance(signal_identifiers=[
				"LabelEmbeddingSignal", "TextEmbeddingSignal", "ContextSentenceEmbeddingSignal", "RelativePositionSignal",
			]),
			max_num_feedback=100,
			len_ranked_list=10,
			max_distance=0.2,
			num_random_docs=1,
			sampling_mode="AT_MAX_DISTANCE_THRESHOLD",
			adjust_threshold=True,
			nugget_pipeline=Pipeline([
				ContextSentenceCacher(), CopyNormalizer(), OntoNotesLabelParaphraser(),
				SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
				SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
				SBERTTextEmbedder("SBERTBertLargeNliMeanTokensResource"),
				BERTContextSentenceEmbedder("BertLargeCasedResource"),
				RelativePositionEmbedder(),
			]),
			find_additional_nuggets=propagation if propagation is not None else WebMatchPropagation(),
			allow_manual_without_candidates=True,
			suggestion_provenance=True,
		)

	def add_automatic_matches_for_preview(self):
		self._matcher().add_automatic_matches_for_preview(self.document_base, Statistics(False))

	def _prepare_matching_base(self, interaction, statistics):
		# Older add/edit tasks could save raw documents without preprocessing.
		raw_documents = [document for document in self.document_base.documents
			if SentenceStartCharsSignal.identifier not in document.signals]
		if raw_documents:
			self._preprocess(DocumentBase(raw_documents, []), statistics)

		Pipeline([
			SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
			ContextSentenceCacher(),
			SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
		])(self.document_base, interaction, self.status_callback, statistics)

	def start_interactive_table_population(self):
		"""Prepare one session and return as soon as it needs a reviewer."""
		try:
			self.signals.status.emit("Preparing feedback session.")
			for attempt in range(_MATCHING_COMMIT_ATTEMPTS):
				if attempt:
					self.load_document_base_from_bson(publish_to_ui=False)
					if self.signals.error.msg is not None:
						raise FeedbackSessionConflict("The document base could not be reloaded.")
				validate_corpus(document.text for document in self.document_base.documents)
				validate_attribute_count(len(self.document_base.attributes))
				interaction, statistics = EmptyInteractionCallback(), Statistics(False)
				self._prepare_matching_base(interaction, statistics)
				matcher = self._matcher()
				checkpoint, request = matcher.advance(self.document_base, interaction, self.status_callback, statistics)
				try:
					self._save_matching_step(checkpoint, request, matcher.identifier)
					return
				except FeedbackSnapshotConflict:
					continue
			raise FeedbackSessionConflict("Other feedback is being saved. Open the attribute again.")
		except Exception as error:
			self._report_error("MATCHING_FAILED", error)
			raise

	def advance_interactive_table_population(self, current, command, payload, lease):
		"""Run one decision, retrying only a concurrent canonical snapshot commit."""
		propagation = WebMatchPropagation()
		for attempt in range(_MATCHING_COMMIT_ATTEMPTS):
			try:
				self._advance_matching_step(current, command, payload, lease, propagation)
				return
			except FeedbackSnapshotConflict:
				if attempt == _MATCHING_COMMIT_ATTEMPTS - 1:
					break
				latest = load_session(self.user_id, self.session.session_id, include_checkpoint=True)
				if (latest is None or latest["closed"] or latest["version"] != command["expected_version"] or
					latest["base_id"] != self.session.base_id):
					raise FeedbackSessionConflict("Feedback has changed or the session expired. Reopen the attribute.")
				current = latest
		raise FeedbackSessionConflict("Other feedback is being saved. Try your action again.")

	def _advance_matching_step(self, current, command, payload, lease, propagation):
		state = decode(current["checkpoint"])
		moved = current["snapshot_hash"] != current["live_snapshot_hash"]
		base = current["snapshot"] if moved else state.get("base", current["snapshot"])
		self._document_base = DocumentBase.from_bson(base, deduplicate_nuggets=False)
		self.document_id = current["snapshot_id"]
		self._attribute_schema_version = current["attribute_schema_version"]
		interaction, statistics = EmptyInteractionCallback(), Statistics(False)
		if moved:
			validate_corpus(document.text for document in self.document_base.documents)
			validate_attribute_count(len(self.document_base.attributes))
		needs_preparation = moved and (
			any(SentenceStartCharsSignal.identifier not in document.signals for document in self.document_base.documents)
			or any(LabelEmbeddingSignal.identifier not in item.signals
				for item in [*self.document_base.attributes, *self.document_base.nuggets])
		)
		if needs_preparation:
			self._prepare_matching_base(interaction, statistics)
		else:
			# Context sentences are deliberately ephemeral. Rebuild them after BSON restore.
			ContextSentenceCacher()(self.document_base, interaction, self.status_callback, statistics)

		decision, conflict, replacing = self._reconcile_matching_step(state, current, payload, moved)
		propagation.bind(self.document_base.documents, current["attribute"])
		matcher = self._matcher(propagation)
		checkpoint = state["matcher"]
		if replacing and decision is not None:
			clear_replaced_decisions(self.document_base, current["attribute"], decision)
		ranking = checkpoint["ranking"]
		empty_rank = ranking is not None and not ranking["remaining"]
		rebased = moved or state.get("conflict") is not None or conflict is not None or empty_rank
		if rebased:
			checkpoint, request = matcher.rebase(self.document_base, checkpoint, interaction, self.status_callback,
				statistics, keep_candidates=decision is not None, advance_if_empty=decision is None and conflict is None)
		if decision is not None or not rebased:
			checkpoint, request = matcher.advance(self.document_base, interaction, self.status_callback, statistics,
				checkpoint=checkpoint, feedback=decision)
		if conflict is not None:
			# Keep the original displayed span references for an explicit replacement.
			checkpoint = state["matcher"]
			request = dict(request)
			request.pop("do-attribute-request", None)
			request["review-conflict"] = conflict["review"]
		acknowledge = conflict is None and (payload["message"] != "reload-document-base" or replacing)
		self._save_matching_step(checkpoint, request, matcher.identifier, current=current, command=command, lease=lease,
			conflict=conflict, write_snapshot=decision is not None, record_receipt=acknowledge,
			propagation_limited=propagation.limited)

	def _reconcile_matching_step(self, state, current, payload, moved):
		attribute = current["attribute"]
		latest = observe_documents(self.document_base, attribute)
		baseline = state.get("observed")
		if baseline is None:
			if moved:
				raise FeedbackSessionConflict("The document base changed. Open a fresh feedback session.")
			baseline = latest
		pending = state.get("conflict")
		if pending is not None:
			if payload["message"] != "reload-document-base":
				raise FeedbackSessionConflict("Resolve the conflicting feedback before submitting another decision.")
			resolution = payload.get("conflict_resolution")
			if resolution == "keep":
				return None, None, False
			if resolution == "replace" and not pending["review"]["canReplace"]:
				raise FeedbackSessionConflict("This decision cannot replace the saved feedback. Keep the saved result.")
			proposal, previews = pending["proposal"], pending["previews"]
			names, decision, can_replace = compare_feedback(proposal, baseline, latest)
			if resolution == "replace" and not names:
				return decision, None, True
			names = list(dict.fromkeys([item["document"] for item in pending["review"]["items"]] + names))
			can_replace = can_replace and pending["review"]["canReplace"]
		elif payload["message"] == "reload-document-base":
			if payload.get("conflict_resolution") is not None:
				raise FeedbackSessionConflict("The feedback conflict has already been resolved.")
			return None, None, False
		else:
			names, decision, can_replace = compare_feedback(payload, baseline, latest)
			if not names:
				return decision, None, False
			proposal = compact_proposal(payload)
			previews = proposed_previews(payload, self.document_base)

		reset = proposal["message"] == "start-ranking" and proposal.get("reset") is True
		review = conflict_review(self.document_base, attribute, names, previews, can_replace=can_replace, reset=reset)
		return None, {"proposal": proposal, "previews": previews, "review": review}, False

	def _save_matching_step(self, checkpoint, request, identifier, *, current=None, command=None, lease=None,
			conflict=None, write_snapshot=False, record_receipt=True, propagation_limited=False):
		if request is None:
			phase, attribute, feedback_payload = "finished", None, None
		else:
			phase = "selection" if "do-attribute-request" in request else "ranking"
			attribute = request["attribute"].name
			feedback_payload = encode_feedback_request(dict(request, identifier=identifier), compact=True)
		document_payload = encode_base(self.document_base, self._document_ids(self.document_base))
		serialized = self.document_base.to_bson()
		canonical = self._expected_bson if current is None else current["snapshot"]
		new_snapshot = serialized if write_snapshot and serialized != canonical else None
		state = None
		if checkpoint is not None:
			state = {"matcher": checkpoint, "observed": observe_documents(self.document_base, attribute)}
			if conflict is not None:
				state["conflict"] = conflict
			if new_snapshot is None and serialized != canonical:
				# Keep newly prepared inputs session-local while no decision is committed.
				state["base"] = serialized
			state = encode(state)
		version = save_session(
			self.user_id, self.session.session_id, self.session.base_id, self.document_id,
			self._expected_bson if current is None else current["live_snapshot_hash"],
			self._attribute_schema_version, state, phase, attribute,
			expected_version=0 if current is None else current["version"],
			expected_phase=None if current is None else current["phase"],
			expected_attribute=None if current is None else current["attribute"],
			expected_session_snapshot=None if current is None else current["snapshot_hash"],
			command=command, new_snapshot=new_snapshot, record_receipt=record_receipt,
		)
		self.matching_step_saved = True
		if not self.session.publish_step(
			version, phase, attribute, document_payload, feedback_payload,
			command_id=command["command_id"] if command else None, lease=lease,
			propagation_limited=propagation_limited,
		):
			raise RuntimeError("Saved feedback could not be published.")
		logger.debug("Feedback step published. phase=%s version=%s", phase, version)
