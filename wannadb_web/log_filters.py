import logging
import re


class _RedactLegacyTaskStatus(logging.Filter):
	legacy_status = re.compile(r"(/core/status/)[^/\s?]+/")

	def filter(self, record):
		message = record.getMessage()
		redacted = self.legacy_status.sub(r"\1[redacted]/", message)
		if redacted != message:
			record.msg = redacted
			record.args = ()
		return True
