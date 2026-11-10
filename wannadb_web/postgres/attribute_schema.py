"""Versioned attribute edits for web document bases."""
from contextlib import closing
from uuid import UUID, uuid4, uuid5

from bson import decode, encode
from psycopg2.extras import Json

from wannadb_web.limits import MAX_ATTRIBUTES, validate_attribute_count
from wannadb_web.postgres.queries import document_base_snapshot_query
from wannadb_web.postgres.util import connectPG, execute_query


# Persisted BSON field name for automatic, provisional mappings.
SUGGESTED_ATTRIBUTE_MAPPINGS = "SuggestedAttributeMappingsSignal"


class AttributeSchemaConflict(RuntimeError):
    """The editor's schema is stale."""


def parse_attribute_edit(version, operations):
    """Validate and normalize the submitted edit before it is queued."""
    if not isinstance(version, str) or len(version) != 36:
        raise ValueError("An attribute schema version is required. Reload the page.")
    version = str(UUID(version))
    if not isinstance(operations, list) or not 0 < len(operations) <= 2 * MAX_ATTRIBUTES:
        raise ValueError("Provide a bounded list of attribute operations.")

    edits = []
    touched_ids = set()
    for operation in operations:
        if not isinstance(operation, dict) or operation.get("op") not in ("add", "remove", "rename"):
            raise ValueError("Use add, remove, or rename for each attribute operation.")
        kind = operation["op"]
        edit = {"op": kind}
        if kind != "add":
            attr_id = operation.get("id")
            if not isinstance(attr_id, str) or len(attr_id) != 36:
                raise ValueError("A valid attribute ID is required.")
            attr_id = str(UUID(attr_id))
            if attr_id in touched_ids:
                raise ValueError("An attribute can be edited only once per request.")
            touched_ids.add(attr_id)
            edit["id"] = attr_id
        if kind != "remove":
            name = operation.get("name")
            if not isinstance(name, str) or not name.strip() or "\0" in name:
                raise ValueError("Attribute names must be nonempty.")
            try:
                name.encode("utf-8")
            except UnicodeError:
                raise ValueError("Attribute names must be valid UTF-8.") from None
            edit["name"] = name
        edits.append(edit)
    return version, edits


def attribute_ids_for_snapshot(base, version, stored_ids):
    """Keep IDs stable for legacy snapshots until their first schema edit."""
    namespace = UUID(version)
    return {
        attribute["name"]: stored_ids.get(attribute["name"]) or str(uuid5(namespace, attribute["name"]))
        for attribute in base["attributes"]
    }


def get_attribute_schema_version(base_name, organisation_id):
    # The route has already authorized access to the base. The worker checks again
    # while holding the base lock.
    result = execute_query(
        "SELECT attribute_schema_version::text FROM document_bases WHERE name = %s AND organisation_id = %s",
        (base_name, organisation_id),
    )
    if result is False:
        raise RuntimeError("Could not read the attribute schema.")
    return result[0][0] if result else None


def _apply_edits(base, ids, operations):
    edits = {op["id"]: op for op in operations if op["op"] != "add"}
    if edits.keys() - set(ids.values()):
        raise AttributeSchemaConflict()

    new_attributes, new_ids = [], {}
    renames, removed = {}, []
    for attribute in base["attributes"]:
        name = attribute["name"]
        attr_id = ids[name]
        edit = edits.get(attr_id)
        if edit and edit["op"] == "remove":
            removed.append(name)
            continue
        if edit and edit["name"] != name:
            new_name = edit["name"]
            renames[name] = new_name
            attribute = dict(attribute, name=new_name)
        new_attributes.append(attribute)
        new_ids[attribute["name"]] = attr_id

    for edit in operations:
        if edit["op"] == "add":
            name = edit["name"]
            new_attributes.append({"name": name, "signals": {}})
            new_ids[name] = str(uuid4())

    validate_attribute_count(len(new_attributes))
    if len(new_attributes) != len(new_ids):
        raise ValueError("Attribute names must be unique.")

    base["attributes"] = new_attributes
    if renames or removed:
        removed_names = set(removed)
        for document in base["documents"]:
            document["attribute_mappings"] = {
                renames.get(name, name): matches
                for name, matches in document["attribute_mappings"].items()
                if name not in removed_names
            }
            signals = document.get("signals", {})
            if SUGGESTED_ATTRIBUTE_MAPPINGS in signals:
                suggestions = [renames.get(name, name) for name in signals[SUGGESTED_ATTRIBUTE_MAPPINGS]
                               if name not in removed_names]
                if suggestions:
                    signals[SUGGESTED_ATTRIBUTE_MAPPINGS] = suggestions
                else:
                    del signals[SUGGESTED_ATTRIBUTE_MAPPINGS]

    return new_ids, renames, removed


def edit_attribute_schema(user_id, base_id, base_name, organisation_id, expected_version, operations):
    """Edit BSON, catalog metadata, and ratings in one base-scoped transaction."""
    with closing(connectPG()) as connection, connection, connection.cursor() as cursor:
        # Use the same base-first lock order as snapshot and document writes.
        cursor.execute(
            """SELECT b.attribute_schema_version::text, b.attribute_ids FROM document_bases b
               WHERE b.id = %s AND b.name = %s AND b.organisation_id = %s
               AND EXISTS (SELECT 1 FROM membership m WHERE m.userid = %s
                   AND m.organisationid = b.organisation_id AND m.authorisation IN (0, 1, 10))
               FOR UPDATE OF b""",
            (base_id, base_name, organisation_id, user_id),
        )
        schema = cursor.fetchone()
        if schema is None:
            raise PermissionError("Document base access denied.")
        version, stored_ids = schema
        if version != expected_version:
            raise AttributeSchemaConflict()

        cursor.execute(document_base_snapshot_query(lock=True), (base_name, base_id, organisation_id, user_id))
        snapshots = cursor.fetchall()
        if len(snapshots) != 1:
            raise RuntimeError("The document base has no unique saved snapshot.")
        snapshot_id, content = snapshots[0]
        base = decode(bytes(content))
        ids = attribute_ids_for_snapshot(base, version, stored_ids)
        new_ids, renames, removed = _apply_edits(base, ids, operations)

        cursor.execute("UPDATE documents SET content_byte = %s WHERE id = %s", (encode(base), snapshot_id))
        if cursor.rowcount != 1:
            raise RuntimeError("The document base snapshot could not be updated.")
        cursor.execute(
            """UPDATE document_bases SET attributes = %s::text[], attribute_ids = %s,
               attribute_schema_version = gen_random_uuid() WHERE id = %s""",
            (list(new_ids), Json(new_ids), base_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("The attribute schema could not be updated.")
        if removed:
            cursor.execute(
                """DELETE FROM document_feedback f USING documents d
                   WHERE f.documentid = d.id AND d.documentbaseid = %s AND d.organisationid = %s
                   AND f.attribute = ANY(%s)""",
                (base_id, organisation_id, removed),
            )
        if renames:
            cursor.execute(
                """UPDATE document_feedback f SET attribute = renamed.new_name
                   FROM documents d, unnest(%s::text[], %s::text[]) AS renamed(old_name, new_name)
                   WHERE f.documentid = d.id AND d.documentbaseid = %s AND d.organisationid = %s
                   AND f.attribute = renamed.old_name""",
                (list(renames), list(renames.values()), base_id, organisation_id),
            )
