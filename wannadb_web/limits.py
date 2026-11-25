"""Configurable web work budgets and source-document admission validation."""
import os
import re


def _positive_setting(name: str, default: int) -> int:
	"""Read a positive integer environment setting or fail configuration validation.

	:param name: The selected display name or operation identifier.
	:type name: str
	:param default: The fallback used when the setting is absent.
	:type default: int
	:returns: The resulting count, version, identifier or status code for this operation.
	:rtype: int
	:raises RuntimeError: If the operation cannot satisfy its state or persistence
	    preconditions.
	"""
	try:
		value = int(os.environ.get(name, default))
	except ValueError:
		value = 0
	if value <= 0:
		raise RuntimeError(f"{name} must be a positive integer.")
	return value


MAX_REQUEST_BYTES = _positive_setting("MAX_REQUEST_BYTES", 16 * 1024 * 1024)
MAX_FILE_BYTES = _positive_setting("MAX_FILE_BYTES", 512 * 1024)
MAX_UPLOAD_FILES = _positive_setting("MAX_UPLOAD_FILES", 32)
MAX_BASE_DOCUMENTS = _positive_setting("MAX_BASE_DOCUMENTS", 256)
MAX_BASE_BYTES = _positive_setting("MAX_BASE_BYTES", 16 * 1024 * 1024)
MAX_DOCUMENT_TOKENS = _positive_setting("MAX_DOCUMENT_TOKENS", 50_000)
MAX_BASE_TOKENS = _positive_setting("MAX_BASE_TOKENS", 250_000)
MAX_ATTRIBUTES = _positive_setting("MAX_ATTRIBUTES", 64)
MAX_COMPUTE_TASKS = _positive_setting("MAX_COMPUTE_TASKS", 32)
MAX_COMPUTE_TASKS_PER_USER = _positive_setting("MAX_COMPUTE_TASKS_PER_USER", 8)
MAX_FEEDBACK_TASKS = _positive_setting("MAX_FEEDBACK_TASKS", 64)
COMPUTE_SECONDS = _positive_setting("COMPUTE_SECONDS", 1800)
MATCHING_SECONDS = _positive_setting("MATCHING_SECONDS", 3600)
QUEUE_SECONDS = _positive_setting("QUEUE_SECONDS", 900)
FEEDBACK_SECONDS = 45
FEEDBACK_QUEUE_SECONDS = 120

_TOKEN_PARTS = re.compile(r"\w+|[^\w\s]")


class WorkLimitError(RuntimeError):
	"""A source-document, corpus or other web work budget was exceeded."""
	pass


class QueueFullError(RuntimeError):
	"""Shared task or active-session admission has no remaining capacity."""
	pass


def validate_document_text(text: str) -> tuple[int, int]:
	"""Validate UTF-8 byte size and estimate a document's admission token cost.

	:param text: The complete source document text.
	:type text: str
	:returns: The UTF-8 byte count and inexpensive token estimate.
	:rtype: tuple[int, int]
	:raises ValueError: If the text cannot be encoded as UTF-8.
	:raises WorkLimitError: If the document exceeds a byte or estimated-token budget.
	"""
	if len(text) > MAX_FILE_BYTES:
		raise WorkLimitError(f"Document text exceeds the {MAX_FILE_BYTES}-byte limit.")
	try:
		byte_count = len(text.encode("utf-8"))
	except UnicodeEncodeError:
		raise ValueError("Document text must be valid UTF-8.") from None
	if byte_count > MAX_FILE_BYTES:
		raise WorkLimitError(f"Document text exceeds the {MAX_FILE_BYTES}-byte limit.")
	# Cheap admission estimate. Longer words count more to account for subword tokenization.
	tokens = 0
	for part in _TOKEN_PARTS.finditer(text):
		tokens += 1 + (part.end() - part.start() - 1) // 8
		if tokens > MAX_DOCUMENT_TOKENS:
			raise WorkLimitError(f"Document exceeds the estimated {MAX_DOCUMENT_TOKENS}-token limit.")
	return byte_count, tokens


def validate_corpus(texts):
	"""Validate the combined source-document budgets for one base.

	:param texts: The document texts, including existing documents when adding files.
	:type texts: Iterable[str]
	:raises ValueError: If a document contains invalid Unicode text.
	:raises WorkLimitError: If a document or the combined corpus exceeds a budget.
	"""
	total_bytes = total_tokens = 0
	for count, text in enumerate(texts, 1):
		if count > MAX_BASE_DOCUMENTS:
			raise WorkLimitError(f"A document base can contain at most {MAX_BASE_DOCUMENTS} documents.")
		size, tokens = validate_document_text(text)
		total_bytes += size
		total_tokens += tokens
		if total_bytes > MAX_BASE_BYTES:
			raise WorkLimitError(f"Document base text exceeds the {MAX_BASE_BYTES}-byte limit.")
		if total_tokens > MAX_BASE_TOKENS:
			raise WorkLimitError(f"Document base exceeds the estimated {MAX_BASE_TOKENS}-token limit.")


def validate_attribute_count(count: int):
	"""Check the maximum number of attributes allowed in one base.

	:param count: The proposed total number of attributes.
	:type count: int
	:raises WorkLimitError: If the proposed count exceeds the attribute budget.
	"""
	if count > MAX_ATTRIBUTES:
		raise WorkLimitError(f"A document base can contain at most {MAX_ATTRIBUTES} attributes.")
