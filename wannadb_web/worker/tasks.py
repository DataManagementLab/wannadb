import pickle
import random
import time

from celery import current_app

from wannadb.data.data import Document, Attribute
from wannadb.statistics import Statistics
from wannadb_web.postgres.queries import getDocuments
from wannadb_web.worker.Web_API import WannaDB_WebAPI
from wannadb_web.worker.util import TaskObject, State, TaskUpdate


class U:

	def update_state(*args, **kwargs):
		print('update_state called with args: ', args, ' and kwargs: ', kwargs)
		print("meta: ", TaskObject.from_dump(kwargs.get("meta")).signals.to_json())


@current_app.task(bind=True)
def create_document_base_task(self, user_id, document_ids: [int], attributes_dump: bytes, statistics_dump: bytes):
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

	api = WannaDB_WebAPI(1, task_object)

	task_object.update(state=State.PENDING, msg="api created")
	try:
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
		# raise Exception("No documents found")

		api.create_document_base(documents, attributes, statistics)
		return task_object.to_dump()

	except Exception as e:
		self.update_state(state=State.FAILURE.value, meta={'exception': str(e)})


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
