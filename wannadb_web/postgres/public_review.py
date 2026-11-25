"""Value and source identities used by public votes and owner review."""

from hashlib import sha256
import json

from bson import decode


class PublicFeedbackConflict(ValueError):
    """The displayed source, attribute or mapping is no longer current."""


class PublicSuggestionConflict(PublicFeedbackConflict):
    """The selected suggestion or its source changed during owner review."""


def source_revision(text):
    """Hash the exact UTF-8 source text used by public feedback.

    :param text: The exact Unicode source text.
    :type text: str
    :returns: The source revision text or identifier.
    :rtype: str
    """
    return sha256(text.encode("utf-8")).hexdigest()


def _digest(value):
    """Hash a stable JSON representation for a source/mapping review identity.

    :param value: The value to validate, store or convert as described above.
    :type value: object
    :returns: The digest text or identifier.
    :rtype: str
    """
    return sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def mapping_spans(document, attribute):
    """Read sorted canonical code-point spans, distinguishing missing mapping from No Match.

    :param document: The selected domain document or serialized source record.
    :type document: Document | dict[str, object]
    :param attribute: The selected attribute name or domain attribute, as required here.
    :type attribute: str | Attribute
    :returns: The mapping spans result.
    :rtype: list[list[int]] | None
    :raises RuntimeError: If the operation cannot satisfy its state or persistence
        preconditions.
    """
    if attribute not in document["attribute_mappings"]:
        return None
    spans = []
    for index in document["attribute_mappings"][attribute]:
        if type(index) is not int or not 0 <= index < len(document["nuggets"]):
            raise RuntimeError("The saved mapping contains an invalid candidate reference.")
        nugget = document["nuggets"][index]
        start, end = nugget["start_char"], nugget["end_char"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(document["text"]):
            raise RuntimeError("The saved mapping contains an invalid candidate range.")
        spans.append([start, end])
    return sorted(spans)


def mapping_revisions(document, attribute_ids):
    """Hash the visible value and provenance while preserving stable rename identity.

    :param document: The selected domain document or serialized source record.
    :type document: Document | dict[str, object]
    :param attribute_ids: Displayed attribute names mapped to stable UUIDs.
    :type attribute_ids: dict[str, str]
    :returns: The mapping revisions mapping.
    :rtype: dict[str, str]
    """
    source = source_revision(document["text"])
    provisional = document.get("signals", {}).get("SuggestedAttributeMappingsSignal", [])
    return {
        name: _digest([identifier, source, mapping_spans(document, name), name in provisional])
        for name, identifier in attribute_ids.items()
    }


def suggestion_version(ids, revisions):
    """Hash the displayed correction-group members and their revision identities.

    :param ids: The ordered correction row IDs displayed in the group.
    :type ids: list[int]
    :param revisions: The correction revisions paired with the displayed IDs.
    :type revisions: list[str]
    :returns: The suggestion version text or identifier.
    :rtype: str
    """
    return _digest(list(zip(ids, revisions)))


def load_review_base(cursor, base_id, organisation_id, user_id):
    # These modules expose the existing legacy snapshot and attribute-ID contracts.
    # Import them at use time because their query module also uses this helper.
    """Read one authorized base snapshot and its stable attribute identities.

    :param cursor: The transaction/query cursor owned by the caller.
    :type cursor: psycopg2.extensions.cursor | sqlite3.Cursor
    :param base_id: The selected document-base database ID.
    :type base_id: int
    :param organisation_id: The organization database ID used to scope access.
    :type organisation_id: int
    :param user_id: The authenticated account ID selecting the authorized scope.
    :type user_id: int
    :returns: The review base mapping.
    :rtype: dict[str, object]
    :raises PublicFeedbackConflict: The displayed source, stable attribute or canonical mapping
        changed.
    """
    from wannadb_web.postgres.attribute_schema import attribute_ids_for_snapshot
    from wannadb_web.postgres.queries import document_base_snapshot_query

    cursor.execute("""SELECT b.name, b.attribute_schema_version::text, b.attribute_ids
        FROM public.document_bases b WHERE b.id = %s AND b.organisation_id = %s
        AND EXISTS (SELECT 1 FROM public.membership m WHERE m.userid = %s
            AND m.organisationid = b.organisation_id AND m.authorisation IN (0, 1, 10))
        FOR SHARE OF b""", (base_id, organisation_id, user_id))
    schema = cursor.fetchone()
    if schema is None:
        raise PublicFeedbackConflict("The document base changed. Refresh before retrying.")
    name, version, stored_ids = schema
    cursor.execute(document_base_snapshot_query(), (name, base_id, organisation_id, user_id))
    snapshots = cursor.fetchall()
    if len(snapshots) != 1:
        raise PublicFeedbackConflict("The saved document base is unavailable. Refresh before retrying.")
    snapshot_id, snapshot = snapshots[0]
    base = decode(bytes(snapshot))
    return {
        "id": base_id, "organisation_id": organisation_id, "name": name,
        "snapshot_id": snapshot_id, "snapshot": bytes(snapshot), "base": base,
        "attribute_ids": attribute_ids_for_snapshot(base, version, stored_ids),
    }


def load_review_document(cursor, document_id, user_id, *, base=None):
    """Read source text and canonical review identities for an authorized document.

    :param cursor: The transaction/query cursor owned by the caller.
    :type cursor: psycopg2.extensions.cursor | sqlite3.Cursor
    :param document_id: The source-document database ID.
    :type document_id: int
    :param user_id: The authenticated account ID selecting the authorized scope.
    :type user_id: int
    :param base: The authorized domain base or decoded snapshot record.
    :type base: DocumentBase | dict[str, object]
    :returns: The review document mapping.
    :rtype: dict[str, object]
    :raises PublicFeedbackConflict: The displayed source, stable attribute or canonical mapping
        changed.
    """
    if base is None:
        cursor.execute("""SELECT documentbaseid, organisationid FROM public.documents
            WHERE id = %s AND content IS NOT NULL""", (document_id,))
        scope = cursor.fetchone()
        if scope is None:
            raise PublicFeedbackConflict("The document changed. Refresh before retrying.")
        base = load_review_base(cursor, *scope, user_id)
    cursor.execute("""SELECT name, content FROM public.documents
        WHERE id = %s AND documentbaseid = %s AND organisationid = %s AND content IS NOT NULL""",
        (document_id, base["id"], base["organisation_id"]))
    row = cursor.fetchone()
    if row is None:
        raise PublicFeedbackConflict("The document changed. Refresh before retrying.")
    name, text = row
    document = next((item for item in base["base"]["documents"]
                     if item["name"] == name and item["text"] == text), None)
    if document is None:
        raise PublicFeedbackConflict("The saved document changed. Refresh before retrying.")
    return {
        "document": document, "base": base, "source_revision": source_revision(text),
        "mapping_revisions": mapping_revisions(document, base["attribute_ids"]),
    }


def validate_displayed_document(context, content, attribute_ids, mappings):
    """Reject vote counts when displayed text, attribute IDs or mapping spans changed.

    :param context: The validated source/base review context.
    :type context: dict[str, object]
    :param content: The complete source text or snapshot payload for this operation.
    :type content: str | bytes
    :param attribute_ids: Displayed attribute names mapped to stable UUIDs.
    :type attribute_ids: dict[str, str]
    :param mappings: The exact displayed mapping spans or missing/No Match sentinels.
    :type mappings: dict[str, object]
    :raises PublicFeedbackConflict: The displayed source, stable attribute or canonical mapping
        changed.
    """
    document = context["document"]
    ids = context["base"]["attribute_ids"]
    expected = {name: mapping_spans(document, name) for name in ids}
    if content != document["text"] or attribute_ids != ids or not isinstance(mappings, dict) or set(mappings) != set(ids):
        raise PublicFeedbackConflict("The displayed document changed. Refresh before retrying.")
    for spans in mappings.values():
        if spans is not None and (not isinstance(spans, list) or any(
                not isinstance(span, list) or len(span) != 2 or any(type(value) is not int for value in span)
                or not 0 <= span[0] < span[1] <= len(document["text"]) for span in spans)):
            raise PublicFeedbackConflict("The displayed mapping is invalid. Refresh before retrying.")
    normalized = {name: None if spans is None else sorted(spans) for name, spans in mappings.items()}
    if normalized != expected:
        raise PublicFeedbackConflict("The displayed mapping changed. Refresh before retrying.")
