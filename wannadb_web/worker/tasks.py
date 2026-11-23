import logging
import inspect
import hashlib
import json
import pickle
import time
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional, Any, Union

from celery import Task
from celery.exceptions import Ignore, SoftTimeLimitExceeded, TaskPredicate, TimeLimitExceeded, WorkerLostError
from celery.signals import task_failure, task_revoked

from wannadb.data.data import Document, Attribute, InformationNugget
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import RedisCache, TaskAccess, TaskAdmission, SessionState, set_signal_scope, get_signal_scope
from wannadb_web.SQLite.table_query import TableQueryError, query_document_table
from wannadb_web.limits import (
	COMPUTE_SECONDS, MAX_BASE_DOCUMENTS, MAX_COMPUTE_TASKS, MAX_COMPUTE_TASKS_PER_USER, QUEUE_SECONDS, WorkLimitError,
	validate_attribute_count, validate_corpus,
)
from wannadb_web.postgres.attribute_schema import AttributeSchemaConflict, edit_attribute_schema
from wannadb_web.postgres.feedback_sessions import FeedbackSessionConflict, close_session, extend_session_step, load_session
from wannadb_web.postgres.queries import get_creation_documents, get_base_id, get_feedback_outcome
from wannadb_web.worker.data import DoAttributeRanking, MultiNuggetsMatchFeedback, ReloadDocumentBase, Signals, NoMatchFeedback, NuggetMatchFeedback, CustomMatchFeedback, SkipAttributeRanking, StopMatching
from wannadb_web.worker.util import State
from wannadb_web.postgres.transactions import PublicSuggestionConflict, review_public_suggestion

logger = logging.getLogger(__name__)

_ADMISSION_HEADER = "wannadb_admission"
_FEEDBACK_QUEUE = "feedback"


def _task_user_id(args, kwargs):
	return (kwargs or {}).get("user_id", args[0] if args else None)


def _request_fingerprint(task_name, parameters):
	return hashlib.sha256(json.dumps([task_name, parameters], sort_keys=True).encode()).hexdigest()


