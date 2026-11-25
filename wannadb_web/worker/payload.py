"""Compact web publications. Text appears only on its owning document."""
import json

from wannadb_web.worker.progress import attribute_progress

DOCUMENT_PAGE_SIZE = 8
TABLE_PAGE_SIZE = 50
_VISIBLE_SIGNALS = {"ExtractorNameSignal", "CachedDistanceSignal"}


def compact_base(base, document_ids=None):
	"""Encode each document's source once and reference candidates by their identity.

	:param base: The authorized domain base or decoded snapshot record.
	:type base: DocumentBase | dict[str, object]
	:param document_ids: The selected source IDs or publication name-to-ID map.
	:type document_ids: list[int] | dict[str, int] | None
	:returns: The compact base mapping.
	:rtype: dict[str, object]
	"""
	documents = []
	names = [attribute.name for attribute in base.attributes]
	progress_documents = []
	for document in base.documents:
		indices = {id(nugget): index for index, nugget in enumerate(document.nuggets)}
		mappings = {name: [indices[id(nugget)] for nugget in matches]
			for name, matches in document.attribute_mappings.items()}
		progress_documents.append({"attribute_mappings": mappings, "signals": document.signals})
		documents.append({
			"name": document.name,
			"id": document_ids.get(document.name) if document_ids is not None else None,
			"text": document.text,
			"attribute_mappings": mappings,
			"nuggets": [
				{"start_char": int(nugget.start_char), "end_char": int(nugget.end_char),
					"signals": [{"name": name, "signal": {"identifier": name, "signal": str(signal)}}
						for name, signal in nugget.signals.items() if name in _VISIBLE_SIGNALS]}
				for nugget in document.nuggets
			],
		})
	return {
		"format": "compact-v1",
		"ids_resolved": document_ids is not None,
		"attributes": names,
		"attribute_summary": attribute_progress(progress_documents, names),
		"document_count": len(documents),
		"nugget_count": sum(len(document["nuggets"]) for document in documents),
		"documents": documents,
	}


def encode_base(base, document_ids=None):
	"""Serialize a compact base publication to UTF-8 JSON bytes.

	:param base: The authorized domain base or decoded snapshot record.
	:type base: DocumentBase | dict[str, object]
	:param document_ids: The selected source IDs or publication name-to-ID map.
	:type document_ids: list[int] | dict[str, int] | None
	:returns: The encode base result.
	:rtype: bytes
	"""
	return json.dumps(compact_base(base, document_ids), ensure_ascii=False, separators=(",", ":")).encode()


def project_base(base, feedback, view, *, offset=0, document_id=None, document_name=None):
	"""Select a catalog, document or bounded manual-review page from the publication.

	:param base: The authorized domain base or decoded snapshot record.
	:type base: DocumentBase | dict[str, object]
	:param feedback: The feedback payload or adapter used by this step.
	:type feedback: dict[str, object] | object
	:param view: The requested catalog, document, review or full publication view.
	:type view: str
	:param offset: The zero-based retained-result or suggestion offset.
	:type offset: int
	:param document_id: The source-document database ID.
	:type document_id: int | None
	:param document_name: The exact source-document display name.
	:type document_name: str | None
	:returns: The projected base publication and matching feedback-request view.
	:rtype: tuple[dict[str, object], dict[str, object]]
	"""
	documents = base["documents"]
	if view == "catalog":
		documents = [{"name": document["name"], "id": document["id"]} for document in documents]
	elif view == "document":
		documents = [document for document in documents if
			(document["id"] == document_id if document_id is not None else document["name"] == document_name)]
	elif view == "review":
		manual = feedback.get("documents-without-nuggets", [])
		page = manual[offset:offset + DOCUMENT_PAGE_SIZE]
		ranked_names = {item["document"]["name"] for item in feedback.get("nuggets", [])}
		names = ranked_names | set(page)
		documents = [document for document in documents if document["name"] in names]
		feedback = dict(feedback, **{"documents-without-nuggets": page,
			"manual_page": {"offset": offset, "size": DOCUMENT_PAGE_SIZE, "total": len(manual)}})
	return {key: value for key, value in dict(base, documents=documents).items() if key != "ids_resolved"}, feedback


def legacy_payload(base, feedback):
	"""Support existing clients and already queued tasks during a rolling update.

	:param base: The authorized domain base or decoded snapshot record.
	:type base: DocumentBase | dict[str, object]
	:param feedback: The feedback payload or adapter used by this step.
	:type feedback: dict[str, object] | object
	:returns: The expanded compatibility base and feedback payloads.
	:rtype: tuple[dict[str, object], dict[str, object]]
	"""
	documents = []
	by_name = {}
	for document in base["documents"]:
		ref = {"name": document["name"], "text": document["text"]}
		nuggets = [dict(nugget, id=index, document=ref,
			text=ref["text"][nugget["start_char"]:nugget["end_char"]])
			for index, nugget in enumerate(document["nuggets"])]
		mappings = {name: [nuggets[index] for index in indices]
			for name, indices in document["attribute_mappings"].items()}
		documents.append(dict(document, nuggets=nuggets, attribute_mappings=mappings, signals=[]))
		by_name[document["name"]] = nuggets
	if "nuggets" in feedback:
		candidates = []
		for nugget in feedback["nuggets"]:
			if "text" in nugget.get("document", {}):
				candidates.append(nugget)
				continue
			nuggets = by_name.get(nugget["document"]["name"], [])
			index = nugget.get("id")
			if type(index) is int and 0 <= index < len(nuggets):
				candidates.append(nuggets[index])
		feedback = dict(feedback, nuggets=candidates)
	return {**{key: base[key] for key in ("id", "name", "organization_id", "attributes")},
		"attribute_summary": base.get("attribute_summary"),
		"documents": documents, "nuggets": [nugget for document in documents for nugget in document["nuggets"]]}, feedback
