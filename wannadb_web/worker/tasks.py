import logging
import inspect
import hashlib
import json
import pickle
import time
from uuid import uuid4
from typing import Optional, Any, Union

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded, TaskPredicate

import wannadb.resources
from wannadb.data.data import Document, Attribute, InformationNugget
from wannadb.resources import ResourceManager
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache, TaskAccess, TaskAdmission, SessionState, set_signal_scope, get_signal_scope
from wannadb_web.limits import (
	COMPUTE_SECONDS, MATCHING_SECONDS, MAX_BASE_DOCUMENTS, MAX_COMPUTE_TASKS, MAX_FEEDBACK_TASKS,
	QUEUE_SECONDS, FEEDBACK_QUEUE_SECONDS, FEEDBACK_SECONDS, WorkLimitError,
	validate_attribute_count, validate_corpus,
)
from wannadb_web.postgres.attribute_schema import AttributeSchemaConflict, edit_attribute_schema
from wannadb_web.postgres.queries import get_creation_documents, get_base_id
from wannadb_web.worker.Web_API import WannaDB_WebAPI
from wannadb_web.worker.data import DoAttributeRanking, MultiNuggetsMatchFeedback, ReloadDocumentBase, Signals, NoMatchFeedback, NuggetMatchFeedback, CustomMatchFeedback, SkipAttributeRanking, StopMatching
from wannadb_web.worker.util import State

logger = logging.getLogger(__name__)


def _request_fingerprint(task_name, parameters):
	return hashlib.sha256(json.dumps([task_name, parameters], sort_keys=True).encode()).hexdigest()


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
	soft_time_limit = COMPUTE_SECONDS
	time_limit = COMPUTE_SECONDS + 30
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

	def __call__(self, *args, **kwargs):
		try:
			return super().__call__(*args, **kwargs)
		except TaskPredicate:
			raise
		except SoftTimeLimitExceeded:
			self._signals.error.emit(RuntimeError("TASK_LIMIT"))
			raise RuntimeError("TASK_LIMIT") from None
		except WorkLimitError as error:
			self._signals.error.emit(error)
			raise RuntimeError("WORK_LIMIT") from None
		except Exception as error:
			# Celery records the raised exception and traceback. Keep library/SQL messages private.
			logger.error("Task failed. task=%s error_type=%s", self.name, type(error).__name__)
			raise RuntimeError("TASK_FAILED") from None

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
			durable_outcome = options.pop("durable_outcome", None)
			if durable_outcome is not None:
				return self._durable_replay(parameters, durable_outcome, session_id, expected_version, command_id)
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
				request_fingerprint=_request_fingerprint(self.name, parameters))
		else:
			task_id = task_id or str(uuid4())
			organisation_id = parameters.get("organisation_id")
			if organisation_id is None:
				raise PermissionError("A document base is required.")
			scope = {"organisation_id": int(organisation_id), "base_name": parameters.get("base_name"),
				"session_id": task_id, "interactive": isinstance(self, DocumentBaseInteractiveTablePopulation)}
			if isinstance(self, CreateDocumentBase):
				scope.update(base_id=0, creation=True)
			else:
				scope["base_id"] = get_base_id(scope["base_name"], scope["organisation_id"])
			if not access.permitted(scope):
				raise PermissionError("Document base access denied.")
		feedback = isinstance(self, FeedbackTask)
		queue = "feedback" if feedback else "celery"
		wait_seconds = FEEDBACK_QUEUE_SECONDS if feedback else QUEUE_SECONDS
		admission = TaskAdmission(queue, user_id, task_id)
		reserved = admission.reserve(MAX_FEEDBACK_TASKS if feedback else MAX_COMPUTE_TASKS,
			wait_seconds + self.time_limit + 30)
		try:
			if not reserved and access.task(task_id) is None:
				raise ValueError("The task is being submitted. Retry shortly.")
			access.register(task_id, scope)
			if not reserved:
				return self.AsyncResult(task_id=task_id)
			options.setdefault("expires", wait_seconds)
			options.update(argsrepr="[redacted]", kwargsrepr="[redacted]")
			return super().apply_async(args=args, kwargs=kwargs, task_id=task_id, **options)
		except Exception:
			if reserved:
				admission.release()
			raise

	def before_start(self, task_id, args, kwargs):
		set_signal_scope()
		parameters = inspect.signature(self.run).bind_partial(*args, **kwargs).arguments
		user_id = parameters.get("user_id")
		access = TaskAccess(user_id)
		scope = access.task(task_id)
		if not access.permitted(scope) or not scope.get("session_id"):
			raise PermissionError("Document base access denied.")
		creation = isinstance(self, CreateDocumentBase)
		if creation != (scope.get("creation") is True) or (creation and (
			scope["base_id"] != 0 or scope["base_name"] != parameters.get("base_name") or
			scope["organisation_id"] != parameters.get("organisation_id")
		)):
			raise PermissionError("Task does not match its document base scope.")
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
					message = None
					if status != "SUCCESS":
						message = Signals(str(scope["user_id"])).error.to_json() or "The session failed."
					session.close(error=message)
		except Exception as error:
			# A Redis error in this notification must not change the durable task result.
			logger.warning("Task session finalization failed. task=%s error_type=%s", self.name, type(error).__name__)
		finally:
			set_signal_scope()
			user_id = kwargs.get("user_id", args[0] if args else None)
			if user_id is not None:
				TaskAdmission("feedback" if isinstance(self, FeedbackTask) else "celery", user_id, task_id).release()

	@staticmethod
	def load():
		if wannadb.resources.MANAGER is None:
			wannadb.resources.ResourceManager()
			BaseTask.load()
			return
		logger.debug("Worker resources ready.")

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
				self.update(state=State.SUCCESS, meta={"msg": _input})
				time.sleep(2)
			self.update(state=State.WAITING, meta={"msg": "waiting"})
			time.sleep(2)


