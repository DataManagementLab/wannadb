import logging
import pickle
import time
from typing import Optional, Any, Union

from celery import Task

import wannadb.resources
from wannadb.data.data import Document, Attribute, InformationNugget
from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache
from wannadb_web.postgres.queries import getDocuments
from wannadb_web.worker.Web_API import WannaDB_WebAPI
from wannadb_web.worker.data import Signals, NoMatchFeedback, NuggetMatchFeedback, CustomMatchFeedback
from wannadb_web.worker.util import State

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger()


class InitManager(Task):
	name = "InitManager"

	def run(self, *args, **kwargs):
		ResourceManager()
		if wannadb.resources.MANAGER is None:
			raise RuntimeError("Resource_Manager is None!")
		manager = pickle.dumps(wannadb.resources.MANAGER)
		RedisCache("0").set("manager", manager)


class BaseTask(Task):
	name = "BaseTask"
	_signals: Optional[Signals] = None
	_redis_client: Optional[RedisCache] = None

	def __init__(self):
		super().__init__()

	def run(self, *args, **kwargs):
		raise NotImplementedError("BaseTask is abstract")

	@staticmethod
	def load():
		if wannadb.resources.MANAGER is None:
			wannadb.resources.ResourceManager()
			BaseTask.load()
			return
		logging.info("loaded")

	def update(self,
			   state: State,
			   meta: Optional[dict[str, Any]] = None,
			   ) -> None:
		super().update_state(state=state.value, meta=meta)

	def update_state(self,
					 task_id: Optional[str] = None,
					 state: Optional[str] = None,
					 meta: Any = None,
					 **kwargs: Any
					 ) -> None:
		raise NotImplementedError("user update() instead")

	def get_new_input(self):
		if self._redis_client is None:
			raise RuntimeError("self._redis_client is None!")
		_input = self._redis_client.get("input")
		if _input is not None:
			pass

		return _input


class TestTask(BaseTask):
	name = "TestTask"

	def run(self, *args, **kwargs):
		super().run()
		self.update(state=State.PENDING)
		while True:
			_input = self.get_new_input()
			if _input is not None:
				print(_input)
				self.update(state=State.SUCCESS, meta={"msg": _input})
				time.sleep(2)
			self.update(state=State.WAITING, meta={"msg": "waiting"})
			time.sleep(2)


class CreateDocumentBase(BaseTask):
	name = "CreateDocumentBase"

	def run(self, user_id: int, document_ids: list[int], attributes_strings: list[str], statistics_dump: bytes,
			base_name: str, organisation_id: int):
		self.load()
		attributes: list[Attribute] = []
		statistics: Statistics = pickle.loads(statistics_dump)
		for attribute_string in attributes_strings:
			if attribute_string == "":
				logger.error("Attribute names cannot be empty!")
				raise Exception("Attribute names cannot be empty!")
			if attribute_string in [attribute.name for attribute in attributes]:
				logger.error("Attribute names must be unique!")
				raise Exception("Attribute names must be unique!")
			attributes.append(Attribute(attribute_string))

		"""
		init api
		"""
		api = WannaDB_WebAPI(user_id, base_name, organisation_id)

		"""
		Creating document base
		"""
		if not isinstance(attributes[0], Attribute):
			self.update(State.ERROR)
			raise Exception("Invalid attributes")

		if not isinstance(statistics, Statistics):
			self.update(State.ERROR)
			raise Exception("Invalid statistics")

		docs = getDocuments(document_ids, user_id)
		if docs[0] is tuple[None,None]:
			raise Exception(f"user with user id:{user_id} has no document with the document_ids: {document_ids}")

		self.update(State.PENDING)
		documents: list[Document] = []
		if docs:
			for doc in docs:
				name = doc[0]
				text = doc[1]
				if name is None:
					raise Exception("Document Name is none")
				if text is None:
					raise Exception("Document text is none")
				documents.append(Document(name, text))

		else:
			self.update(State.ERROR)
			raise Exception("No documents found")

		api.create_document_base(documents, attributes, statistics)

		api.save_document_base_to_bson()
		if api.signals.error.msg is None:
			api.update_document_base_to_bson()
			self.update(State.SUCCESS)
			return self
		self.update(State.ERROR)
		return self


