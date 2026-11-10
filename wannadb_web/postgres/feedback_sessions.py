"""Durable checkpoints and command commits for interactive feedback."""

from contextlib import closing
from hashlib import sha256
import re

from psycopg2 import sql

from wannadb_web.limits import QueueFullError
from wannadb_web.postgres.queries import document_base_snapshot_scope
from wannadb_web.postgres.util import connectPG, execute_query


_IDLE_SECONDS = 3600
_FINISHED_SECONDS = 300
_MAX_ACTIVE_SESSIONS_PER_USER = 8
_MAX_ACTIVE_SESSIONS = 64
_ADMISSION_LOCK = (0x57414E4E, 0x463332)
_WAITING_PHASES = ("selection", "ranking")


class FeedbackSessionConflict(RuntimeError):
    """A feedback step lost its current version or its source snapshot."""


class FeedbackSessionUnavailable(RuntimeError):
    """The saved feedback session could not be read."""


class FeedbackSessionLimit(QueueFullError):
    """Too many feedback checkpoints are already active."""


def load_session(user_id, session_id, *, include_checkpoint=False):
    """Read a current member's unexpired session. API callers only receive metadata."""
    payload = sql.SQL(", s.checkpoint, d.content_byte, b.attribute_schema_version::text AS live_schema") if include_checkpoint else sql.SQL("")
    statement = sql.SQL("""
        SELECT s.base_id, b.organisation_id, b.name, s.snapshot_id, s.snapshot_hash,
               s.attribute_schema_version::text, s.version, s.phase, s.attribute{payload}
        FROM public.feedback_sessions s
        JOIN public.document_bases b ON b.id = s.base_id
        JOIN public.documents d ON d.id = s.snapshot_id
        WHERE s.user_id = %s AND s.session_id = %s AND s.expires_at > clock_timestamp()
          AND EXISTS (
              SELECT 1 FROM public.membership m
              WHERE m.userid = s.user_id AND m.organisationid = b.organisation_id
                AND m.authorisation IN (0, 1, 10)
          )
    """).format(payload=payload)
    rows = execute_query(statement, (user_id, session_id))
    if rows is False:
        raise FeedbackSessionUnavailable("Could not read the saved feedback session.")
    if not rows:
        return None
    base_id, organisation_id, base_name, snapshot_id, snapshot_hash, schema, version, phase, attribute, *body = rows[0]
    session = {
        "user_id": user_id, "session_id": session_id, "base_id": base_id,
        "organisation_id": organisation_id, "base_name": base_name, "interactive": True,
        "snapshot_id": snapshot_id, "snapshot_hash": snapshot_hash,
        "attribute_schema_version": schema, "version": version, "phase": phase,
        "attribute": attribute, "closed": phase == "finished", "error": None,
    }
    if include_checkpoint:
        checkpoint, snapshot, live_schema = body
        snapshot = bytes(snapshot) if snapshot is not None else None
        if phase != "finished" and (snapshot is None or sha256(snapshot).hexdigest() != snapshot_hash or live_schema != schema):
            raise FeedbackSessionConflict("The document base changed. Open a fresh feedback session.")
        session.update(checkpoint=bytes(checkpoint) if checkpoint is not None else None, snapshot=snapshot)
    return session


def extend_session_step(user_id, session_id, expected_version, lease_seconds):
    """Keep a claimed checkpoint alive through the worker's bounded execution."""
    if type(lease_seconds) is not int or lease_seconds <= 0:
        raise ValueError("A positive feedback step lease is required.")
    with closing(connectPG()) as connection, connection, connection.cursor() as cursor:
        cursor.execute("""
            UPDATE public.feedback_sessions s
            SET expires_at = GREATEST(s.expires_at, clock_timestamp() + %s * interval '1 second')
            FROM public.document_bases b
            WHERE b.id = s.base_id AND b.attribute_schema_version = s.attribute_schema_version
              AND s.user_id = %s AND s.session_id = %s AND s.version = %s
              AND s.phase IN ('selection', 'ranking') AND s.expires_at > clock_timestamp()
              AND EXISTS (
                  SELECT 1 FROM public.membership m
                  WHERE m.userid = s.user_id AND m.organisationid = b.organisation_id
                    AND m.authorisation IN (0, 1, 10)
              )
        """, (lease_seconds, user_id, session_id, expected_version))
        return cursor.rowcount == 1


def _purge_expired(connection):
    # This short transaction only locks session rows, before any base lock is acquired.
    with connection, connection.cursor() as cursor:
        cursor.execute("""
            DELETE FROM public.feedback_sessions s USING (
                SELECT user_id, session_id FROM public.feedback_sessions
                WHERE expires_at <= clock_timestamp()
                ORDER BY expires_at LIMIT 32 FOR UPDATE SKIP LOCKED
            ) expired
            WHERE s.user_id = expired.user_id AND s.session_id = expired.session_id
        """)


def _check_capacity(cursor, user_id):
    cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", _ADMISSION_LOCK)
    cursor.execute("""
        SELECT count(*) AS total, count(*) FILTER (WHERE user_id = %s) AS personal
        FROM public.feedback_sessions
        WHERE phase <> 'finished' AND expires_at > clock_timestamp()
    """, (user_id,))
    total, personal = cursor.fetchone()
    if total >= _MAX_ACTIVE_SESSIONS or personal >= _MAX_ACTIVE_SESSIONS_PER_USER:
        raise FeedbackSessionLimit("Too many feedback sessions are open. Finish an existing session or try again later.")


