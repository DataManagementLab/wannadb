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


class InitManager(Task):
	name = "InitManager"

	def run(self, *args, **kwargs):
		ResourceManager()
		if wannadb.resources.MANAGER is None:
			raise RuntimeError("Resource_Manager is None!")
		manager = pickle.dumps(wannadb.resources.MANAGER)
		RedisCache(0).set("manager", manager)


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
		manager = RedisCache(0).get("manager")
		if not isinstance(manager, bytes):
			raise RuntimeError("manager is not bytes!")
		if manager is None and wannadb.resources.MANAGER is None:
			wannadb.resources.ResourceManager()
			BaseTask.load()
		_MANAGER: Optional["ResourceManager"] = pickle.loads(manager)
		wannadb.resources.MANAGER = _MANAGER

	@staticmethod
	def save():
		manager = pickle.dumps(wannadb.resources.MANAGER)
		RedisCache(0).set("manager", manager)

	def update(self,
			   state: Optional[State] = None,
			   meta: Optional[dict[str, Any]] = None,
			   ) -> None:
		if meta:
			super().update_state(meta=meta)
		if self._signals is None:
			raise RuntimeError("self._signals is None!")
		else:
			super().update_state(state=str(state.value if state else None),
								 meta=self._signals.to_json())

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

	def run(self, user_id: int, document_ids: list[int], attributes_dump: bytes, statistics_dump: bytes,
			base_name: str, organisation_id: int):
		self._signals = Signals(user_id)
		self._redis_client = RedisCache(user_id)
		self.load()
		attributes: list[Attribute] = pickle.loads(attributes_dump)
		statistics: Statistics = pickle.loads(statistics_dump)
		print(user_id)

		"""
		init api
		"""
		api = WannaDB_WebAPI(user_id, EmptyInteractionCallback(), base_name, organisation_id)
		try:
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
			documents = []
			if docs:
				for doc in docs:
					documents.append(Document(doc[0], doc[1]))
			else:
				print("No documents found")

			api.create_document_base(documents, attributes, statistics)

			api.save_document_base_to_bson()

			self.update(State.SUCCESS)
			return self
		finally:
			self.save()