class DocumentBaseLoad(BaseTask):
	name = "DocumentBaseLoad"

	def run(self, user_id: int, base_name: str, organisation_id: int):
		self.load()
		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		# self.update(State.SUCCESS)
		# return self
		if api.signals.error.msg is None:
			self.update(State.SUCCESS)
			return self
		self.update(State.ERROR)
		return self


class DocumentBaseAddAttributes(BaseTask):
	name = "DocumentBaseAddAttributes"

	def run(self, user_id: int, attributes_strings: list[str], base_name: str, organisation_id: int):
		self.load()
		attributes: list[Attribute] = []

		for attribute_string in attributes_strings:
			if attribute_string == "":
				logger.error("Attribute names cannot be empty!")
				raise Exception("Attribute names cannot be empty!")
			if attribute_string in [attribute.name for attribute in attributes]:
				logger.error("Attribute names must be unique!")
				raise Exception("Attribute names must be unique!")
			attributes.append(Attribute(attribute_string))

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		api.add_attributes(attributes)
		if api.signals.error.msg is None:
			api.update_document_base_to_bson()
			self.update(State.SUCCESS)
			return self
		self.update(State.ERROR)
		return self


class DocumentBaseUpdateAttributes(BaseTask):
	name = "DocumentBaseAddAttributes"

	def run(self, user_id: int, attributes_strings: list[str], base_name: str, organisation_id: int):
		self.load()
		attributes: list[Attribute] = []

		for attribute_string in attributes_strings:
			if attribute_string == "":
				logger.error("Attribute names cannot be empty!")
				raise Exception("Attribute names cannot be empty!")
			if attribute_string in [attribute.name for attribute in attributes]:
				logger.error("Attribute names must be unique!")
				raise Exception("Attribute names must be unique!")
			attributes.append(Attribute(attribute_string))

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		api.update_attributes(attributes)
		if api.signals.error.msg is None:
			api.update_document_base_to_bson()
			self.update(State.SUCCESS)
			return self
		self.update(State.ERROR)
		return self


class DocumentBaseRemoveAttributes(BaseTask):
	name = "DocumentBaseRemoveAttributes"

	def run(self, user_id: int, attributes_strings: list[str], base_name: str, organisation_id: int):
		self.load()
		attributes: list[Attribute] = []

		for attribute_string in attributes_strings:
			if attribute_string == "":
				logger.error("Attribute names cannot be empty!")
				raise Exception("Attribute names cannot be empty!")
			if attribute_string in [attribute.name for attribute in attributes]:
				logger.error("Attribute names must be unique!")
				raise Exception("Attribute names must be unique!")
			attributes.append(Attribute(attribute_string))

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		api.remove_attributes(attributes)
		if api.signals.error.msg is None:
			api.update_document_base_to_bson()
			self.update(State.SUCCESS)
			return self
		self.update(State.ERROR)
		return self


class DocumentBaseForgetMatches(BaseTask):
	name = "DocumentBaseForgetMatches"

	def run(self, user_id: int, attributes_strings: list[str], base_name: str, organisation_id: int):
		self.load()
		attributes: list[Attribute] = []

		for attribute_string in attributes_strings:
			if attribute_string == "":
				logger.error("Attribute names cannot be empty!")
				raise Exception("Attribute names cannot be empty!")
			if attribute_string in [attribute.name for attribute in attributes]:
				logger.error("Attribute names must be unique!")
				raise Exception("Attribute names must be unique!")
			attributes.append(Attribute(attribute_string))

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		api.forget_matches()
		if api.signals.error.msg is None:
			api.update_document_base_to_bson()
			self.update(State.SUCCESS)
			return self
		self.update(State.ERROR)
		return self


