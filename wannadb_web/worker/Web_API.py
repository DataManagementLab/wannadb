import csv
import io
import json
import logging
import re
import time
from typing import Optional, Any

import wannadb
from wannadb import resources
from wannadb.configuration import Pipeline
from wannadb.data.data import Attribute, Document, DocumentBase, InformationNugget
from wannadb.data.signals import CachedDistanceSignal, SentenceStartCharsSignal
from wannadb.interaction import EmptyInteractionCallback, InteractionCallback
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
	get_document
from wannadb_web.postgres.transactions import DocumentBaseCreationConflict, create_document_base_with_snapshot, mutate_base_documents
from wannadb_web.limits import validate_attribute_count, validate_corpus
from wannadb_web.Redis.RedisCache import SessionState, get_signal_scope
from wannadb_web.worker.data import decode_feedback, MultiNuggetsMatchFeedback, DoAttributeRanking, ReloadDocumentBase, Signals, CustomMatchFeedback, NuggetMatchFeedback, NoMatchFeedback, SkipAttributeRanking, StopMatching

logger = logging.getLogger(__name__)
TIMEOUT = 600  # 10 minutes

INPUT_DOCS_COLUMN_NAME = "input_document"


class WannaDB_WebAPI:

	def __init__(self, user_id: int, document_base_name: str, organisation_id: int, timeout: int = TIMEOUT, build_query_cache: bool = True):
		self._document_id: Optional[int] = None
		self._document_base: Optional[DocumentBase] = None
		self.user_id = user_id
		self._feedback: Optional[dict[str, Any]] = None
		self._expected_bson: Optional[bytes] = None
		self._pending_command_id: Optional[str] = None
		self.session = SessionState.current(user_id)

		self.signals = Signals(str(self.user_id))
		self.sqLiteCacheDBWrapper = SQLiteCacheDBWrapper(user_id, db_file=":memory:") if build_query_cache else None
		self.document_base_name = document_base_name
		self.organisation_id = organisation_id

		def status_callback_fn(message, progress):
			self.signals.status.emit(str(message) + " " + str(progress))

		self.status_callback = StatusCallback(status_callback_fn)

		def interaction_callback_fn(pipeline_element_identifier, feedback_request):
			feedback_request["identifier"] = pipeline_element_identifier
			self.publish_feedback(feedback_request)
			start_time = time.monotonic()
			while (time.monotonic() - start_time) < max(timeout, TIMEOUT):
				command = self.signals.match_feedback.claim()
				if command is not None:
					self._pending_command_id = command["command_id"]
					msg = decode_feedback(command["payload"])
					self.signals.status.emit("Feedback received from UI")
					logger.debug("Feedback received. wait_seconds=%.3f", time.monotonic() - start_time)
					start_time = time.monotonic()
					if isinstance(msg, CustomMatchFeedback):
						return {"message": "custom-match", "document": msg.document, "start": msg.start, "end": msg.end, "not_a_match": msg.not_a_match}
					elif isinstance(msg, NuggetMatchFeedback):
						return {"message": "is-match", "nugget": msg.nugget, "not_a_match": msg.not_a_match}
					elif isinstance(msg, MultiNuggetsMatchFeedback):
						return {"message": "multi-match", "nuggets": msg.nuggets, "not_a_match": msg.not_a_match}
					elif isinstance(msg, NoMatchFeedback):
						return {"message": "no-match-in-document", "nugget": msg.nugget, "not_a_match": msg.not_a_match, "document": msg.document}
					elif isinstance(msg, DoAttributeRanking):
						return {"message": "start-ranking", "do-attribute": True, "reset": msg.reset}
					elif isinstance(msg, SkipAttributeRanking):
						return {"message": "skip-ranking", "do-attribute": False}
					elif isinstance(msg, ReloadDocumentBase):
						self.publish_feedback(feedback_request)
					elif isinstance(msg, StopMatching):
						return {"message": "stop-interactive-matching"}
					else:
						raise ValueError("Unsupported feedback command")
				time.sleep(0.1)
			raise TimeoutError("no match_feedback in time provided")

		self.interaction_callback = InteractionCallback(interaction_callback_fn)

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
		self.signals.document_base_to_ui.emit(value)
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

	def load_document_base_from_bson(self):
		logger.debug("Loading document base snapshot.")
		try:
			if self.sqLiteCacheDBWrapper is not None:
				self.sqLiteCacheDBWrapper.reset_cache_db()

			scope = get_signal_scope()
			snapshot = get_document_base_snapshot(self.document_base_name, scope["base_id"],
				self.organisation_id, self.user_id)
			if snapshot is None:
				self.signals.error.emit(RuntimeError("Document base snapshot not found."))
				return

			document_id, document = snapshot
			document_base = DocumentBase.from_bson(document)
			if self.sqLiteCacheDBWrapper is not None:
				for attribute in document_base.attributes:
					self.sqLiteCacheDBWrapper.create_attribute_table(attribute.name)
				self.sqLiteCacheDBWrapper.cache_db.create_input_docs_table(INPUT_DOCS_COLUMN_NAME, document_base.documents)

			self.document_base = document_base
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
			self.organisation_id, self.user_id, scope["base_id"], **metadata)
		if not status:
			self.signals.error.emit(RuntimeError("STALE_BASE"))
			raise RuntimeError("The base changed or access was lost; reload before editing again.")
		self._expected_bson = serialized
		self.signals.status.emit("Changes saved.")

	def publish_feedback(self, feedback_request):
		# A consumed command is acknowledged only after its changes are durable and
		# both the base and next candidate payload have been atomically published.
		if self._pending_command_id is not None:
			self.update_document_base_to_bson()
		self.signals.document_base_to_ui.emit(self.document_base)
		self.signals.feedback_request_to_ui.emit(feedback_request)
		phase = "selection" if "do-attribute-request" in feedback_request else "ranking"
		attribute = feedback_request.get("attribute")
		version = self.session.publish(phase, getattr(attribute, "name", None), self._pending_command_id)
		logger.debug("Feedback published. phase=%s version=%s", phase, version)
		self._pending_command_id = None

	def complete_session(self):
		self.signals.document_base_to_ui.emit(self.document_base)
		self.session.close(command_id=self._pending_command_id)
		self._pending_command_id = None

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
				self.signals.document_base_to_ui.emit(self.document_base)
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
			self.signals.document_base_to_ui.emit(self.document_base)
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

	def interactive_table_population(self):
		logger.debug("Called slot 'interactive_table_population'.")

		try:
			if self.document_base is None:
				logger.error("Document base not loaded!")
				self.signals.error.emit(Exception("Document base not loaded!"))
				return

			# Older add/edit tasks could save raw documents without preprocessing.
			raw_documents = [document for document in self.document_base.documents
				if SentenceStartCharsSignal.identifier not in document.signals]
			if raw_documents:
				self._preprocess(DocumentBase(raw_documents, []), Statistics(False))

			# load default matching phase
			self.signals.status.emit("Loading matching phase...")

			# TODO: this should not be implemented here!
			def find_additional_nuggets(nugget, documents):
				if not nugget.text:
					return []
				# Match against original text: lowercasing can change Unicode string length.
				pattern = re.compile(re.escape(nugget.text), re.IGNORECASE)
				return [(document, match.start(), match.end()) for document in documents
					for match in pattern.finditer(document.text)]

			matching_phase = Pipeline(
				[
					SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
					ContextSentenceCacher(),
					SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
					RankingBasedMatcher(
						distance=SignalsMeanDistance(
							signal_identifiers=[
								"LabelEmbeddingSignal",
								"TextEmbeddingSignal",
								"ContextSentenceEmbeddingSignal",
								"RelativePositionSignal"
							]
						),
						max_num_feedback=100,
						len_ranked_list=10,
						max_distance=0.2,
						num_random_docs=1,
						sampling_mode="AT_MAX_DISTANCE_THRESHOLD",
						adjust_threshold=True,
						nugget_pipeline=Pipeline(
							[
								ContextSentenceCacher(),
								CopyNormalizer(),
								OntoNotesLabelParaphraser(),
								SplitAttributeNameLabelParaphraser(do_lowercase=True, splitters=[" ", "_"]),
								SBERTLabelEmbedder("SBERTBertLargeNliMeanTokensResource"),
								SBERTTextEmbedder("SBERTBertLargeNliMeanTokensResource"),
								BERTContextSentenceEmbedder("BertLargeCasedResource"),
								RelativePositionEmbedder()
							]
						),
						find_additional_nuggets=find_additional_nuggets,
						allow_manual_without_candidates=True
					)
				]
			)

			matching_phase(self.document_base, self.interaction_callback, self.status_callback,
						   Statistics(False))
			self.signals.document_base_to_ui.emit(self.document_base)
			self.signals.finished.emit(1)
		except Exception as error:
			self._report_error("MATCHING_FAILED", error)
			raise
