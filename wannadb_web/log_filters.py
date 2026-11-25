"""Redaction of legacy task-status access-log details."""
import logging
import re


class _RedactLegacyTaskStatus(logging.Filter):
	"""Remove sensitive legacy status URL suffixes before access-log formatting."""
	legacy_status = re.compile(r"(/core/status/)[^/\s?]+/")

	def filter(self, record):
		"""Rewrite legacy task-status log arguments before the record is emitted.

		:param record: The access-log record to redact before formatting.
		:type record: logging.LogRecord
		:returns: True when the operation or predicate succeeds; otherwise False.
		:rtype: bool
		"""
		message = record.getMessage()
		redacted = self.legacy_status.sub(r"\1[redacted]/", message)
		if redacted != message:
			record.msg = redacted
			record.args = ()
		return True
