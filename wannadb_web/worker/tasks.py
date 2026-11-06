import logging
import inspect
import hashlib
import json
import pickle
import time
from uuid import uuid4
from typing import Optional, Any, Union

from celery import Task

import wannadb.resources
from wannadb.data.data import Document, Attribute, InformationNugget
from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache, TaskAccess, SessionState, set_signal_scope, get_signal_scope
from wannadb_web.postgres.queries import get_documents, get_base_id
from wannadb_web.worker.Web_API import WannaDB_WebAPI
from wannadb_web.worker.data import DoAttributeRanking, MultiNuggetsMatchFeedback, ReloadDocumentBase, Signals, NoMatchFeedback, NuggetMatchFeedback, CustomMatchFeedback, SkipAttributeRanking, StopMatching
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
	@property
	def _signals(self):
		scope = get_signal_scope()
		if scope is None:
			raise PermissionError("No task session selected")
		return Signals(str(scope["user_id"]))

	@property
	def _redis_client(self):
		scope = get_signal_scope()
		if scope is None:
			raise PermissionError("No task session selected")
		return RedisCache(str(scope["user_id"]))

	def __init__(self):
		super().__init__()

	def run(self, *args, **kwargs):
		raise NotImplementedError("BaseTask is abstract")

	def apply_async(self, args=None, kwargs=None, task_id=None, **options):
		parameters = inspect.signature(self.run).bind_partial(*(args or ()), **(kwargs or {})).arguments
		user_id = parameters.get("user_id")
		if user_id is None:
			raise ValueError("A task requires an authenticated user.")
		access = TaskAccess(user_id)
		if isinstance(self, FeedbackTask):
			session_id = options.pop("session_id", None)
			expected_version = options.pop("expected_version", None)
			command_id = options.pop("command_id", None)
			parent = access.task(session_id) if session_id else None
			if (not access.permitted(parent) or not parent.get("interactive") or
				parent.get("session_id") != session_id or not isinstance(command_id, str) or
				type(expected_version) is not int or expected_version < 1):
				raise PermissionError("An authorized interactive session and version are required.")
			if (("organisation_id" in parameters and int(parameters["organisation_id"]) != parent["organisation_id"]) or
				("base_name" in parameters and parameters["base_name"] != parent["base_name"])):
				raise PermissionError("The feedback belongs to a different document base.")
			task_id = command_id
			scope = dict(parent, command_id=command_id, expected_version=expected_version,
				request_fingerprint=hashlib.sha256(json.dumps([self.name, parameters], sort_keys=True).encode()).hexdigest())
		else:
			task_id = task_id or str(uuid4())
			organisation_id = parameters.get("organisation_id")
			if organisation_id is None:
				raise PermissionError("A document base is required.")
			scope = {"organisation_id": int(organisation_id), "base_name": parameters.get("base_name"),
				"session_id": task_id, "interactive": isinstance(self, DocumentBaseInteractiveTablePopulation)}
			scope["base_id"] = get_base_id(scope["base_name"], scope["organisation_id"])
			if not access.permitted(scope):
				raise PermissionError("Document base access denied.")
		access.register(task_id, scope)
		return super().apply_async(args=args, kwargs=kwargs, task_id=task_id, **options)

	def before_start(self, task_id, args, kwargs):
		set_signal_scope()
		parameters = inspect.signature(self.run).bind_partial(*args, **kwargs).arguments
		user_id = parameters.get("user_id")
		access = TaskAccess(user_id)
		scope = access.task(task_id)
		if not access.permitted(scope) or not scope.get("session_id"):
			raise PermissionError("Document base access denied.")
		if isinstance(self, FeedbackTask):
			parent = access.task(scope["session_id"])
			if not access.permitted(parent) or not parent.get("interactive"):
				raise PermissionError("Interactive session access denied.")
		if not isinstance(self, FeedbackTask):
			if not SessionState(user_id, scope["base_id"], scope["session_id"]).claim_execution(str(uuid4())):
				raise PermissionError("This task session has already started.")
		set_signal_scope(user_id, scope["base_id"], scope["session_id"],
			scope.get("command_id"), scope.get("expected_version"))
		if not isinstance(self, FeedbackTask):
			SessionState(user_id, scope["base_id"], scope["session_id"]).initialize()

	def after_return(self, status, retval, task_id, args, kwargs, einfo):
		try:
			scope = get_signal_scope()
			if scope is not None:
				session = SessionState(scope["user_id"], scope["base_id"], scope["session_id"])
				if isinstance(self, FeedbackTask):
					if status != "SUCCESS":
						session.reject(task_id, "Feedback could not be queued or was rejected.")
				else:
					message = Signals(str(scope["user_id"])).error.to_json()
					session.close(error=(message or "The session failed.") if status != "SUCCESS" else None)
		finally:
			set_signal_scope()

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

	@staticmethod
	def check_api_error(api):
		if api.signals.error.msg is not None:
			raise RuntimeError("TASK_FAILED")

	def finish(self, api, persist: bool = False):
		self.check_api_error(api)
		if persist:
			api.update_document_base_to_bson()
			self.check_api_error(api)
		api.complete_session()
		return {"ok": True}

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
		api = WannaDB_WebAPI(user_id, base_name, organisation_id, timeout=len(document_ids) * 60, build_query_cache=False)

		"""
		Creating document base
		"""
		if not isinstance(attributes[0], Attribute):
			raise Exception("Invalid attributes")

		if not isinstance(statistics, Statistics):
			raise Exception("Invalid statistics")

		docs = get_documents(document_ids, user_id, organisation_id)
		if not docs or any(name is None or content is None for name, content in docs):
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
			raise Exception("No documents found")

		api.create_document_base(documents, attributes, statistics)

		self.check_api_error(api)
		api.save_document_base_to_bson()
		return self.finish(api)


