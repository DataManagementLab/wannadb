"""Scoped Celery work, feedback commands and safe worker lifecycle handling."""
import logging
import inspect
import hashlib
import json
import time
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional, Any, Union

from celery import Task
from celery.exceptions import Ignore, SoftTimeLimitExceeded, TaskPredicate, TimeLimitExceeded, WorkerLostError
from celery.signals import task_failure, task_revoked

from wannadb.data.data import Document, Attribute, InformationNugget
from wannadb.statistics import Statistics
from wannadb_web.Redis.RedisCache import TaskAccess, TaskAdmission, SessionState, set_signal_scope, get_signal_scope
from wannadb_web.SQLite.table_query import TableQueryError, query_document_table
from wannadb_web.limits import (
	COMPUTE_SECONDS, MAX_BASE_DOCUMENTS, MAX_COMPUTE_TASKS, MAX_COMPUTE_TASKS_PER_USER, QUEUE_SECONDS, WorkLimitError,
	validate_attribute_count, validate_corpus,
)
from wannadb_web.postgres.attribute_schema import AttributeSchemaConflict, edit_attribute_schema
from wannadb_web.postgres.feedback_sessions import FeedbackSessionConflict, close_session, extend_session_step, load_session
from wannadb_web.postgres.queries import get_creation_documents, get_base_id, get_feedback_outcome
from wannadb_web.worker.data import DoAttributeRanking, MultiNuggetsMatchFeedback, ReloadDocumentBase, Signals, NoMatchFeedback, NuggetMatchFeedback, CustomMatchFeedback, SkipAttributeRanking, StopMatching
from wannadb_web.worker.runtime import configure_torch_threads
from wannadb_web.worker.util import State
from wannadb_web.postgres.transactions import PublicSuggestionConflict, review_public_suggestion

logger = logging.getLogger(__name__)

_ADMISSION_HEADER = "wannadb_admission"
_FEEDBACK_QUEUE = "feedback"


def _task_user_id(args, kwargs):
	"""Read the submitting user from positional or keyword task arguments.

	:param args: Positional task/callback arguments.
	:type args: tuple[object, ...]
	:param kwargs: Keyword task/callback arguments.
	:type kwargs: dict[str, object]
	:returns: The task user id result.
	:rtype: int | None
	"""
	return (kwargs or {}).get("user_id", args[0] if args else None)


def _request_fingerprint(task_name, parameters):
	"""Hash the task name and normalized parameters for exact replay validation.

	:param task_name: The registered Celery task name included in the replay fingerprint.
	:type task_name: str
	:param parameters: Bound task arguments used to validate exact submission identity.
	:type parameters: dict[str, object]
	:returns: The request fingerprint text or identifier.
	:rtype: str
	"""
	return hashlib.sha256(json.dumps([task_name, parameters], sort_keys=True).encode()).hexdigest()