class DocumentBaseForgetMatchesForAttribute(BaseTask):
	name = "DocumentBaseForgetMatches"

	def run(self, user_id: int, attribute_string: str, base_name: str, organisation_id: int):
		self.load()

		attribute = (Attribute(attribute_string))

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		api.forget_matches_for_attribute(attribute)
		if api.signals.error.msg is None:
			api.update_document_base_to_bson()
			self.update(State.SUCCESS)
			return self
		self.update(State.ERROR)
		return self


class DocumentBaseInteractiveTablePopulation(BaseTask):
	name = "DocumentBaseInteractiveTablePopulation"

	def run(self, user_id: int, base_name: str, organisation_id: int):
		self._signals = Signals(str(user_id))
		self._redis_client = RedisCache(str(user_id))
		self.load()

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		api.interactive_table_population()
		if api.signals.error.msg is None:
			api.update_document_base_to_bson()
			self.update(State.SUCCESS)
			return self


class DocumentBaseGetOrderedNuggets(BaseTask):
	name = "DocumentBaseGetOrderedNuggets"

	def run(self, user_id: int, base_name: str, organisation_id: int, document_name: str, document_content: str):
		self._signals = Signals(str(user_id))
		self._redis_client = RedisCache(str(user_id))
		self.load()

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		# api.get_ordert_nuggets(document_id)
		api.get_ordered_nuggets_by_doc_name(document_name, document_content)
		# no need to update the document base
		self.update(State.SUCCESS)
		return self


class DocumentBaseConfirmNugget(BaseTask):
	name = "DocumentBaseConfirmNugget"

	def run(self, user_id: int, base_name: str, organisation_id: int,
			document_name: str, document_text: str, nugget: Union[str, InformationNugget],
			start_index: Union[int, None], end_index: Union[int, None], interactive_call_task_id: str):
		"""
		:param user_id: user id
		:param base_name: name of base document
		:param organisation_id: organisation id of the document base
		:param document_name: name of the document
		:param document_text: text of the document
		:param nugget: the Nugget that gets confirmed
		:param start_index: start of the nugget in the document (optional) if start and end is None the nugget is not in the document
		:param end_index: end of the nugget in the document (optional) if start and end is None the nugget is not in the document
		:param interactive_call_task_id: the same task id that's used for interactive call
		"""
		self._signals = Signals(str(user_id))
		self._redis_client = RedisCache(str(user_id))
		self.load()

		document = Document(document_name, document_text)
		if start_index is None and end_index is None and isinstance(nugget, InformationNugget):
			self._signals.match_feedback.emit(no_match(nugget))
		else:
			self._signals.match_feedback.emit(match_feedback(nugget, document, start_index, end_index))
		# no need to update the document base the doc will be saved in the interactive call
		self.update(State.SUCCESS)
		return self


def nugget_exist(nugget: str, document: Document, start_index: int, end_index: int):
	print("start: ", start_index, "end: ", end_index)
	try:
		print("doc "+document.text[start_index:end_index])
		print("nug "+nugget)
		if document.text[start_index:end_index] == nugget:
			return True
	except IndexError:
		logger.error("Nugget does not exist in the given Text")
		raise Exception("Nugget does not exist in the given Text")
	logger.error("Nugget does not exist in the given Text")
	raise Exception("Nugget does not exist in the given Text")


def match_feedback(nugget: Union[str, InformationNugget], document: Document,
				   start_index: Optional[int] = None, end_index: Optional[int] = None) -> Union[NuggetMatchFeedback, CustomMatchFeedback]:
	logger.debug("match_feedback")
	if isinstance(nugget, str):
		if document is None:
			logger.error("The document is missing in document base")
			raise Exception("The document is missing in document base")
		if start_index is None or end_index is None:
			logger.error("Start-index or end-index are missing to find the custom nugget")
			raise Exception("Start-index or end-index are missing to find the custom nugget")
		return CustomMatchFeedback(document, start_index, end_index)
	if isinstance(nugget, InformationNugget):
		return NuggetMatchFeedback(nugget, None)
	raise Exception("Invalid nugget type")


def no_match(nugget: InformationNugget) -> NoMatchFeedback:
	return NoMatchFeedback(nugget, nugget)