def _lock_snapshot(cursor, user_id, base_id, snapshot_id, snapshot_hash, schema):
    # Match the account-first and base-first lock order used by the F38 commit.
    cursor.execute("SELECT id FROM public.users WHERE id = %s FOR KEY SHARE", (user_id,))
    if cursor.fetchone() is None:
        raise PermissionError("Feedback session access denied.")
    cursor.execute("""
        SELECT b.attribute_schema_version::text
        FROM public.document_bases b
        WHERE b.id = %s AND EXISTS (
            SELECT 1 FROM public.membership m
            WHERE m.userid = %s AND m.organisationid = b.organisation_id AND m.authorisation IN (0, 1, 10)
        ) FOR UPDATE OF b
    """, (base_id, user_id))
    base = cursor.fetchone()
    if base is None:
        raise PermissionError("Feedback session access denied.")
    if base[0] != schema:
        raise FeedbackSessionConflict("The attribute schema changed. Open a fresh feedback session.")
    cursor.execute(sql.SQL("""
        SELECT d.id, encode(sha256(d.content_byte), 'hex')
        FROM public.document_bases b JOIN public.documents d ON {scope}
        WHERE b.id = %s LIMIT 2 FOR UPDATE OF d
    """).format(scope=document_base_snapshot_scope()), (base_id,))
    if cursor.fetchall() != [(snapshot_id, snapshot_hash)]:
        raise FeedbackSessionConflict("The document base changed. Open a fresh feedback session.")


def save_session(user_id, session_id, base_id, snapshot_id, expected_snapshot,
                 attribute_schema_version, checkpoint, phase, attribute, *,
                 expected_version=0, expected_phase=None, expected_attribute=None,
                 command=None, new_snapshot=None):
    """Create a checkpoint or atomically advance it, its BSON snapshot and its F38 receipt."""
    expected_hash = sha256(expected_snapshot).hexdigest() if isinstance(expected_snapshot, bytes) else expected_snapshot
    if not isinstance(expected_hash, str) or re.fullmatch(r"[a-f0-9]{64}", expected_hash) is None:
        raise ValueError("A valid expected snapshot is required.")
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError("A valid expected session version is required.")
    if phase in _WAITING_PHASES:
        if not isinstance(attribute, str) or not attribute or not isinstance(checkpoint, bytes) or not checkpoint:
            raise ValueError("A waiting feedback session requires an attribute and a checkpoint.")
    elif phase != "finished" or attribute is not None or checkpoint is not None:
        raise ValueError("A finished session cannot retain its checkpoint or attribute.")

    if expected_version == 0:
        if command is not None or new_snapshot is not None:
            raise ValueError("An initial session does not apply a feedback command.")
    elif (not isinstance(command, dict) or not command.get("command_id") or
          not command.get("request_fingerprint") or command.get("session_id") != session_id or
          command.get("expected_version") != expected_version or
          expected_phase not in _WAITING_PHASES or not isinstance(expected_attribute, str) or
          not isinstance(new_snapshot, bytes) or not new_snapshot):
        raise ValueError("An advancing feedback session requires a scoped command and its saved snapshot.")

    version = expected_version + 1
    lifetime = _FINISHED_SECONDS if phase == "finished" else _IDLE_SECONDS
    new_hash = expected_hash if new_snapshot is None else sha256(new_snapshot).hexdigest()
    with closing(connectPG()) as connection:
        if expected_version == 0:
            _purge_expired(connection)
        with connection, connection.cursor() as cursor:
            if expected_version == 0:
                _check_capacity(cursor, user_id)
            _lock_snapshot(cursor, user_id, base_id, snapshot_id, expected_hash, attribute_schema_version)
            if expected_version == 0:
                cursor.execute("""
                    INSERT INTO public.feedback_sessions
                        (user_id, session_id, base_id, snapshot_id, snapshot_hash, attribute_schema_version,
                         version, phase, attribute, checkpoint, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp() + %s * interval '1 second')
                    ON CONFLICT (user_id, session_id) DO NOTHING
                """, (user_id, session_id, base_id, snapshot_id, expected_hash, attribute_schema_version,
                      version, phase, attribute, checkpoint, lifetime))
                if cursor.rowcount != 1:
                    raise FeedbackSessionConflict("This feedback session has already started.")
                return version

            cursor.execute("""
                UPDATE public.feedback_sessions
                SET snapshot_hash = %s, version = %s, phase = %s, attribute = %s, checkpoint = %s,
                    expires_at = clock_timestamp() + %s * interval '1 second'
                WHERE user_id = %s AND session_id = %s AND base_id = %s AND snapshot_id = %s
                  AND snapshot_hash = %s AND attribute_schema_version = %s AND version = %s
                  AND phase = %s AND attribute = %s AND expires_at > clock_timestamp()
            """, (new_hash, version, phase, attribute, checkpoint, lifetime, user_id, session_id,
                  base_id, snapshot_id, expected_hash, attribute_schema_version, expected_version,
                  expected_phase, expected_attribute))
            if cursor.rowcount != 1:
                raise FeedbackSessionConflict("This feedback session changed or expired. Reload its current state.")

            cursor.execute("UPDATE public.documents SET content_byte = %s WHERE id = %s", (new_snapshot, snapshot_id))
            if cursor.rowcount != 1:
                raise FeedbackSessionConflict("The saved document snapshot could not be updated.")
            cursor.execute("UPDATE public.document_bases SET last_modified = now() WHERE id = %s", (base_id,))
            if cursor.rowcount != 1:
                raise FeedbackSessionConflict("The document base could not be updated.")
            cursor.execute("""
                INSERT INTO public.feedback_outcomes
                    (user_id, command_id, session_id, base_id, expected_version, request_fingerprint, snapshot_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, command_id) DO NOTHING
            """, (user_id, command["command_id"], session_id, base_id, expected_version,
                  command["request_fingerprint"], new_hash))
            if cursor.rowcount != 1:
                raise FeedbackSessionConflict("This feedback command was already saved.")
    return version