class CreateDocumentBase(BaseTask):
	name = "CreateDocumentBase"

	def run(self, user_id: int, document_ids: list[int], attributes_strings: list[str],
			base_name: str, organisation_id: int):
		signals = self._signals
		if isinstance(document_ids, list) and len(document_ids) > MAX_BASE_DOCUMENTS:
			raise WorkLimitError(f"Select at most {MAX_BASE_DOCUMENTS} documents.")
		if (not isinstance(document_ids, list) or not document_ids or
			any(type(doc_id) is not int or not 0 < doc_id <= 9223372036854775807 for doc_id in document_ids) or
			len(set(document_ids)) != len(document_ids) or not isinstance(attributes_strings, list) or not attributes_strings or
			any(not isinstance(name, str) or not name.strip() or "\0" in name for name in attributes_strings) or
			len(set(attributes_strings)) != len(attributes_strings)):
			signals.error.emit(RuntimeError("CREATE_INVALID"))
			raise ValueError("Invalid document or attribute selection.")

		validate_attribute_count(len(attributes_strings))
		signals.status.emit("Reading documents.")
		if get_base_id(base_name, organisation_id) is not None:
			signals.error.emit(RuntimeError("CREATE_CONFLICT"))
			raise ValueError("A document base with this name already exists.")
		try:
			source_documents = get_creation_documents(document_ids, user_id, organisation_id)
		except RuntimeError:
			signals.error.emit(RuntimeError("CREATE_FAILED"))
			raise
		if source_documents is None:
			signals.error.emit(RuntimeError("CREATE_INPUT_CHANGED"))
			raise ValueError("One or more documents are unavailable.")

		try:
			self.load()
			api = WannaDB_WebAPI(user_id, base_name, organisation_id, build_query_cache=False)
		except Exception:
			signals.error.emit(RuntimeError("CREATE_FAILED"))
			raise
		attributes = [Attribute(name) for name in attributes_strings]
		base_id = api.create_document_base(source_documents, attributes, Statistics(False))
		# Celery's result is the acknowledgment. The base is already committed here.
		return {"ok": True, "base_id": base_id}


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

	def run(self, user_id: int, documents: list[list[str]], base_name: str, organisation_id: int):
		self.load()
		api = WannaDB_WebAPI(user_id, base_name, organisation_id, build_query_cache=False)
		api.mutate_documents(additions=[Document(name, content) for name, content in documents])
		return self.finish(api)


