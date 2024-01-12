import threading
import logging.config
import time
from datetime import datetime
from wannadb_web.worker.Web_API_Thread import Web_API_Thread

logger = logging.getLogger(__name__)


class Web_Thread_Manager(threading.Thread):
	def __init__(self, idle_time=60):
		super().__init__()
		logger.info("Web_Thread_Manager initialized")
		self.idle_time = idle_time
		self.threads: dict[int, Web_API_Thread] = {}
		self.thread_limit = 2
		global web_Thread_Manager
		web_Thread_Manager = self

	def run(self):
		logger.info("Web_Thread_Manager running")
		while True:
			time.sleep(self.idle_time)
			for thread_id, thread in self.threads.items():
				if not thread.is_alive():
					logger.info(f"Thread {thread_id} cleaned")
					del self.threads[thread_id]
				elif (datetime.now() - thread.last_call).total_seconds() > self.idle_time:
					thread.exit_flag = True

	def access_thread(self, thread_id):
		if thread_id not in self.threads:
			logger.error("Thread not found")
			raise threading.ThreadError("Thread not found")
		logger.debug(f"Thread {thread_id} accessed")
		return self.threads[thread_id]

	def new_thread(self, thread_id):
		if thread_id in self.threads:
			logger.debug(f"Thread {thread_id} already exists")
			return self.threads[thread_id]
		if len(self.threads) >= self.thread_limit:
			logger.error("Thread limit reached")
			raise threading.ThreadError("Thread limit reached")
		thread = Web_API_Thread(thread_id)
		thread.start()
		logger.debug(f"Thread {thread_id} created and started")
		return thread