class InitManager(Task):
	name = "InitManager"

	def run(self, *args, **kwargs):
		from wannadb import resources

		resources.ResourceManager()
		if resources.MANAGER is None:
			raise RuntimeError("Resource_Manager is None!")
		manager = pickle.dumps(resources.MANAGER)
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
		started = time.monotonic()
		try:
			return super().__call__(*args, **kwargs)
		except TaskPredicate:
			raise
		except SoftTimeLimitExceeded:
			if not isinstance(self, FeedbackTask):
				self._signals.error.emit(RuntimeError("TASK_LIMIT"))
			raise RuntimeError("TASK_LIMIT") from None
		except WorkLimitError as error:
			if not isinstance(self, FeedbackTask):
				self._signals.error.emit(error)
			raise RuntimeError("WORK_LIMIT") from None
		except ModuleNotFoundError as error:
			logger.error("Worker module not found. task=%s module=%r", self.name, error.name)
			raise RuntimeError("TASK_FAILED") from None
		except Exception as error:
			# Celery records the raised exception and traceback. Keep library/SQL messages private.
			logger.error("Task failed. task=%s error_type=%s", self.name, type(error).__name__)
			raise RuntimeError("TASK_FAILED") from None
		finally:
			logger.info("Worker task ended. task=%s compute_seconds=%.3f", self.name, time.monotonic() - started)

	def apply_async(self, args=None, kwargs=None, task_id=None, **options):
		parameters = inspect.signature(self.run).bind_partial(*(args or ()), **(kwargs or {})).arguments
		user_id = parameters.get("user_id")
		if user_id is None:
			raise ValueError("A task requires an authenticated user.")
		access = TaskAccess(user_id)
		expected_base_id = options.pop("expected_base_id", None)
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
				if expected_base_id is not None and scope["base_id"] != expected_base_id:
					raise ValueError("The document base changed. Reload before retrying.")
			if isinstance(self, DocumentBaseLoad) and parameters.get("sql_query") is not None:
				scope["table_query"] = True
			if not access.permitted(scope):
				raise PermissionError("Document base access denied.")
		# Both broker queues share one admission budget and status namespace.
		admission = TaskAdmission("celery", user_id, task_id)
		deadline_ms = admission.reserve(scope, MAX_COMPUTE_TASKS, MAX_COMPUTE_TASKS_PER_USER, QUEUE_SECONDS)
		if not deadline_ms:
			return self.AsyncResult(task_id=task_id)
		try:
			headers = dict(options.get("headers") or {})
			headers.update({_ADMISSION_HEADER: True, "wannadb_queued_at": time.time()})
			options.update(argsrepr="[redacted]", kwargsrepr="[redacted]", headers=headers,
				expires=datetime.fromtimestamp(deadline_ms / 1000, tz=timezone.utc))
			return super().apply_async(args=args, kwargs=kwargs, task_id=task_id, **options)
		except Exception:
			# A broker write can succeed even if the producer loses the reply.
			# Cancel only if a worker has not claimed this job.
			admission.finish("FAILURE", expected_state="QUEUED")
			raise

	def before_start(self, task_id, args, kwargs):
		queued_at = (self.request.headers or {}).get("wannadb_queued_at")
		if isinstance(queued_at, (float, int)):
			logger.info("Worker task started. task=%s queue_wait_seconds=%.3f", self.name, max(0, time.time() - queued_at))
		set_signal_scope()
		parameters = inspect.signature(self.run).bind_partial(*args, **kwargs).arguments
		user_id = parameters.get("user_id")
		if (self.request.headers or {}).get(_ADMISSION_HEADER):
			admission = TaskAdmission("celery", user_id, task_id)
			if not admission.start(self.time_limit + 30):
				# Ignore redelivery or late delivery without overwriting an existing result.
				raise Ignore()
			self.request.wannadb_admission_started = True
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
			if scope is not None and not isinstance(self, FeedbackTask):
				# A successful bootstrap returns while the interactive session waits.
				if status != "SUCCESS" or not isinstance(self, DocumentBaseInteractiveTablePopulation):
					session = SessionState(scope["user_id"], scope["base_id"], scope["session_id"])
					message = None
					if status != "SUCCESS":
						message = Signals(str(scope["user_id"])).error.to_json() or "The session failed."
					session.close(error=message)
		except Exception as error:
			# A Redis error in this notification must not change the durable task result.
			logger.warning("Task session finalization failed. task=%s error_type=%s", self.name, type(error).__name__)
		finally:
			set_signal_scope()
			user_id = _task_user_id(args, kwargs)
			if user_id is not None:
				admission = TaskAdmission("celery", user_id, task_id)
				if not (self.request.headers or {}).get(_ADMISSION_HEADER):
					admission.finish(status, legacy=True)
				elif getattr(self.request, "wannadb_admission_started", False):
					admission.finish(status, expected_state="STARTED")

	@staticmethod
	def load():
		from wannadb import resources

		if resources.MANAGER is None:
			resources.ResourceManager()
			BaseTask.load()
			return
		logger.debug("Worker resources ready.")

	@staticmethod
	def _create_api(user_id, base_name, organisation_id, **options):
		# Task submission uses these same classes in the Flask API.
		from wannadb_web.worker.Web_API import WannaDB_WebAPI

		return WannaDB_WebAPI(user_id, base_name, organisation_id, **options)

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


@task_revoked.connect
def _release_revoked_task(sender, request, terminated, expired, **kwargs):
	if isinstance(sender, BaseTask):
		user_id = _task_user_id(request.args, request.kwargs)
		if user_id is not None:
			admission = TaskAdmission("celery", user_id, request.id)
			admission.finish("EXPIRED" if expired else "REVOKED",
				expected_state="" if terminated else "QUEUED",
				legacy=not (request.headers or {}).get(_ADMISSION_HEADER))


@task_failure.connect
def _release_lost_task(sender, task_id, exception, args, kwargs, **extra):
	if isinstance(sender, BaseTask) and isinstance(exception, (WorkerLostError, TimeLimitExceeded)):
		user_id = _task_user_id(args, kwargs)
		if user_id is not None:
			TaskAdmission("celery", user_id, task_id).finish("FAILURE")


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
			api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		except Exception:
			signals.error.emit(RuntimeError("CREATE_FAILED"))
			raise
		attributes = [Attribute(name) for name in attributes_strings]
		base_id = api.create_document_base(source_documents, attributes, Statistics(False))
		# Celery's result is the acknowledgment. The base is already committed here.
		return {"ok": True, "base_id": base_id}