class BaseTask(Task):
	"""Shared task admission, authorization, safe errors and lazy worker resource loading."""
	name = "BaseTask"
	soft_time_limit = COMPUTE_SECONDS
	time_limit = COMPUTE_SECONDS + 30
	@property
	def _signals(self):
		"""Return signal adapters for the authorized task-local user/base/session scope.

		:returns: The signals result.
		:rtype: Signals
		:raises PermissionError: If the operation cannot satisfy its state or persistence
		    preconditions.
		"""
		scope = get_signal_scope()
		if scope is None:
			raise PermissionError("No task session selected")
		return Signals(str(scope["user_id"]))


	def __init__(self):
		"""Initialize BaseTask with its supplied dependencies and scope.
		"""
		super().__init__()

	def run(self, *args, **kwargs):
		"""Define the abstract task body that concrete web tasks must implement.

		:param args: Positional task/callback arguments.
		:type args: tuple[object, ...]
		:param kwargs: Keyword task/callback arguments.
		:type kwargs: dict[str, object]
		:raises NotImplementedError: When the abstract operation has no concrete implementation.
		"""
		raise NotImplementedError("BaseTask is abstract")

	def __call__(self, *args, **kwargs):
		"""Run a task with safe public error classification and timing logs.

		:param args: Positional task/callback arguments.
		:type args: tuple[object, ...]
		:param kwargs: Keyword task/callback arguments.
		:type kwargs: dict[str, object]
		:returns: The concrete task result; failures are classified before a safe exception is
		    raised.
		:rtype: object
		:raises RuntimeError: If the operation cannot satisfy its state or persistence
		    preconditions.
		"""
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
		"""Reserve capacity and submit a scoped task with redacted broker arguments.

		:param args: Positional task/callback arguments.
		:type args: tuple[object, ...]
		:param kwargs: Keyword task/callback arguments.
		:type kwargs: dict[str, object]
		:param task_id: The scoped Celery task/command UUID.
		:type task_id: str | None
		:param options: Additional client, task or worker options.
		:type options: dict[str, object]
		:returns: The handle for the admitted task or an exactly matching previous submission.
		:rtype: celery.result.AsyncResult
		:raises ValueError: If an input fails validation for this operation.
		:raises PermissionError: If the operation cannot satisfy its state or persistence
		    preconditions.
		"""
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
		"""Claim admission and establish authorized task/session scope before execution.

		:param task_id: The scoped Celery task/command UUID.
		:type task_id: str
		:param args: Positional task/callback arguments.
		:type args: tuple[object, ...]
		:param kwargs: Keyword task/callback arguments.
		:type kwargs: dict[str, object]
		:raises Ignore: If the operation cannot satisfy its state or persistence preconditions.
		:raises PermissionError: If the operation cannot satisfy its state or persistence
		    preconditions.
		"""
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
		"""Finalize publication/admission and clear task-local state even if cleanup fails.

		:param status: The state, HTTP status or emitted value required here.
		:type status: str | int | object
		:param retval: The task's returned value.
		:type retval: object
		:param task_id: The scoped Celery task/command UUID.
		:type task_id: str
		:param args: Positional task/callback arguments.
		:type args: tuple[object, ...]
		:param kwargs: Keyword task/callback arguments.
		:type kwargs: dict[str, object]
		:param einfo: Celery exception information for task finalization.
		:type einfo: object
		"""
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
	def load() -> None:
		"""Initialize CPU thread settings and model resources lazily in the worker process.
		"""
		configure_torch_threads()
		from wannadb import resources

		if resources.MANAGER is None:
			resources.ResourceManager()
			BaseTask.load()
			return
		logger.debug("Worker resources ready.")

	@staticmethod
	def _create_api(user_id, base_name, organisation_id, **options):
		# Task submission uses these same classes in the Flask API.
		"""Construct the worker-local orchestrator only when task processing needs it.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:param options: Additional client, task or worker options.
		:type options: dict[str, object]
		:returns: The create api result.
		:rtype: WannaDB_WebAPI
		"""
		from wannadb_web.worker.Web_API import WannaDB_WebAPI

		return WannaDB_WebAPI(user_id, base_name, organisation_id, **options)

	def update(self,
			   state: State,
			   meta: Optional[dict[str, Any]] = None,
			   ) -> None:
		"""Publish a task state using the stable web state enumeration.

		:param state: The current serialized/worker matching state.
		:type state: State
		:param meta: The safe task metadata to publish alongside its state.
		:type meta: Optional[dict[str, Any]]
		"""
		super().update_state(state=state.value, meta=meta)

	def update_state(self,
					 task_id: Optional[str] = None,
					 state: Optional[str] = None,
					 meta: Any = None,
					 **kwargs: Any
					 ) -> None:
		"""Publish scoped task metadata without a second non-atomic base payload.

		:param task_id: The scoped Celery task/command UUID.
		:type task_id: Optional[str]
		:param state: The current serialized/worker matching state.
		:type state: Optional[str]
		:param meta: The safe task metadata to publish alongside its state.
		:type meta: Any
		:param kwargs: Keyword task/callback arguments.
		:type kwargs: dict[str, Any]
		:raises NotImplementedError: When the abstract operation has no concrete implementation.
		"""
		raise NotImplementedError("user update() instead")

	@staticmethod
	def check_api_error(api):
		"""Raise when the worker API has published a task error.

		:param api: The worker-local orchestrator for the authorized base.
		:type api: WannaDB_WebAPI
		:raises RuntimeError: If the operation cannot satisfy its state or persistence
		    preconditions.
		"""
		if api.signals.error.msg is not None:
			raise RuntimeError("TASK_FAILED")

	def finish(self, api, persist: bool = False):
		"""Optionally persist, complete the task publication and return a success receipt.

		:param api: The worker-local orchestrator for the authorized base.
		:type api: WannaDB_WebAPI
		:param persist: Whether to save the staged canonical snapshot before task completion.
		:type persist: bool
		:returns: The finish mapping.
		:rtype: dict[str, object]
		"""
		self.check_api_error(api)
		if persist:
			api.update_document_base_to_bson()
			self.check_api_error(api)
		api.complete_session()
		return {"ok": True}