class DocumentBaseLoad(BaseTask):
	name = "DocumentBaseLoad"

	def run(self, user_id: int, base_name: str, organisation_id: int):
		self.load()
		api = WannaDB_WebAPI(user_id, base_name, organisation_id, build_query_cache=False)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		return self.finish(api)


class DocumentBaseAddDocument(BaseTask):
	name = "DocumentBaseAddDocument"

	def run(self, user_id: int, document_name: str, document_content: str, base_name: str, organisation_id: int):
		self.load()
		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		api.add_document(Document(document_name, document_content))
		return self.finish(api, persist=True)


class DocumentBaseRemoveDocument(BaseTask):
	name = "DocumentBaseRemoveDocument"

	def run(self, user_id: int, document_name: str, base_name: str, organisation_id: int):
		self.load()
		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		_doc = None
		for doc in api._document_base.documents:
			if doc.name == document_name:
				_doc = doc
				break
		if _doc is None:
			raise Exception(f"Document with name {document_name} not found")
		api.remove_document(_doc)
		return self.finish(api, persist=True)


class DocumentBaseUpdateDocument(BaseTask):
	name = "DocumentBaseUpdateDocument"

	def run(self, user_id: int, document_name: str, document_content: str, base_name: str, organisation_id: int):
		self.load()
		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		api.update_document(Document(document_name, document_content))
		return self.finish(api, persist=True)


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
		self.check_api_error(api)
		api.add_attributes(attributes)
		return self.finish(api, persist=True)


class DocumentBaseUpdateAttributes(BaseTask):
	name = "DocumentBaseUpdateAttributes"

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
		self.check_api_error(api)
		api.update_attributes(attributes)
		return self.finish(api, persist=True)


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
		self.check_api_error(api)
		api.remove_attributes(attributes)
		return self.finish(api, persist=True)


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
		self.check_api_error(api)
		api.forget_matches()
		return self.finish(api, persist=True)


class DocumentBaseForgetMatchesForAttribute(BaseTask):
	name = "DocumentBaseForgetMatchesForAttribute"

	def run(self, user_id: int, attribute_string: str, base_name: str, organisation_id: int):
		self.load()

		attribute = (Attribute(attribute_string))

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		api.forget_matches_for_attribute(attribute)
		return self.finish(api, persist=True)