class DocumentBaseLoad(BaseTask):
	name = "DocumentBaseLoad"

	def run(self, user_id: int, base_name: str, organisation_id: int, include_automatic_matches=False, sql_query=None, confirmed_only=False):
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		api.load_document_base_from_bson(publish_to_ui=False)
		self.check_api_error(api)
		if include_automatic_matches or (sql_query is not None and not confirmed_only):
			api.add_automatic_matches_for_preview()
		if sql_query is not None:
			try:
				api.session.store_table_result(query_document_table(api.document_base, sql_query, include_automatic_matches=not confirmed_only))
				return {"ok": True}
			except TableQueryError as error:
				api.signals.error.emit(error)
				raise
		return self.finish(api)


class DocumentBaseAddDocument(BaseTask):
	name = "DocumentBaseAddDocument"

	def run(self, user_id: int, documents: list[list[str]], base_name: str, organisation_id: int):
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		api.mutate_documents(additions=[Document(name, content) for name, content in documents])
		return self.finish(api)


class DocumentBaseRemoveDocument(BaseTask):
	name = "DocumentBaseRemoveDocument"

	def run(self, user_id: int, document_name: str, base_name: str, organisation_id: int, document_id: int):
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		api.mutate_documents(removal=(document_id, document_name))
		return self.finish(api)


class DocumentBaseUpdateDocument(BaseTask):
	name = "DocumentBaseUpdateDocument"

	def run(self, user_id: int, document_name: str, document_content: str, base_name: str, organisation_id: int,
			document_id: int, old_content: str):
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
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