#
#
# @app.task(bind=True)
# def add_attributes(self, user_id: int, attributes_dump: Optional[bytes], base_name: str, organisation_id: int):
# 	"""
# 	define values
# 	"""
#
# 	def task_callback_fn(state: str, meta: TaskObject):
# 		if isinstance(state, str) and state is not None and len(state) > 0:
# 			meta_dump = meta.to_dump()
# 			self.update_state(state=state, meta=meta_dump)
# 		else:
# 			raise Exception("task_callback_fn error Invalid state")
#
# 	task_callback = TaskCallback(task_callback_fn)
#
# 	task_object = TaskObject(task_callback)
#
# 	"""
# 	init api
# 	"""
#
# 	api = WannaDB_WebAPI(user_id, task_object, base_name, organisation_id)
# 	task_object.check()
#
# 	api.load_document_base_from_bson()
# 	task_object.check()
#
# 	if attributes_dump is not None:
# 		attributes: list[Attribute] = pickle.loads(attributes_dump)
# 		api.add_attributes(attributes)
# 		if task_object.signals.error.msg:
# 			task_object.update(State.FAILURE)
# 			raise task_object.signals.error.msg
#
# 	api.save_document_base_to_bson()
# 	task_object.check()
# 	task_object.update(state=State.SUCCESS)
#
#
# @app.task(bind=True)
# def remove_attributes(self, user_id: int, attributes_dump: Optional[bytes], base_name: str, organisation_id: int):
# 	"""
# 	define values
# 	"""
#
# 	def task_callback_fn(state: str, meta: TaskObject):
# 		if isinstance(state, str) and state is not None and len(state) > 0:
# 			meta_dump = meta.to_dump()
# 			self.update_state(state=state, meta=meta_dump)
# 		else:
# 			raise Exception("task_callback_fn error Invalid state")
#
# 	task_callback = TaskCallback(task_callback_fn)
#
# 	task_object = TaskObject(task_callback)
#
# 	"""
# 	init api
# 	"""
#
# 	api = WannaDB_WebAPI(user_id, task_object, base_name, organisation_id)
# 	task_object.check()
#
# 	api.load_document_base_from_bson()
# 	task_object.check()
#
# 	if attributes_dump is not None:
# 		attributes: list[Attribute] = pickle.loads(attributes_dump)
# 		api.remove_attributes(attributes)
# 		if task_object.signals.error.msg:
# 			task_object.update(State.FAILURE)
# 			raise task_object.signals.error.msg
#
# 	api.save_document_base_to_bson()
# 	task_object.check()
# 	task_object.update(state=State.SUCCESS)
#
#
# @app.task(bind=True)
# def forget_matches_for_attribute(self, user_id: int, attribute_dump: Optional[bytes], base_name: str,
# 								 organisation_id: int):
# 	"""
# 	define values
# 	"""
#
# 	def task_callback_fn(state: str, meta: TaskObject):
# 		if isinstance(state, str) and state is not None and len(state) > 0:
# 			meta_dump = meta.to_dump()
# 			self.update_state(state=state, meta=meta_dump)
# 		else:
# 			raise Exception("task_callback_fn error Invalid state")
#
# 	task_callback = TaskCallback(task_callback_fn)
#
# 	task_object = TaskObject(task_callback)
#
# 	"""
# 	init api
# 	"""
#
# 	api = WannaDB_WebAPI(user_id, task_object, base_name, organisation_id)
# 	task_object.check()
#
# 	api.load_document_base_from_bson()
# 	task_object.check()
#
# 	if attribute_dump is not None:
# 		attribute: Attribute = pickle.loads(attribute_dump)
# 		api.forget_matches_for_attribute(attribute)
# 		if task_object.signals.error.msg:
# 			task_object.update(State.FAILURE)
# 			raise task_object.signals.error.msg
#
# 	api.save_document_base_to_bson()
# 	task_object.check()
# 	task_object.update(state=State.SUCCESS)
#
#
# @app.task(bind=True)
# def forget_matches(self, user_id: int, base_name: str, organisation_id: int):
# 	"""
# 	define values
# 	"""
#
# 	def task_callback_fn(state: str, meta: TaskObject):
# 		if isinstance(state, str) and state is not None and len(state) > 0:
# 			meta_dump = meta.to_dump()
# 			self.update_state(state=state, meta=meta_dump)
# 		else:
# 			raise Exception("task_callback_fn error Invalid state")
#
# 	task_callback = TaskCallback(task_callback_fn)
#
# 	task_object = TaskObject(task_callback)
#
# 	"""
# 	init api
# 	"""
#
# 	api = WannaDB_WebAPI(user_id, task_object, base_name, organisation_id)
# 	task_object.check()
#
# 	api.load_document_base_from_bson()
# 	task_object.check()
#
# 	api.forget_matches()
# 	task_object.check()
#
# 	api.save_document_base_to_bson()
# 	task_object.check()
# 	task_object.update(state=State.SUCCESS)
#
#
# @app.task(bind=True)
# def interactive_table_population(self, user_id: int, attributes_dump: Optional[bytes], base_name: str,
# 								 organisation_id: int):
# 	"""
# 	define values
# 	"""
#
# 	def task_callback_fn(state: str, meta: TaskObject):
# 		if isinstance(state, str) and state is not None and len(state) > 0:
# 			meta_dump = meta.update().to_dump()
# 			self.update_state(state=state, meta=meta_dump)
# 		else:
# 			raise Exception("task_callback_fn error Invalid state")
#
# 	task_callback = TaskCallback(task_callback_fn)
#
# 	def interaction_callback_fn(pipeline_element_identifier, feedback_request):
# 		feedback_request["identifier"] = pipeline_element_identifier
# 		self.feedback_request_to_ui.emit(feedback_request)
#
# 		self.feedback_mutex.lock()
# 		try:
# 			self.feedback_cond.wait(self.feedback_mutex)
# 		finally:
# 			self.feedback_mutex.unlock()
#
# 		return self.feedback
#
# 	interaction_callback = InteractionCallback(interaction_callback_fn)
#
# 	task_object = TaskObject(task_callback)
#
# 	"""
# 	init api
# 	"""
#
# 	api = WannaDB_WebAPI(user_id, task_object, base_name, organisation_id)
# 	task_object.check()
#
# 	api.load_document_base_from_bson()
# 	task_object.check()
#
# 	api.forget_matches()
# 	task_object.check()
#
# 	api.save_document_base_to_bson()
# 	task_object.check()
# 	task_object.update(state=State.SUCCESS)
#
#
# @app.task(bind=True)
# def long_task(self):
# 	try:
# 		"""Background task that runs a long function with progress reports."""
# 		verb = ['Starting up', 'Booting', 'Repairing', 'Loading', 'Checking']
# 		adjective = ['master', 'radiant', 'silent', 'harmonic', 'fast']
# 		noun = ['solar array', 'particle reshaper', 'cosmic ray', 'orbiter', 'bit']
# 		data = ''
# 		total = random.randint(10, 50)
#
# 		def task_callback_fn(state: str, meta: TaskObject):
# 			if not isinstance(state, str):
# 				raise Exception("task_callback_fn error Invalid state")
# 			meta_dump = meta.to_dump()
# 			self.update_state(state=state, meta=meta_dump)
#
# 		task_callback = TaskCallback(task_callback_fn)
#
# 		task_object = TaskObject(task_callback)
#
# 		for i in range(total):
# 			if not data or random.random() < 0.25:
# 				data = '{0} {1} {2}...'.format(random.choice(verb),
# 											   random.choice(adjective),
# 											   random.choice(noun))
# 			time.sleep(1)
# 			task_object.update(state=State.PENDING)
# 		task_object.update(state=State.SUCCESS)
# 		return data
# 	except Exception as e:
# 		self.update_state(state=State.FAILURE.value, meta={'exception': str(e)})
# 		raise