@task_revoked.connect
def _release_revoked_task(sender, request, terminated, expired, **kwargs):
	"""Release admission/publication state when Celery reports a revoked task.

	:param sender: The Celery sender for the lifecycle signal.
	:type sender: celery.Task
	:param request: The Celery request describing the affected execution.
	:type request: object
	:param terminated: Whether Celery terminated the revoked task execution.
	:type terminated: bool
	:param expired: Whether Celery revoked this task because its execution deadline expired.
	:type expired: bool
	:param kwargs: Keyword task/callback arguments.
	:type kwargs: dict[str, object]
	"""
	if isinstance(sender, BaseTask):
		user_id = _task_user_id(request.args, request.kwargs)
		if user_id is not None:
			admission = TaskAdmission("celery", user_id, request.id)
			admission.finish("EXPIRED" if expired else "REVOKED",
				expected_state="" if terminated else "QUEUED",
				legacy=not (request.headers or {}).get(_ADMISSION_HEADER))


@task_failure.connect
def _release_lost_task(sender, task_id, exception, args, kwargs, **extra):
	"""Finalize admission when Celery reports a failed or lost task execution.

	:param sender: The Celery sender for the lifecycle signal.
	:type sender: celery.Task
	:param task_id: The scoped Celery task/command UUID.
	:type task_id: str
	:param exception: The worker failure to classify without exposing sensitive details.
	:type exception: BaseException
	:param args: Positional task/callback arguments.
	:type args: tuple[object, ...]
	:param kwargs: Keyword task/callback arguments.
	:type kwargs: dict[str, object]
	:param extra: Additional Celery signal metadata.
	:type extra: dict[str, object]
	"""
	if isinstance(sender, BaseTask) and isinstance(exception, (WorkerLostError, TimeLimitExceeded)):
		user_id = _task_user_id(args, kwargs)
		if user_id is not None:
			TaskAdmission("celery", user_id, task_id).finish("FAILURE")


class CreateDocumentBase(BaseTask):
	"""Preprocess selected inputs and commit the new base and source links atomically."""
	name = "CreateDocumentBase"

	def run(self, user_id: int, document_ids: list[int], attributes_strings: list[str],
			base_name: str, organisation_id: int):
		"""Preprocess selected inputs and commit the new base and source links atomically.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param document_ids: The selected source IDs or publication name-to-ID map.
		:type document_ids: list[int]
		:param attributes_strings: The requested distinct attribute display names.
		:type attributes_strings: list[str]
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:returns: The run mapping.
		:rtype: dict[str, object]
		:raises WorkLimitError: A source-document, corpus or other web work budget was exceeded.
		:raises ValueError: If an input fails validation for this operation.
		"""
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
	"""Load a scoped base or evaluate and cache a bounded SQL query."""
	name = "DocumentBaseLoad"

	def run(self, user_id: int, base_name: str, organisation_id: int, include_automatic_matches=False, sql_query=None, confirmed_only=False):
		"""Load a scoped base or evaluate and cache a bounded SQL query.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:param include_automatic_matches: Whether provisional automatic matches are included in the
		    projection.
		:type include_automatic_matches: bool
		:param sql_query: The read-only SQL text to evaluate.
		:type sql_query: str | None
		:param confirmed_only: Whether provisional matches must be excluded from the SQL view.
		:type confirmed_only: bool
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
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
	"""Preprocess additions and commit their raw rows and base snapshot together."""
	name = "DocumentBaseAddDocument"

	def run(self, user_id: int, documents: list[list[str]], base_name: str, organisation_id: int):
		"""Preprocess additions and commit their raw rows and base snapshot together.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param documents: The document set or names/text references processed by this helper.
		:type documents: list[list[str]]
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		api.mutate_documents(additions=[Document(name, content) for name, content in documents])
		return self.finish(api)