class DocumentBaseInteractiveTablePopulation(BaseTask):
	name = "DocumentBaseInteractiveTablePopulation"
	track_started = False  # STARTED below means the base is loaded, not just dequeued.

	def run(self, user_id: int, base_name: str, organisation_id: int):
		self.load()

		api = WannaDB_WebAPI(user_id, base_name, organisation_id, build_query_cache=False)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		# Preserve F08 readiness: this task's base is loaded before STARTED.
		self.update(State.STARTED)
		try:
			api.interactive_table_population()
		except TimeoutError:
			# Preserve completed feedback on idle timeout, then report task failure.
			api.update_document_base_to_bson()
			raise
		return self.finish(api, persist=True)


class FeedbackTask(BaseTask):
	# Keep feedback runnable while compute workers wait for user input.
	queue = "feedback"

	def emit_command(self, feedback):
		record = self._signals.match_feedback.emit(feedback)
		if record.get("state") == "rejected":
			raise RuntimeError(record.get("error") or "Feedback was rejected.")
		return record


class DocumentBaseStartRanking(FeedbackTask):
	name = "DocumentBaseStartRanking"

	def run(self, user_id: int, do_attribute: bool):

		if do_attribute:
			self.emit_command(DoAttributeRanking())
		else:
			self.emit_command(SkipAttributeRanking())
		return {"ok": True}


class DocumentBaseStopMatching(FeedbackTask):
	name = "DocumentBaseStopMatching"

	def run(self, user_id: int):

		self.emit_command(StopMatching())
		return {"ok": True}


class ReloadDocumentBaseTask(FeedbackTask):
	name = "ReloadDocumentBase"

	def run(self, user_id: int):

		self.emit_command(ReloadDocumentBase())
		return {"ok": True}