class DocumentBaseRemoveDocument(BaseTask):
	name = "DocumentBaseRemoveDocument"

	def run(self, user_id: int, document_name: str, base_name: str, organisation_id: int, document_id: int):
		self.load()
		api = WannaDB_WebAPI(user_id, base_name, organisation_id, build_query_cache=False)
		api.mutate_documents(removal=(document_id, document_name))
		return self.finish(api)


class DocumentBaseUpdateDocument(BaseTask):
	name = "DocumentBaseUpdateDocument"

	def run(self, user_id: int, document_name: str, document_content: str, base_name: str, organisation_id: int,
			document_id: int, old_content: str):
		self.load()
		api = WannaDB_WebAPI(user_id, base_name, organisation_id, build_query_cache=False)
		api.mutate_documents(replacement=(document_id, old_content, Document(document_name, document_content)))
		return self.finish(api)


class DocumentBaseUpdateAttributes(BaseTask):
	name = "DocumentBaseUpdateAttributes"

	def run(self, user_id: int, operations: list[dict], base_name: str, organisation_id: int, expected_version: str):
		try:
			edit_attribute_schema(user_id, get_signal_scope()["base_id"], base_name, organisation_id,
				expected_version, operations)
		except AttributeSchemaConflict:
			self._signals.error.emit(RuntimeError("ATTRIBUTES_CHANGED"))
			raise
		except ValueError as error:
			self._signals.error.emit(error)
			raise
		return {"ok": True}


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
	soft_time_limit = MATCHING_SECONDS
	time_limit = MATCHING_SECONDS + 30
	track_started = False  # STARTED below means the base is loaded, not just dequeued.

	def run(self, user_id: int, base_name: str, organisation_id: int):
		self.load()

		api = WannaDB_WebAPI(user_id, base_name, organisation_id, build_query_cache=False)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		validate_corpus(document.text for document in api.document_base.documents)
		validate_attribute_count(len(api.document_base.attributes))
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
	soft_time_limit = FEEDBACK_SECONDS - 15
	time_limit = FEEDBACK_SECONDS

	def _durable_replay(self, parameters, outcome, session_id, expected_version, command_id):
		if (outcome["session_id"] != session_id or outcome["command_id"] != command_id or
			outcome["expected_version"] != expected_version or
			outcome["request_fingerprint"] != _request_fingerprint(self.name, parameters)):
			raise ValueError("Task ID belongs to different request parameters")
		return self.AsyncResult(task_id=command_id)

	def existing_submission(self, args, *, session_id, expected_version, command_id, durable_outcome=None):
		"""Return an exact replay of a recorded command without queuing it again."""
		parameters = inspect.signature(self.run).bind(*args).arguments
		if durable_outcome is not None:
			return self._durable_replay(parameters, durable_outcome, session_id, expected_version, command_id)
		user_id = parameters["user_id"]
		scope = TaskAccess(user_id).task(command_id)
		if scope is None:
			return None
		if (scope.get("session_id") != session_id or scope.get("command_id") != command_id or
			scope.get("expected_version") != expected_version or
			scope.get("request_fingerprint") != _request_fingerprint(self.name, parameters)):
			raise ValueError("Task ID belongs to different request parameters")
		session = SessionState(user_id, scope["base_id"], session_id)
		return self.AsyncResult(task_id=command_id) if session.command(command_id) is not None else None

	def emit_command(self, feedback):
		record = self._signals.match_feedback.emit(feedback)
		if record.get("state") == "rejected":
			raise RuntimeError(record.get("error") or "Feedback was rejected.")
		return record