class DocumentBaseRemoveDocument(BaseTask):
	"""Remove the selected source document from its authorized base."""
	name = "DocumentBaseRemoveDocument"

	def run(self, user_id: int, document_name: str, base_name: str, organisation_id: int, document_id: int):
		"""Remove the selected source document from its authorized base.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param document_name: The exact source-document display name.
		:type document_name: str
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:param document_id: The source-document database ID.
		:type document_id: int
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		api.mutate_documents(removal=(document_id, document_name))
		return self.finish(api)


class DocumentBaseUpdateDocument(BaseTask):
	"""Reprocess replacement text against the displayed original source."""
	name = "DocumentBaseUpdateDocument"

	def run(self, user_id: int, document_name: str, document_content: str, base_name: str, organisation_id: int,
			document_id: int, old_content: str):
		"""Reprocess replacement text against the displayed original source.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param document_name: The exact source-document display name.
		:type document_name: str
		:param document_content: The proposed complete replacement source text.
		:type document_content: str
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:param document_id: The source-document database ID.
		:type document_id: int
		:param old_content: The original source text required by the replacement guard.
		:type old_content: str
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		api.mutate_documents(replacement=(document_id, old_content, Document(document_name, document_content)))
		return self.finish(api)


class DocumentBaseUpdateAttributes(BaseTask):
	"""Apply explicit attribute-schema operations against the displayed schema UUID."""
	name = "DocumentBaseUpdateAttributes"

	def run(self, user_id: int, operations: list[dict], base_name: str, organisation_id: int, expected_version: str):
		"""Apply explicit attribute-schema operations against the displayed schema UUID.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param operations: Validated explicit attribute add/remove/rename operations.
		:type operations: list[dict]
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:param expected_version: The displayed session integer version or schema UUID required by
		    this operation.
		:type expected_version: str
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
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
	"""Apply an owner decision against exact suggestion identities and revisions."""
	name = "ReviewPublicSuggestion"

	def run(self, user_id, base_name, organisation_id, base_id, document_id, review, accepted):
		"""Apply an owner decision against exact suggestion identities and revisions.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:param base_id: The selected document-base database ID.
		:type base_id: int
		:param document_id: The source-document database ID.
		:type document_id: int
		:param review: The displayed owner-review identities and expected revisions.
		:type review: dict[str, object]
		:param accepted: Whether the owner accepts rather than rejects the correction.
		:type accepted: bool
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
		def prepare_nugget(nugget):
			"""Prepare an accepted correction before its guarded owner-review commit.

			:param nugget: The exact selected candidate or custom candidate text.
			:type nugget: InformationNugget | str
			"""
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


