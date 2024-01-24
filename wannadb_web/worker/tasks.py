import logging
import pickle
import time
from typing import Optional, Any

from celery import Task

import wannadb.resources
from wannadb.data.data import Document, Attribute
from wannadb.interaction import EmptyInteractionCallback
from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache
from wannadb_web.postgres.queries import getDocuments
from wannadb_web.worker.Web_API import WannaDB_WebAPI
from wannadb_web.worker.data import Signals
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
		## todo hier muss self.request.id durchgeleitet werden und in signals(request_id) gespeichert werden
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
		self.update(State.PENDING)
		documents: list[Document] = []
		if docs:
			for doc in docs:
				documents.append(Document(doc[0], doc[1]))
		else:
			self.update(State.ERROR)
			raise Exception("No documents found")

		api.create_document_base(documents, attributes, statistics)

		api.save_document_base_to_bson()
		self.update(State.SUCCESS)
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
		api.update_document_base_to_bson()


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


class DocumentBaseInteractiveTablePopulation(BaseTask):
	name = "DocumentBaseInteractiveTablePopulation"

	def run(self, user_id: int, base_name: str, organisation_id: int):
		self._signals = Signals(str(self.request.id))
		self._redis_client = RedisCache(str(self.request.id))
		self.load()

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		api.interactive_table_population()
		if api.signals.error.msg is None:
			api.update_document_base_to_bson()
