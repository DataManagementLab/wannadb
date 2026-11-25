"""Bounded propagation of explicit custom selections into additional candidates."""
import re

from wannadb.data.signals import ExtractorNameSignal, LabelSignal

MAX_PROPAGATION_HITS_PER_DOCUMENT = 4
MAX_PROPAGATION_HITS_PER_ATTRIBUTE = 128
MAX_PROPAGATION_HITS_PER_JOB = 32

_EXTRACTOR_NAME = "<WEB_CUSTOM_PROPAGATION>"
_LEGACY_EXTRACTOR_PREFIX = "<function WannaDB_WebAPI._matcher.<locals>.find_additional_nuggets at "


class WebMatchPropagation:
	"""Bound extra candidates before the shared matcher constructs and embeds them."""

	def __init__(self):
		"""Initialize WebMatchPropagation with its supplied dependencies and scope.
		"""
		self.remaining = MAX_PROPAGATION_HITS_PER_JOB
		self.limited = False
		self.documents = ()
		self.attribute = None

	def bind(self, documents, attribute):
		# A snapshot retry gets fresh documents but shares the original job budget.
		"""Select the current document set and attribute while retaining this job's hit budget.

		:param documents: The document set or names/text references processed by this helper.
		:type documents: Iterable[Document] | dict[str, str]
		:param attribute: The selected attribute name or domain attribute, as required here.
		:type attribute: str | Attribute
		"""
		self.documents = documents
		self.attribute = attribute
		self.limited = False

	def __str__(self):
		"""Return the stable display/serialization identifier for this component.

		:returns: The str text or identifier.
		:rtype: str
		"""
		return _EXTRACTOR_NAME

	def to_config(self):
		"""Serialize web match propagation into its web transport representation.

		:returns: The serialized representation of this adapter or command.
		:rtype: dict[str, object]
		"""
		return {"identifier": _EXTRACTOR_NAME}

	def _propagated_count(self, document):
		"""Count previously web-propagated candidates for this document/attribute.

		:param document: The selected domain document or serialized source record.
		:type document: Document | dict[str, object]
		:returns: The resulting count, version, identifier or status code for this operation.
		:rtype: int
		"""
		count = 0
		for nugget in document.nuggets:
			label = nugget.signals.get(LabelSignal.identifier)
			source = nugget.signals.get(ExtractorNameSignal.identifier)
			if label is None or label.value != self.attribute or source is None:
				continue
			if source.value == _EXTRACTOR_NAME or (
				isinstance(source.value, str) and source.value.startswith(_LEGACY_EXTRACTOR_PREFIX)
			):
				count += 1
		return count

	def __call__(self, nugget, remaining_documents):
		"""Find additional exact occurrences within document, attribute and job hit caps.

		:param nugget: The exact selected candidate or custom candidate text.
		:type nugget: InformationNugget | str
		:param remaining_documents: Documents still available for bounded propagation.
		:type remaining_documents: Iterable[Document]
		:returns: The call result.
		:rtype: list[tuple[Document, int, int]]
		"""
		if self.attribute is None or not nugget.text or not remaining_documents:
			return []

		counts = {document.name: self._propagated_count(document) for document in self.documents}
		attribute_remaining = MAX_PROPAGATION_HITS_PER_ATTRIBUTE - sum(counts.values())
		# Scan the original text so character offsets are valid even for Unicode case variants.
		pattern = re.compile(re.escape(nugget.text), re.IGNORECASE)
		hits = []
		for document in remaining_documents:
			document_remaining = MAX_PROPAGATION_HITS_PER_DOCUMENT - counts[document.name]
			existing_spans = {(item.start_char, item.end_char) for item in document.nuggets}
			for match in pattern.finditer(document.text):
				start, end = match.span()
				if (start, end) in existing_spans:
					continue
				if document_remaining <= 0:
					self.limited = True
					break
				if attribute_remaining <= 0 or self.remaining <= 0:
					self.limited = True
					return hits
				hits.append((document, start, end))
				document_remaining -= 1
				attribute_remaining -= 1
				self.remaining -= 1
		return hits