class DocumentBaseInteractiveTablePopulation(BaseTask):
	"""Open a resumable matching session on the dedicated feedback queue."""
	name = "DocumentBaseInteractiveTablePopulation"
	queue = _FEEDBACK_QUEUE
	track_started = False  # STARTED below means the base is loaded, not just dequeued.

	def run(self, user_id: int, base_name: str, organisation_id: int):
		"""Open a resumable matching session on the dedicated feedback queue.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
		self.load()
		api = self._create_api(user_id, base_name, organisation_id, build_query_cache=False)
		api.load_document_base_from_bson(publish_to_ui=False)
		self.check_api_error(api)
		self.update(State.STARTED)
		api.start_interactive_table_population()
		return {"ok": True}


class FeedbackTask(BaseTask):
	# Each command performs one bounded compute step, then releases the worker.
	"""One bounded decision step fenced by session version, command identity and lease."""
	queue = _FEEDBACK_QUEUE

	def _durable_replay(self, parameters, outcome, session_id, expected_version, command_id):
		"""Validate exact saved command parameters and return its existing result handle.

		:param parameters: Bound task arguments used to validate exact submission identity.
		:type parameters: dict[str, object]
		:param outcome: The saved command receipt used for recovery/replay.
		:type outcome: dict[str, object]
		:param session_id: The parent feedback-session UUID.
		:type session_id: str
		:param expected_version: The displayed session integer version or schema UUID required by
		    this operation.
		:type expected_version: int | str
		:param command_id: The unique decision UUID used for exact replay.
		:type command_id: str
		:returns: The Celery handle for this scoped task or exact command replay.
		:rtype: celery.result.AsyncResult
		:raises ValueError: If an input fails validation for this operation.
		"""
		if (outcome["session_id"] != session_id or outcome["command_id"] != command_id or
			outcome["expected_version"] != expected_version or
			outcome["request_fingerprint"] != _request_fingerprint(self.name, parameters)):
			raise ValueError("Task ID belongs to different request parameters")
		return self.AsyncResult(task_id=command_id)

	def existing_submission(self, args, *, session_id, expected_version, command_id, durable_outcome=None):
		"""Return an exact replay of a recorded command without queuing it again.

		:param args: Positional task/callback arguments.
		:type args: tuple[object, ...]
		:param session_id: The parent feedback-session UUID.
		:type session_id: str
		:param expected_version: The displayed session integer version or schema UUID required by
		    this operation.
		:type expected_version: int | str
		:param command_id: The unique decision UUID used for exact replay.
		:type command_id: str
		:param durable_outcome: A previously committed command receipt for exact replay.
		:type durable_outcome: dict[str, object] | None
		:returns: The existing exact command result handle, or None when no submission is recorded.
		:rtype: celery.result.AsyncResult | None
		:raises ValueError: If an input fails validation for this operation.
		"""
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
		"""Claim one exact decision lease, advance its durable checkpoint and publish safely.

		:param feedback: The feedback payload or adapter used by this step.
		:type feedback: dict[str, object] | object
		:raises PermissionError: If the operation cannot satisfy its state or persistence
		    preconditions.
		:raises FeedbackSessionConflict: A feedback command no longer matches its durable
		    checkpoint or source.
		:raises ValueError: If an input fails validation for this operation.
		:raises RuntimeError: If the operation cannot satisfy its state or persistence
		    preconditions.
		"""
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
	"""Start, reset or skip the exact attribute waiting in a feedback session."""
	name = "DocumentBaseStartRanking"

	@staticmethod
	def payload(do_attribute: bool, reset: bool, attribute: str):
		"""Encode the explicit start/reset/skip decision for the waiting attribute.

		:param do_attribute: Whether to rank the waiting attribute rather than skip it.
		:type do_attribute: bool
		:param reset: Whether to clear previous ranking progress before starting the attribute.
		:type reset: bool
		:param attribute: The selected attribute name or domain attribute, as required here.
		:type attribute: str
		:returns: The payload mapping.
		:rtype: dict[str, object]
		"""
		feedback = DoAttributeRanking(reset) if do_attribute else SkipAttributeRanking()
		return dict(feedback.to_json(), attribute=attribute)

	def run(self, user_id: int, do_attribute: bool, reset: bool, attribute: str):
		"""Start, reset or skip the exact attribute waiting in a feedback session.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param do_attribute: Whether to rank the waiting attribute rather than skip it.
		:type do_attribute: bool
		:param reset: Whether to clear previous ranking progress before starting the attribute.
		:type reset: bool
		:param attribute: The selected attribute name or domain attribute, as required here.
		:type attribute: str
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
		self.apply_decision(self.payload(do_attribute, reset, attribute))
		return {"ok": True}


class DocumentBaseStopMatching(FeedbackTask):
	"""Stop the current ranked attribute while allowing the session to continue."""
	name = "DocumentBaseStopMatching"

	def run(self, user_id: int):

		"""Stop the current ranked attribute while allowing the session to continue.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
		self.apply_decision(StopMatching())
		return {"ok": True}


class DocumentBaseCloseFeedbackSession(FeedbackTask):
	"""Close one review session while preserving committed canonical matches."""
	name = "DocumentBaseCloseFeedbackSession"

	def run(self, user_id: int):
		"""Close one review session while preserving committed canonical matches.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""
		self.apply_decision({"message": "close-feedback-session"})
		return {"ok": True}


