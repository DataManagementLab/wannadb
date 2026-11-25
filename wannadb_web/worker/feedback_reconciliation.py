"""Compare a reviewer's published choices with the latest document base."""
from hashlib import sha256

from wannadb.data.signals import SuggestedAttributeMappingsSignal


def _text_digest(text):
    """Hash source text for concurrent-feedback comparison without retaining a duplicate.

    :param text: The exact Unicode source text.
    :type text: str
    :returns: The text digest text or identifier.
    :rtype: str
    """
    return sha256(text.encode("utf-8")).hexdigest()


def _confirmed_mapping(document, attribute):
    """Return confirmed spans while distinguishing provisional and missing decisions.

    :param document: The selected domain document or serialized source record.
    :type document: Document | dict[str, object]
    :param attribute: The selected attribute name or domain attribute, as required here.
    :type attribute: str | Attribute
    :returns: The confirmed mapping result.
    :rtype: list[list[int]] | None
    """
    marker = SuggestedAttributeMappingsSignal
    if marker.identifier in document.signals and attribute in document[marker]:
        return None
    if attribute not in document.attribute_mappings:
        return None
    return sorted([[int(match.start_char), int(match.end_char)]
                   for match in document.attribute_mappings[attribute]])


def observe_documents(document_base, attribute):
    """Store only the text digest and confirmed span coordinates for each document.

    :param document_base: The worker-local domain base.
    :type document_base: DocumentBase
    :param attribute: The selected attribute name or domain attribute, as required here.
    :type attribute: str | Attribute
    :returns: The observe documents mapping.
    :rtype: dict[str, list[object]]
    """
    return {document.name: [_text_digest(document.text), _confirmed_mapping(document, attribute)]
            for document in document_base.documents}


def _nugget_span(nugget):
    """Normalize a serialized candidate's code-point coordinates.

    :param nugget: The exact selected candidate or custom candidate text.
    :type nugget: InformationNugget | str
    :returns: The nugspan result.
    :rtype: list[int]
    """
    return [int(nugget["start_char"]), int(nugget["end_char"])]


def _targets(payload):
    """Extract document references and proposed spans from the feedback command shape.

    :param payload: The exact serialized feedback action being processed.
    :type payload: dict[str, object]
    :returns: The targets result.
    :rtype: list[tuple[dict[str, object], list[list[int]]]]
    """
    message = payload["message"]
    if message == "multi-match":
        return [(nugget["document"], [_nugget_span(nugget)]) for nugget in payload["nuggets"]]
    if message == "custom-match":
        return [(payload["document"], [[int(payload["start"]), int(payload["end"])]])]
    if message == "is-match":
        return [(payload["nugget"]["document"], [_nugget_span(payload["nugget"])])]
    if message == "no-match-in-document":
        return [(payload.get("document") or payload["nugget"]["document"], [])]
    return []


def compare_feedback(payload, baseline, latest):
    """Return conflicting documents, the remaining proposal, and whether it can be replaced.

    :param payload: The exact serialized feedback action being processed.
    :type payload: dict[str, object]
    :param baseline: Source/decision observations saved in this reviewer's checkpoint.
    :type baseline: dict[str, object]
    :param latest: Current canonical source/decision observations.
    :type latest: dict[str, object]
    :returns: Conflicting document names, the remaining proposal and whether replacement is
        allowed.
    :rtype: tuple[list[str], dict[str, object] | None, bool]
    """
    message = payload["message"]
    if message == "start-ranking" and payload.get("reset"):
        conflicts = [
            name for name in sorted(baseline.keys() | latest.keys())
            if baseline.get(name) != latest.get(name)
            and any(observation is not None and observation[1] is not None
                    for observation in (baseline.get(name), latest.get(name)))
        ]
        return conflicts, payload, False

    conflicts, identical = [], set()
    replaceable = True
    for reference, proposed in _targets(payload):
        name = reference["name"]
        prior, saved = baseline.get(name), latest.get(name)
        submitted_text = reference.get("text")
        if (prior is None or saved is None or prior[0] != saved[0] or
                (submitted_text is not None and _text_digest(submitted_text) != saved[0])):
            conflicts.append(name)
            replaceable = False
        elif saved[1] == proposed:
            identical.add(name)
        elif saved[1] != prior[1]:
            conflicts.append(name)

    if conflicts:
        return conflicts, payload, replaceable
    if message == "multi-match" and identical:
        nuggets = [nugget for nugget in payload["nuggets"] if nugget["document"]["name"] not in identical]
        return [], dict(payload, nuggets=nuggets) if nuggets else None, True
    return [], None if identical else payload, True