class ReviewPublicSuggestion(BaseTask):
	name = "ReviewPublicSuggestion"

	def run(self, user_id, base_name, organisation_id, base_id, document_id, review, accepted):
		def prepare_nugget(nugget):
			self.load()
			api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
			api.prepare_public_nugget(nugget)
		try:
			review_public_suggestion(user_id, organisation_id, base_id, base_name, document_id,
				attribute_id=review["attributeId"], suggestion_id=review["suggestionId"],
				suggestion_version=review["suggestionVersion"], mapping_revision=review["mappingRevision"],
				source_revision=review["sourceRevision"], start=review["startIndex"], end=review["endIndex"],
				accepted=accepted, prepare_nugget=prepare_nugget)
		except PublicSuggestionConflict:
			self._signals.error.emit(RuntimeError("PUBLIC_REVIEW_CONFLICT"))
			raise
		except PermissionError as error:
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

		api = self._create_api(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		api.forget_matches()
		return self.finish(api, persist=True)


class DocumentBaseForgetMatchesForAttribute(BaseTask):
	name = "DocumentBaseForgetMatchesForAttribute"

	def run(self, user_id: int, attribute_string: str, base_name: str, organisation_id: int):
		self.load()

		attribute = (Attribute(attribute_string))

		api = self._create_api(user_id, base_name, organisation_id)
		api.load_document_base_from_bson()
		self.check_api_error(api)
		api.forget_matches_for_attribute(attribute)
		return self.finish(api, persist=True)


class DocumentBaseInteractiveTablePopulation(BaseTask):
	name = "DocumentBaseInteractiveTablePopulation"
	queue = _FEEDBACK_QUEUE
	track_started = False  # STARTED below means the base is loaded, not just dequeued.

	def run(self, user_id: int, base_name: str, organisation_id: int):
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		api.load_document_base_from_bson(publish_to_ui=False)
		self.check_api_error(api)
		self.update(State.STARTED)
		api.start_interactive_table_population()
		return {"ok": True}


class FeedbackTask(BaseTask):
	# Each command performs one bounded compute step, then releases the worker.
	queue = _FEEDBACK_QUEUE

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

	def apply_decision(self, feedback):
		context = get_signal_scope()
		user_id, command_id = int(context["user_id"]), context["command_id"]
		scope = TaskAccess(user_id).task(command_id)
		if scope is None:
			raise PermissionError("The feedback command scope is no longer available.")
		payload = feedback if isinstance(feedback, dict) else feedback.to_json()
		closing_session = payload["message"] == "close-feedback-session"
		conflict = None
		try:
			current = load_session(user_id, context["session_id"], include_checkpoint=not closing_session)
		except FeedbackSessionConflict as error:
			conflict, current = error, None
		if (current is None or current["closed"] or current["version"] != context["expected_version"] or
			current["base_id"] != context["base_id"]):
			outcome = get_feedback_outcome(user_id, command_id)
			if outcome is not None and all(scope[key] == outcome[key] for key in (
				"session_id", "expected_version", "request_fingerprint",
			)):
				return
			if conflict is not None:
				raise conflict
			raise FeedbackSessionConflict("Feedback has changed or the session expired. Reopen the attribute.")
		session = SessionState.current(user_id)
		lease = str(uuid4())
		lease_seconds = self.time_limit + 30
		record = session.begin_step(command_id, current["version"], payload, lease, lease_seconds)
		if record["state"] == "rejected":
			raise ValueError(record["error"])
		if record.get("lease") != lease:
			# A duplicate delivery must not consume or finish another worker's step.
			return

		api = None
		closed = False
		try:
			if not closing_session and not extend_session_step(
				user_id, context["session_id"], current["version"], lease_seconds):
				raise FeedbackSessionConflict("Feedback has changed or the session expired. Reopen the attribute.")
			self.update(State.STARTED)
			if closing_session:
				version = close_session(user_id, context["session_id"], current["base_id"],
					current["version"], scope)
				closed = True
				if not session.publish_step(version, "finished", None, b"{}", None,
					command_id=command_id, lease=lease):
					raise RuntimeError("The closed feedback session could not be published.")
				return
			self.load()
			api = self._create_api(user_id, scope["base_name"], scope["organisation_id"], build_query_cache=False)
			api.advance_interactive_table_population(current, scope, payload, lease)
		except Exception as error:
			if not closed and (api is None or not api.matching_step_saved):
				message = "Feedback could not be applied. Try the action again."
				if isinstance(error, FeedbackSessionConflict):
					message = str(error)
				elif isinstance(error, SoftTimeLimitExceeded):
					message = "Feedback exceeded the processing time limit."
				try:
					session.fail_step(command_id, lease, message)
				except Exception as cleanup_error:
					logger.warning("Feedback step lease cleanup failed. error_type=%s", type(cleanup_error).__name__)
			raise


class DocumentBaseStartRanking(FeedbackTask):
	name = "DocumentBaseStartRanking"

	@staticmethod
	def payload(do_attribute: bool, reset: bool, attribute: str):
		feedback = DoAttributeRanking(reset) if do_attribute else SkipAttributeRanking()
		return dict(feedback.to_json(), attribute=attribute)

	def run(self, user_id: int, do_attribute: bool, reset: bool, attribute: str):
		self.apply_decision(self.payload(do_attribute, reset, attribute))
		return {"ok": True}


class DocumentBaseStopMatching(FeedbackTask):
	name = "DocumentBaseStopMatching"

	def run(self, user_id: int):

		self.apply_decision(StopMatching())
		return {"ok": True}


class DocumentBaseCloseFeedbackSession(FeedbackTask):
	name = "DocumentBaseCloseFeedbackSession"

	def run(self, user_id: int):
		self.apply_decision({"message": "close-feedback-session"})
		return {"ok": True}


class ReloadDocumentBaseTask(FeedbackTask):
	name = "ReloadDocumentBase"

	def run(self, user_id: int, conflict_resolution=None):
		if conflict_resolution not in (None, "keep", "replace"):
			raise ValueError("Unsupported feedback conflict resolution.")
		payload = ReloadDocumentBase().to_json()
		if conflict_resolution is not None:
			payload["conflict_resolution"] = conflict_resolution
		self.apply_decision(payload)
		return {"ok": True}


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

		self.apply_decision(match_feedback(nugget, document, start_index, end_index, not_a_match=not_a_match))
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
		self.apply_decision(multi_match_feedback(nuggets))
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
			self.apply_decision(NoMatchFeedback(None, None, document))
		else:
			nugget_exist(nugget, document, start_index, end_index)
			self.apply_decision(no_match(nugget, document, start_index, end_index))
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