class ReloadDocumentBaseTask(FeedbackTask):
	"""Refresh a feedback step or resolve an explicit keep/replace conflict choice."""
	name = "ReloadDocumentBase"

	def run(self, user_id: int, conflict_resolution=None):
		"""Refresh a feedback step or resolve an explicit keep/replace conflict choice.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param conflict_resolution: The explicit keep/replace response to a displayed conflict.
		:type conflict_resolution: str | None
		:returns: The run mapping.
		:rtype: dict[str, object]
		:raises ValueError: If an input fails validation for this operation.
		"""
		if conflict_resolution not in (None, "keep", "replace"):
			raise ValueError("Unsupported feedback conflict resolution.")
		payload = ReloadDocumentBase().to_json()
		if conflict_resolution is not None:
			payload["conflict_resolution"] = conflict_resolution
		self.apply_decision(payload)
		return {"ok": True}


class DocumentBaseConfirmNugget(FeedbackTask):
	"""Apply an exact candidate/custom-span decision to the current session."""
	name = "DocumentBaseConfirmNugget"

	def run(
     	self, user_id: int, base_name: str, organisation_id: int,
	 	document_name: str, document_text: str, nugget: str,
	 	start_index: int, end_index: int, not_a_match_text: Optional[str],
   		not_a_match_start_index: Optional[int], not_a_match_end_index: Optional[int]
	):
		"""Apply an exact candidate/custom-span decision to the current session.

		:param user_id: user id
		:type user_id: int
		:param base_name: name of base document
		:type base_name: str
		:param organisation_id: organisation id of the document base
		:type organisation_id: int
		:param document_name: name of the document
		:type document_name: str
		:param document_text: text of the document
		:type document_text: str
		:param nugget: the Nugget that gets confirmed
		:type nugget: str
		:param start_index: start of the nugget in the document (optional) if start and end is None
		    the nugget is not in the document
		:type start_index: int
		:param end_index: end of the nugget in the document (optional) if start and end is None the
		    nugget is not in the document
		:type end_index: int
		:param not_a_match_text: text of the nugget that is not a match
		:type not_a_match_text: Optional[str]
		:param not_a_match_start_index: start of the nugget that is not a match
		:type not_a_match_start_index: Optional[int]
		:param not_a_match_end_index: end of the nugget that is not a match
		:type not_a_match_end_index: Optional[int]
		:returns: The run mapping.
		:rtype: dict[str, object]
		:raises ValueError: If an input fails validation for this operation.
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
	"""Apply one exact selection per distinct document in one feedback command."""
	name = "DocumentBaseConfirmMultipleNuggets"

	def run(self, user_id: int, base_name: str, organisation_id: int,
		documents_and_nuggets: list[tuple[str, str, int, int]]):
		"""Apply one exact selection per distinct document in one feedback command.

		:param user_id: The authenticated account ID selecting the authorized scope.
		:type user_id: int
		:param base_name: The exact document-base display name.
		:type base_name: str
		:param organisation_id: The organization database ID used to scope access.
		:type organisation_id: int
		:param documents_and_nuggets: Document names, source text and exact code-point selections.
		:type documents_and_nuggets: list[tuple[str, str, int, int]]
		:returns: The run mapping.
		:rtype: dict[str, object]
		:raises ValueError: If an input fails validation for this operation.
		"""
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
	"""Reject a candidate or record whole-document No Match for this session."""
	name = "DocumentBaseNoMatchForDocument"

	def run(self, user_id: int, base_name: str, organisation_id: int,
			document_name: str, document_text: str,
   			nugget: Optional[str], start_index: Union[int, None], end_index: Union[int, None]
		):
		"""Reject a candidate or record whole-document No Match for this session.

		:param user_id: user id
		:type user_id: int
		:param base_name: name of base document
		:type base_name: str
		:param organisation_id: organisation id of the document base
		:type organisation_id: int
		:param document_name: name of the document
		:type document_name: str
		:param document_text: text of the document
		:type document_text: str
		:param nugget: the Nugget that gets confirmed
		:type nugget: Optional[str]
		:param start_index: start of the nugget in the document (optional) if start and end is None
		    the nugget is not in the document
		:type start_index: Union[int, None]
		:param end_index: end of the nugget in the document (optional) if start and end is None the
		    nugget is not in the document
		:type end_index: Union[int, None]
		:returns: The run mapping.
		:rtype: dict[str, object]
		"""

		document = Document(document_name, document_text)
		if nugget == "" and start_index == end_index == 0:
			self.apply_decision(NoMatchFeedback(None, None, document))
		else:
			nugget_exist(nugget, document, start_index, end_index)
			self.apply_decision(no_match(nugget, document, start_index, end_index))
		return {"ok": True}


def _validate_feedback_span(document: Document, start_index: int, end_index: int):
	"""Reject an invalid or empty source-text selection before constructing feedback.

	:param document: The selected domain document or serialized source record.
	:type document: Document
	:param start_index: The inclusive Unicode code-point offset.
	:type start_index: int
	:param end_index: The exclusive Unicode code-point offset.
	:type end_index: int
	:raises ValueError: If an input fails validation for this operation.
	"""
	if (not isinstance(document.text, str) or type(start_index) is not int or type(end_index) is not int or
		not 0 <= start_index < end_index <= len(document.text) or not document.text[start_index:end_index].strip()):
		raise ValueError("Selection must be a nonempty span inside the document")


def nugget_exist(nugget: str, document: Document, start_index: int, end_index: int):
	"""Validate the requested source span before checking a custom candidate selection.

	:param nugget: The exact selected candidate or custom candidate text.
	:type nugget: str
	:param document: The selected domain document or serialized source record.
	:type document: Document
	:param start_index: The inclusive Unicode code-point offset.
	:type start_index: int
	:param end_index: The exclusive Unicode code-point offset.
	:type end_index: int
	:returns: True when the operation or predicate succeeds; otherwise False.
	:rtype: bool
	:raises ValueError: If an input fails validation for this operation.
	"""
	_validate_feedback_span(document, start_index, end_index)
	if not isinstance(nugget, str) or document.text[start_index:end_index] != nugget:
		raise ValueError("Selected text does not match the document span")
	return True


def match_feedback(
    nugget: Union[str, InformationNugget], document: Document,
	start_index: Optional[int] = None, end_index: Optional[int] = None,
	not_a_match: Optional[InformationNugget] = None
) -> Union[NuggetMatchFeedback, CustomMatchFeedback]:
    """Generate match feedback for a nugget.

    :param nugget: The exact selected candidate or custom candidate text.
    :type nugget: Union[str, InformationNugget]
    :param document: The selected domain document or serialized source record.
    :type document: Document
    :param start_index: The inclusive Unicode code-point offset.
    :type start_index: Optional[int]
    :param end_index: The exclusive Unicode code-point offset.
    :type end_index: Optional[int]
    :param not_a_match: An optional distinct candidate explicitly rejected by the reviewer.
    :type not_a_match: Optional[InformationNugget]
    :returns: The match feedback result.
    :rtype: Union[NuggetMatchFeedback, CustomMatchFeedback]
    :raises Exception: If required worker state or a dependency is unavailable.
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
    """Generate match feedback for multiple nuggets.

    :param nuggets: The selected candidates, preserving document identity.
    :type nuggets: list[InformationNugget]
    :returns: The multi match feedback result.
    :rtype: MultiNuggetsMatchFeedback
    """
    logger.debug("multi_match_feedback")
    return MultiNuggetsMatchFeedback(nuggets, None)

def no_match(nugget: Union[InformationNugget, str], document: Document, start_index: Optional[int] = None, end_index: Optional[int] = None) -> NoMatchFeedback:
    """Generate no match feedback for a nugget.

    :param nugget: The exact selected candidate or custom candidate text.
    :type nugget: Union[InformationNugget, str]
    :param document: The selected domain document or serialized source record.
    :type document: Document
    :param start_index: The inclusive Unicode code-point offset.
    :type start_index: Optional[int]
    :param end_index: The exclusive Unicode code-point offset.
    :type end_index: Optional[int]
    :returns: The no match result.
    :rtype: NoMatchFeedback
    :raises Exception: If required worker state or a dependency is unavailable.
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