def _preview(text, spans):
    """Render selected source spans for conflict review without changing their identity.

    :param text: The exact Unicode source text.
    :type text: str
    :param spans: The selected inclusive-start/exclusive-end code-point ranges.
    :type spans: list[list[int]]
    :returns: The preview result.
    :rtype: str | None
    """
    if not spans or text is None:
        return None
    remaining, parts = 160, []
    for start, end in spans:
        piece = text[start:min(end, start + remaining)]
        remaining -= len(piece) + 1
        parts.append(piece + ("…" if end > start + len(piece) else ""))
        if remaining <= 0:
            break
    return ", ".join(parts)


def proposed_previews(payload, document_base):
    """Build per-document previews of the proposed exact feedback selections.

    :param payload: The exact serialized feedback action being processed.
    :type payload: dict[str, object]
    :param document_base: The worker-local domain base.
    :type document_base: DocumentBase
    :returns: The proposed previews mapping.
    :rtype: dict[str, str | None]
    """
    documents = {document.name: document.text for document in document_base.documents}
    return {reference["name"]: _preview(reference.get("text", documents.get(reference["name"])), spans)
            for reference, spans in _targets(payload)}


def conflict_review(document_base, attribute, names, previews, *, can_replace, reset=False):
    """Build the user-visible keep/replace comparison for concurrently changed documents.

    :param document_base: The worker-local domain base.
    :type document_base: DocumentBase
    :param attribute: The selected attribute name or domain attribute, as required here.
    :type attribute: str | Attribute
    :param names: The selected attribute or document names.
    :type names: list[str]
    :param previews: Exact proposed occurrence previews keyed by document name.
    :type previews: dict[str, str | None]
    :param can_replace: Whether the conflicting proposal may replace the displayed canonical
        decision.
    :type can_replace: bool
    :param reset: Whether to clear previous ranking progress before starting the attribute.
    :type reset: bool
    :returns: The conflict review mapping.
    :rtype: dict[str, object]
    """
    documents = {document.name: document for document in document_base.documents}
    items = []
    for name in names:
        document = documents.get(name)
        saved = _preview(document.text, _confirmed_mapping(document, attribute)) if document is not None else None
        items.append({"document": name, "saved": saved, "proposed": previews.get(name)})
    if reset:
        message = "Saved decisions changed. Review the latest matches before starting repopulation again."
    elif can_replace:
        message = "Another reviewer saved a different decision. Choose which result to keep."
    else:
        message = "A document changed or was removed. Review the updated candidates before giving feedback again."
    return {"items": items, "canReplace": can_replace, "message": message}


def clear_replaced_decisions(document_base, attribute, payload):
    """Make only the explicitly replaced documents available to the matcher again.

    :param document_base: The worker-local domain base.
    :type document_base: DocumentBase
    :param attribute: The selected attribute name or domain attribute, as required here.
    :type attribute: str | Attribute
    :param payload: The exact serialized feedback action being processed.
    :type payload: dict[str, object]
    """
    targets = {reference["name"] for reference, _ in _targets(payload)}
    marker = SuggestedAttributeMappingsSignal
    for document in document_base.documents:
        if document.name not in targets:
            continue
        document.attribute_mappings.pop(attribute, None)
        if marker.identifier in document.signals:
            names = [name for name in document[marker] if name != attribute]
            if names:
                document[marker] = marker(names)
            else:
                document.signals.pop(marker.identifier)


def compact_proposal(payload):
    """Keep the original action without duplicating full texts in the checkpoint.

    :param payload: The exact serialized feedback action being processed.
    :type payload: dict[str, object]
    :returns: The compact proposal mapping.
    :rtype: dict[str, object]
    """
    def reference(document):
        """Keep only a document name in a saved conflict proposal.

        :param document: The selected domain document or serialized source record.
        :type document: Document | dict[str, object]
        :returns: The reference mapping.
        :rtype: dict[str, str]
        """
        return {"name": document["name"]}

    def nugget(value):
        """Keep source identity and exact coordinates without duplicating document text.

        :param value: The value to validate, store or convert as described above.
        :type value: object
        :returns: The nugget mapping.
        :rtype: dict[str, object]
        """
        start, end = _nugget_span(value)
        return {"document": reference(value["document"]), "start_char": start, "end_char": end}

    proposal = dict(payload)
    if payload.get("document") is not None:
        proposal["document"] = reference(payload["document"])
    if payload.get("nuggets") is not None:
        proposal["nuggets"] = [nugget(value) for value in payload["nuggets"]]
    for key in ("nugget", "not_a_match"):
        if payload.get(key) is not None:
            proposal[key] = nugget(payload[key])
    return proposal
