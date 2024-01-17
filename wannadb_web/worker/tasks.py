import logging
import pickle
import random
import time
from typing import Optional

from celery import current_app

from wannadb.data.data import Document, Attribute
from wannadb.statistics import Statistics
from wannadb_web.postgres.queries import getDocuments
from wannadb_web.worker.Web_API import WannaDB_WebAPI
from wannadb_web.worker.util import State, TaskUpdate
from wannadb_web.worker.util import TaskObject

# class U:
# 	def update_state(*args, **kwargs):
# 		print('update_state called with args: ', args, ' and kwargs: ', kwargs)
# 		print("meta: ", TaskObject.from_dump(kwargs.get("meta")).signals.to_json())


logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# RedisConnection()
# ResourceManager()
# authorization = (
# 	"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjoibGVvbiIsImlkIjoxfQ.YM9gwcXeFSku-bz4RUKkymYvA6Af13sxH-BRlnjCCEA")
# _token = tokenDecode(authorization)
# _base_name = "base_name"
# document_ids = [2, 3]
# attribute = Attribute("a")
# statistics = Statistics(False)
# user_id = 1
# attributesDump = pickle.dumps([attribute])
# statisticsDump = pickle.dumps(statistics)
# uuuuuuuu = U()


@current_app.task(bind=True)
def create_document_base_task(self, user_id, document_ids: list[int], attributes_dump: bytes, statistics_dump: bytes,
							  base_name: str, organisation_id: int):
	"""
    define values
	"""

	attributes: list[Attribute] = pickle.loads(attributes_dump)
	statistics: Statistics = pickle.loads(statistics_dump)

	def task_callback_fn(state: str, meta: TaskObject):
		if isinstance(state, str) and state is not None and len(state) > 0:
			meta_dump = meta.to_dump()
			self.update_state(state=state, meta=meta_dump)
		else:
			raise Exception("task_callback_fn error Invalid state")

	task_callback = TaskUpdate(task_callback_fn)

	task_object = TaskObject(task_callback)

	"""
	init api
	"""

	api = WannaDB_WebAPI(1, task_object, base_name, organisation_id)

	task_object.update(state=State.PENDING, msg="api created")
	try:
		"""
		decoding
		"""
		if not isinstance(attributes[0], Attribute):
			task_object.update(State.FAILURE, "Invalid attributes")
			raise Exception("Invalid attributes")

		if not isinstance(statistics, Statistics):
			task_object.update(State.FAILURE, "Invalid statistics")
			raise Exception("Invalid statistics")

		docs = getDocuments(document_ids, user_id)
		task_object.update(State.PENDING, "Creating document base")
		documents = []
		if docs:
			for doc in docs:
				documents.append(Document(doc[0], doc[1]))
		else:
			print("No documents found")
		"""
		Creating document base
		"""

		api.create_document_base(documents, attributes, statistics)
		if task_object.signals.error.msg:
			task_object.update(State.FAILURE, api.signals)

		"""
		saving document base
		"""

		api.save_document_base_to_bson()

		"""
		response
		"""

		if task_object.signals.finished.msg is None:
			task_object.update(State.ERROR, "task_object signals not set?")
		else:

			task_object.update(State.SUCCESS)

		task_object.update(State.SUCCESS)
		return task_object.to_dump()

	except Exception as e:
		# task_object.update(State.FAILURE, str(e))
		raise e


@current_app.task(bind=True)
def update_document_base(self, user_id,  attributes_dump: Optional[bytes], statistics_dump: bytes, base_name: str,
						 organisation_id: int):
	"""
	define values
	"""
	statistics: Statistics = pickle.loads(statistics_dump)

	def task_callback_fn(state: str, meta: TaskObject):
		if isinstance(state, str) and state is not None and len(state) > 0:
			meta_dump = meta.to_dump()
			self.update_state(state=state, meta=meta_dump)
		else:
			raise Exception("task_callback_fn error Invalid state")

	task_callback = TaskUpdate(task_callback_fn)

	task_object = TaskObject(task_callback)

	"""
	init api
	"""

	api = WannaDB_WebAPI(1, task_object, base_name, organisation_id)
	if task_object.signals.error.msg:
		task_object.update(State.FAILURE, api.signals)
		raise task_object.signals.error.msg
	task_object.update(state=State.PENDING, msg="api created")

	api.load_document_base_from_bson()
	if task_object.signals.error.msg:
		task_object.update(State.FAILURE, api.signals)
		raise task_object.signals.error.msg
	task_object.update(state=State.PENDING, msg="document base loaded")

	if attributes_dump is not None:
		attributes: list[Attribute] = pickle.loads(attributes_dump)
		api.add_attributes(attributes)
		if task_object.signals.error.msg:
			task_object.update(State.FAILURE, api.signals)
			raise task_object.signals.error.msg
		task_object.update(state=State.PENDING, msg="attributes added")
		api.add_attributes(attributes)

	## todo: further manipulations here


@current_app.task(bind=True)
def long_task(self):
	try:
		"""Background task that runs a long function with progress reports."""
		verb = ['Starting up', 'Booting', 'Repairing', 'Loading', 'Checking']
		adjective = ['master', 'radiant', 'silent', 'harmonic', 'fast']
		noun = ['solar array', 'particle reshaper', 'cosmic ray', 'orbiter', 'bit']
		data = ''
		total = random.randint(10, 50)

		def task_callback_fn(state: str, meta: TaskObject):
			if not isinstance(state, str):
				raise Exception("task_callback_fn error Invalid state")
			meta_dump = meta.to_dump()
			self.update_state(state=state, meta=meta_dump)

		task_callback = TaskUpdate(task_callback_fn)

		task_object = TaskObject(task_callback)

		for i in range(total):
			if not data or random.random() < 0.25:
				data = '{0} {1} {2}...'.format(random.choice(verb),
											   random.choice(adjective),
											   random.choice(noun))
			time.sleep(1)
			task_object.update(state=State.PENDING, msg=data)
		task_object.update(state=State.SUCCESS, msg='Task completed!')
		return data
	except Exception as e:
		self.update_state(state=State.FAILURE.value, meta={'exception': str(e)})
		raise