class DocumentBaseGetOrderedNuggets(BaseTask):
	name = "DocumentBaseGetOrderedNuggets"

	def run(self, user_id: int, base_name: str, organisation_id: int, document_name: str, document_content: str):
		self.load()

		api = WannaDB_WebAPI(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		# api.get_ordert_nuggets(document_id)
		api.get_ordered_nuggets_by_doc_name(document_name, document_content)
		# no need to update the document base
		return self.finish(api)


class DocumentBaseConfirmNugget(FeedbackTask):
	name = "DocumentBaseConfirmNugget"

	def run(
     	self, user_id: int, base_name: str, organisation_id: int,
	 	document_name: str, document_text: str, nugget: str,
	 	start_index: int, end_index: int, not_a_match_text: Optional[str],
   		not_a_match_start_index: Optional[int], not_a_match_end_index: Optional[int]
	):
		"""
		:param user_id: user id
		:param base_name: name of base document
		:param organisation_id: organisation id of the document base
		:param document_name: name of the document
		:param document_text: text of the document
		:param nugget: the Nugget that gets confirmed
		:param start_index: start of the nugget in the document (optional) if start and end is None the nugget is not in the document
		:param end_index: end of the nugget in the document (optional) if start and end is None the nugget is not in the document
		:param not_a_match_text: text of the nugget that is not a match
		:param not_a_match_start_index: start of the nugget that is not a match
		:param not_a_match_end_index: end of the nugget that is not a match
		"""
  
		document = Document(document_name, document_text)
  
		if nugget is None:
			nugget = InformationNugget(document=document, start_char=int(start_index), end_char=int(end_index))
		not_a_match = InformationNugget(document=document, start_char=not_a_match_start_index, end_char=not_a_match_end_index) if not_a_match_text else None

		self.emit_command(match_feedback(nugget, document, start_index, end_index, not_a_match=not_a_match))
		# no need to update the document base the doc will be saved in the interactive call
		return {"ok": True}
	

class DocumentBaseConfirmMultipleNuggets(FeedbackTask):
	name = "DocumentBaseConfirmMultipleNuggets"

	def run(self, user_id: int, base_name: str, organisation_id: int,
			documents_and_nuggets: list[tuple[str, str, int, int]],
			interactive_call_task_id: str):
		"""
		:param user_id: user id
		:param base_name: name of base document
		:param organisation_id: organisation id of the document base
		:param document_name: name of the document
		:param document_text: text of the document
		:param nuggets: list of nuggets to confirm
		:param interactive_call_task_id: the same task id that's used for interactive call
		"""
		raise ValueError("Bulk confirmation is unavailable until F14 is repaired; confirm individual matches.")


class DocumentBaseNoMatchForDocument(FeedbackTask):
	name = "DocumentBaseNoMatchForDocument"

	def run(self, user_id: int, base_name: str, organisation_id: int,
			document_name: str, document_text: str,
   			nugget: Optional[str], start_index: Union[int, None], end_index: Union[int, None]
		):
		"""
		:param user_id: user id
		:param base_name: name of base document
		:param organisation_id: organisation id of the document base
		:param document_name: name of the document
		:param document_text: text of the document
		:param nugget: the Nugget that gets confirmed
		:param start_index: start of the nugget in the document (optional) if start and end is None the nugget is not in the document
		:param end_index: end of the nugget in the document (optional) if start and end is None the nugget is not in the document
		"""

		document = Document(document_name, document_text)
		if nugget is None:
			nugget = InformationNugget(document=document, start_char=int(start_index), end_char=int(end_index))
	
		self.emit_command(no_match(nugget, document, int(start_index), int(end_index)))
		# no need to update the document base the doc will be saved in the interactive call
		return {"ok": True}


def nugget_exist(nugget: str, document: Document, start_index: int, end_index: int):
	try:
		if document.text[start_index:end_index] == nugget:
			return True
	except IndexError:
		logger.error("Nugget does not exist in the given Text")
		raise Exception("Nugget does not exist in the given Text")
	logger.error("Nugget does not exist in the given Text")
	raise Exception("Nugget does not exist in the given Text")


def match_feedback(
    nugget: Union[str, InformationNugget], document: Document,
	start_index: Optional[int] = None, end_index: Optional[int] = None,
	not_a_match: Optional[InformationNugget] = None
) -> Union[NuggetMatchFeedback, CustomMatchFeedback]:
    """
    Generate match feedback for a nugget.
    """
    if isinstance(nugget, str):
        if document is None:
            logger.error("The document is missing in document base")
            raise Exception("The document is missing in document base")
        if start_index is None or end_index is None:
            logger.error("Start-index or end-index are missing to find the custom nugget")
            raise Exception("Start-index or end-index are missing to find the custom nugget")
        print(f"nugget: {nugget}, document: {document.name}, start_index: {int(start_index)}, end_index: {int(end_index)}")
        return CustomMatchFeedback(document, start_index, end_index)
    if isinstance(nugget, InformationNugget):
        return NuggetMatchFeedback(nugget, not_a_match)
    raise Exception("Invalid nugget type")

def multi_match_feedback(nuggets: list[InformationNugget]):
    """
    Generate match feedback for multiple nuggets.
    """
    logger.debug("multi_match_feedback")
    return MultiNuggetsMatchFeedback(nuggets)

def no_match(nugget: Union[InformationNugget, str], document: Document, start_index: Optional[int] = None, end_index: Optional[int] = None) -> NoMatchFeedback:
    """
    Generate no match feedback for a nugget.
    """
    if isinstance(nugget, str):
        if document is None:
            logger.error("The document is missing in document base")
            raise Exception("The document is missing in document base")
        if start_index is None or end_index is None:
            logger.error("Start-index or end-index are missing to find the custom nugget")
            raise Exception("Start-index or end-index are missing to find the custom nugget")
        nugget = InformationNugget(document=document, start_char=start_index, end_char=end_index)
        return NoMatchFeedback(nugget, nugget)
    return NoMatchFeedback(nugget, nugget)
