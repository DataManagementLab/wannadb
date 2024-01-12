import logging
import threading
from datetime import datetime
from enum import Enum
from wannadb.data.data import Attribute, Document
from wannadb.statistics import Statistics
from wannadb_web.worker.Web_API import Web_API
from wannadb.resources import ResourceManager

logger = logging.getLogger(__name__)


class Status(Enum):
	"""Gives the status of the application."""
	IDLE = 1
	RUNNING = 2
	CREATED = 3
	DEAD = 98
	ERROR = 99


class Web_API_Thread(threading.Thread):
	def __init__(self, thread_id):
		super().__init__()
		self.function = None
		self.thread_id = thread_id
		self.wannadb_web_api = Web_API()
		self.event = threading.Event()
		self.status = Status.IDLE
		self.last_call = datetime.now()
		self.exit_flag = False

	def run(self):
		ResourceManager()
		self.status = Status.RUNNING
		while True:
			if self.exit_flag:
				self.status = Status.DEAD
				logger.info(f"Thread {self.thread_id} exited")
				return
			self.event.wait()
			self.event.clear()
			if self.function is not None:
				self.function()
				self.last_call = datetime.now()
			else:
				raise Exception("No function set")
			self.function = None

	def create_document_base(self, documents: [Document], attributes: [Attribute], statistics: Statistics):
		if self.function is not None:
			raise Exception("Function running")
		self.function = lambda: self.wannadb_web_api.create_document_base_task(documents, attributes, statistics)
		self.event.set()