class DocumentBaseStartRanking(FeedbackTask):
	name = "DocumentBaseStartRanking"

	@staticmethod
	def payload(do_attribute: bool, reset: bool, attribute: str):
		feedback = DoAttributeRanking(reset) if do_attribute else SkipAttributeRanking()
		return dict(feedback.to_json(), attribute=attribute)

	def run(self, user_id: int, do_attribute: bool, reset: bool, attribute: str):
		self.emit_command(self.payload(do_attribute, reset, attribute))
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
		_validate_feedback_span(document, start_index, end_index)
		if nugget is None:
			nugget = InformationNugget(document=document, start_char=start_index, end_char=end_index)
		else:
			nugget_exist(nugget, document, start_index, end_index)
		not_a_match = None
		if not_a_match_text is not None:
			nugget_exist(not_a_match_text, document, not_a_match_start_index, not_a_match_end_index)
			if (start_index, end_index) == (not_a_match_start_index, not_a_match_end_index):
				raise ValueError("Positive and negative selections must differ")
			not_a_match = InformationNugget(document=document, start_char=not_a_match_start_index, end_char=not_a_match_end_index)

		self.emit_command(match_feedback(nugget, document, start_index, end_index, not_a_match=not_a_match))
		# no need to update the document base the doc will be saved in the interactive call
		return {"ok": True}
	

class DocumentBaseConfirmMultipleNuggets(FeedbackTask):
	name = "DocumentBaseConfirmMultipleNuggets"

	def run(self, user_id: int, base_name: str, organisation_id: int,
		documents_and_nuggets: list[tuple[str, str, int, int]]):
		if not isinstance(documents_and_nuggets, list) or not documents_and_nuggets:
			raise ValueError("Select at least one match")
		nuggets = []
		document_names = set()
		for name, text, start, end in documents_and_nuggets:
			if not isinstance(name, str) or not name or name in document_names:
				raise ValueError("Select one match per document")
			document_names.add(name)
			document = Document(name, text)
			_validate_feedback_span(document, start, end)
			nuggets.append(InformationNugget(document, start, end))
		self.emit_command(multi_match_feedback(nuggets))
		return {"ok": True}


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
		if nugget == "" and start_index == end_index == 0:
			self.emit_command(NoMatchFeedback(None, None, document))
		else:
			nugget_exist(nugget, document, start_index, end_index)
			self.emit_command(no_match(nugget, document, start_index, end_index))
		return {"ok": True}



def _validate_feedback_span(document: Document, start_index: int, end_index: int):
	if (not isinstance(document.text, str) or type(start_index) is not int or type(end_index) is not int or
		not 0 <= start_index < end_index <= len(document.text) or not document.text[start_index:end_index].strip()):
		raise ValueError("Selection must be a nonempty span inside the document")


def nugget_exist(nugget: str, document: Document, start_index: int, end_index: int):
	_validate_feedback_span(document, start_index, end_index)
	if not isinstance(nugget, str) or document.text[start_index:end_index] != nugget:
		raise ValueError("Selected text does not match the document span")
	return True


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
        nugget_exist(nugget, document, start_index, end_index)
        return CustomMatchFeedback(document, start_index, end_index, not_a_match)
    if isinstance(nugget, InformationNugget):
        return NuggetMatchFeedback(nugget, not_a_match)
    raise Exception("Invalid nugget type")

def multi_match_feedback(nuggets: list[InformationNugget]):
    """
    Generate match feedback for multiple nuggets.
    """
    logger.debug("multi_match_feedback")
    return MultiNuggetsMatchFeedback(nuggets, None)

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
