import csv
import io
import json
import logging
import time
from typing import Optional

import wannadb
from wannadb import resources
from wannadb.configuration import Pipeline
from wannadb.data.data import Attribute, Document, DocumentBase, InformationNugget
from wannadb.data.signals import CachedDistanceSignal
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
from wannadb_web.postgres.queries import getDocument_by_name, updateDocumentContent, getDocument
from wannadb_web.postgres.transactions import addDocument
from wannadb_web.worker.data import Signals

logger = logging.getLogger(__name__)


class WannaDB_WebAPI:

	def __init__(self, user_id: int, document_base_name: str, organisation_id: int):
		self._document_id: Optional[int] = None
		self._document_base: Optional[DocumentBase] = None
		self.user_id = user_id
		self._feedback = None

		self.signals = Signals(str(self.user_id))
		self.signals.reset()
		self.sqLiteCacheDBWrapper = SQLiteCacheDBWrapper(user_id, db_file=":memory:")
		self.document_base_name = document_base_name
		self.organisation_id = organisation_id

		def status_callback_fn(message, progress):
			self.signals.status.emit(str(message) + " " + str(progress))

		self.status_callback = StatusCallback(status_callback_fn)

		def interaction_callback_fn(pipeline_element_identifier, feedback_request):
			feedback_request["identifier"] = pipeline_element_identifier
			self.signals.feedback_request_to_ui.emit(feedback_request)
			logger.info("Waiting for feedback...")
			time.sleep(2)

		self.interaction_callback = InteractionCallback(interaction_callback_fn)

		if wannadb.resources.MANAGER is None:
			self.signals.error.emit(Exception("Resource Manager not initialized!"))
			raise Exception("Resource Manager not initialized!")
		if self.sqLiteCacheDBWrapper.cache_db.conn is None:
			self.signals.error.emit(Exception("Cache db could not be initialized!"))
			raise Exception("Cache db could not be initialized!")
		logger.info("WannaDB_WebAPI initialized")
	

	@property
	def feedback(self):
		if self._feedback is None:
			raise Exception("Feedback is not set!")
		return self._feedback
	
	@feedback.setter
	def feedback(self, value:dict):
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

	def get_ordert_nuggets(self, document_id: int):
		document = getDocument(document_id, self.user_id)
		if document is None:
			logger.error(f"Document with id {document_id} not found!")
			self.signals.error.emit(Exception(f"Document with id {document_id} not found!"))
			return
		document_name = document[0]
		logger.debug("get_ordert_nuggets")
		self.signals.status.emit("get_ordert_nuggets")
		for document in self.document_base.documents:
			if document.name == document_name:
				self.signals.ordert_nuggets.emit(list(sorted(document.nuggets, key=lambda x: x[CachedDistanceSignal])))
				return
		logger.error(f"Document \"{document_name}\" not found in document base!")
		self.signals.error.emit(Exception(f"Document \"{document_name}\" not found in document base!"))
	
	
	def create_document_base(self, documents: list[Document], attributes: list[Attribute], statistics: Statistics):
		logger.debug("Called slot 'create_document_base'.")
		self.signals.status.emit("create_document_base")
		try:
			self.sqLiteCacheDBWrapper.reset_cache_db()

			document_base = DocumentBase(documents, attributes)
			self.sqLiteCacheDBWrapper.cache_db.create_input_docs_table("input_document", document_base.documents)

			if not document_base.validate_consistency():
				logger.error("Document base is inconsistent!")
				self.signals.error.emit(Exception("Document base is inconsistent!"))

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

			self.document_base = document_base

			self.signals.statistics.emit(statistics)
			self.signals.finished.emit(1)
			self.signals.status.emit("Finished!")


		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e

	def load_document_base_from_bson(self):
		logger.debug("Called function 'load_document_base_from_bson'.")
		try:
			self.sqLiteCacheDBWrapper.reset_cache_db()
			self.signals.reset()

			document_id, document = getDocument_by_name(self.document_base_name, self.organisation_id, self.user_id)
			if not isinstance(document, bytes):
				logger.error("document is not a DocumentBase!")
				self.signals.error.emit(Exception("document is not a DocumentBase!"))
				return

			document_base = DocumentBase.from_bson(document)

			if not document_base.validate_consistency():
				logger.error("Document base is inconsistent!")
				self.signals.error.emit(Exception("Document base is inconsistent!"))
				return

			for attribute in document_base.attributes:
				self.sqLiteCacheDBWrapper.cache_db.create_table_by_name(attribute.name)
			self.sqLiteCacheDBWrapper.cache_db.create_input_docs_table("input_document", document_base.documents)

			logger.info(f"Document base loaded from BSON with id {document_id}.")
			self.document_base = document_base

		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e

	def save_document_base_to_bson(self):
		logger.debug("Called function 'save_document_base_to_bson'.")

		try:
			document_id = addDocument(self.document_base_name, self.document_base.to_bson(), self.organisation_id,
									  self.user_id)

			if document_id is None:
				logger.error("Document base could not be saved to BSON!")
			elif document_id == -1:
				logger.error(
					f"Document base could not be saved to BSON! Document {self.document_base_name} already exists!")
				self.signals.error.emit(
					Exception(
						f"Document base could not be saved to BSON! Document {self.document_base_name} already exists!"))
			elif document_id > 0:
				logger.info(f"Document base saved to BSON with ID {document_id}.")
				self.signals.status.emit(f"Document base saved to BSON with ID {document_id}.")
				self.document_id = document_id
			return
		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e

	def update_document_base_to_bson(self):
		logger.debug("Called function 'save_document_base_to_bson'.")

		if self.document_id is None:
			logger.error("Document ID not set!")
			self.signals.error.emit(Exception("Document ID not set!"))
			return
		try:
			status = updateDocumentContent(self.document_id, self.document_base.to_bson())
			if status is False:
				logger.error(f"Document base could not be saved to BSON! Document {self.document_id} does not exist!")
			elif status is True:
				logger.info(f"Document base saved to BSON with ID {self.document_id}.")
				self.signals.status.emit(f"Document base saved to BSON with ID {self.document_id}.")
			logger.error("Document base could not be saved to BSON!")
			return
		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e

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
		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e

	def add_attribute(self, attribute: Attribute):
		logger.debug("Called function 'add_attribute'.")
		if attribute in self.document_base.attributes:
			logger.error("Attribute name already exists!")
			self.signals.error.emit(Exception("Attribute name already exists!"))
		else:
			self.document_base.attributes.append(attribute)
			logger.debug(f"Attribute '{attribute.name}' added.")
			self.signals.status.emit(f"Attribute '{attribute.name}' added.")
			self.sqLiteCacheDBWrapper.cache_db.create_table_by_name(attribute.name)

	def add_attributes(self, attributes: list[Attribute]):
		logger.debug("Called function 'add_attributes'.")
		already_existing_names = []
		for attribute in attributes:
			if attribute in self.document_base.attributes:
				logger.info(f"Attribute name '{attribute.name}' already exists and was thus not added.")
				already_existing_names.append(attribute)
			elif attribute is None:
				logger.info("Attribute name must not be empty and was thus ignored.")
			else:
				self.document_base.attributes.append(attribute)
				self.sqLiteCacheDBWrapper.cache_db.create_table_by_name(attribute.name)
				logger.debug(f"Attribute '{attribute.name}' added.")
		return already_existing_names

	def remove_attributes(self, attributes: list[Attribute]):
		logger.debug("Called function 'remove_attribute'.")
		for attribute in attributes:
			if attribute in self.document_base.attributes:
				for document in self.document_base.documents:
					if attribute.name in document.attribute_mappings.keys():
						del document.attribute_mappings[attribute.name]

				for old_attribute in self.document_base.attributes:
					if old_attribute == attribute:
						self.document_base.attributes.remove(attribute)
						break
				self.signals.status.emit(f"Attribute '{attribute.name}' removed.")
			else:
				logger.error("Attribute name does not exist!")
				self.signals.error.emit(Exception("Attribute name does not exist!"))

	def forget_matches_for_attribute(self, attribute: Attribute):
		logger.debug("Called function 'forget_matches_for_attribute'.")

		self.sqLiteCacheDBWrapper.cache_db.delete_table(attribute.name)
		try:
			if attribute in self.document_base.attributes:
				for document in self.document_base.documents:
					if attribute.name in document.attribute_mappings.keys():
						del document.attribute_mappings[attribute.name]
				self.signals.status.emit(f"Matches for attribute '{attribute.name}' forgotten.")
				self.signals.document_base_to_ui.emit(self.document_base)
			else:
				logger.error("Attribute name does not exist!")
				self.signals.error.emit(Exception("Attribute name does not exist!"))
		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e

	def forget_matches(self):
		logger.debug("Called function 'forget_matches'.")
		for attribute in self.document_base.attributes:
			self.sqLiteCacheDBWrapper.cache_db.delete_table(attribute.name)
			self.sqLiteCacheDBWrapper.cache_db.create_table_by_name(attribute.name)
		try:
			for document in self.document_base.documents:
				document.attribute_mappings.clear()
			self.signals.document_base_to_ui.emit(self.document_base)
			self.signals.finished.emit(1)
		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e

	## todo: below not implemented yet

	def save_statistics_to_json(self):
		logger.debug("Called function 'save_statistics_to_json'.")
		try:
			return json.dumps(self.signals.statistics.to_json(), indent=2)
		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e

	def interactive_table_population(self):
		logger.debug("Called slot 'interactive_table_population'.")

		try:
			if self.document_base is None:
				logger.error("Document base not loaded!")
				self.signals.error.emit(Exception("Document base not loaded!"))
				return

			# load default matching phase
			self.signals.status.emit("Loading matching phase...")

			# TODO: this should not be implemented here!
			def find_additional_nuggets(nugget, documents):
				new_nuggets = []
				for document in documents:
					doc_text = document.text.lower()
					nug_text = nugget.text.lower()
					start = 0
					while True:
						start = doc_text.find(nug_text, start)
						if start == -1:
							break
						else:
							new_nuggets.append((document, start, start + len(nug_text)))
							start += len(nug_text)
				return new_nuggets

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
						find_additional_nuggets=find_additional_nuggets
					)
				]
			)

			matching_phase(self.document_base, self.interaction_callback, self.status_callback,
						   self.signals.statistics.msg())
			self.signals.document_base_to_ui.emit(self.document_base)
			self.signals.finished.emit(1)
		except Exception as e:
			logger.error(str(e))
			self.signals.error.emit(e)
			raise e
