"""Private entry point for applying the web database migrations."""
import os
import sys
from contextlib import closing
from hashlib import sha256
from pathlib import Path

from psycopg2 import Error

from wannadb_web.postgres.util import connectPG

MIGRATIONS = (
    "0001_baseline.sql",
    "0002_organization_ownership.sql",
    "0003_attribute_schema.sql",
    "0004_feedback_outcomes.sql",
    "0005_feedback_sessions.sql",
    "0006_public_feedback_votes.sql",
    "0007_public_feedback_no_match.sql",
    "0008_public_feedback_review.sql",
)
ADVISORY_LOCK = (0x57414E4E, 0x414442)

_INTEGER = ("int4", "int8")
_TEXT = ("text", "varchar")
_REQUIRED_COLUMNS = {
    "users": {"id": _INTEGER, "username": _TEXT, "password": ("bytea", *_TEXT)},
    "organisations": {"id": _INTEGER, "name": _TEXT},
    "membership": {"userid": _INTEGER, "organisationid": _INTEGER, "authorisation": _INTEGER},
    "document_bases": {
        "id": _INTEGER, "name": _TEXT, "attributes": (*_TEXT, "_text"), "organisation_id": _INTEGER,
        "last_modified": ("timestamp", "timestamptz"),
        "attribute_schema_version": ("uuid",), "attribute_ids": ("jsonb",),
    },
    "documents": {
        "id": _INTEGER, "name": _TEXT, "content": _TEXT, "content_byte": ("bytea",),
        "organisationid": _INTEGER, "userid": _INTEGER, "documentbaseid": _INTEGER,
    },
    "document_feedback": {
        "id": _INTEGER, "documentid": _INTEGER, "userid": _INTEGER, "positive": ("bool",),
        "attribute": _TEXT, "feedback_start": _INTEGER, "feedback_end": _INTEGER, "no_match": ("bool",), "reviewed": ("bool",),
    },
    "feedback_outcomes": {
        "user_id": _INTEGER, "command_id": _TEXT, "session_id": _TEXT, "base_id": _INTEGER,
        "expected_version": _INTEGER, "request_fingerprint": _TEXT, "snapshot_version": _TEXT,
        "committed_at": ("timestamptz",),
    },
    "feedback_sessions": {
        "user_id": _INTEGER, "session_id": _TEXT, "base_id": _INTEGER, "snapshot_id": _INTEGER,
        "attribute_schema_version": ("uuid",), "snapshot_hash": _TEXT, "version": _INTEGER,
        "phase": _TEXT, "attribute": _TEXT, "checkpoint": ("bytea",), "expires_at": ("timestamptz",),
    },
}

# Keys the application relies on to keep users, bases and membership unambiguous.
_REQUIRED_KEYS = {
    ("users", "p", ("id",)),
    ("users", "u", ("username",)),
    ("organisations", "p", ("id",)),
    ("organisations", "u", ("name",)),
    ("membership", "p", ("organisationid", "userid")),
    ("document_bases", "p", ("id",)),
    ("document_bases", "u", ("name", "organisation_id")),
    ("documents", "p", ("id",)),
    ("document_feedback", "p", ("id",)),
    ("document_feedback", "u", ("attribute", "documentid", "userid")),
    ("feedback_outcomes", "p", ("command_id", "user_id")),
    ("feedback_sessions", "p", ("session_id", "user_id")),
}


class MigrationError(RuntimeError):
    """A migration cannot safely proceed with the configured database."""


def _validate_schema(cursor):
    cursor.execute(
        """
        SELECT columns.table_name, columns.column_name, columns.udt_name,
               columns.is_nullable, columns.is_identity, columns.column_default
        FROM information_schema.columns AS columns
        JOIN information_schema.tables AS tables
          ON tables.table_schema = columns.table_schema AND tables.table_name = columns.table_name
        WHERE columns.table_schema = 'public' AND columns.table_name = ANY(%s)
          AND tables.table_type = 'BASE TABLE'
        """,
        (list(_REQUIRED_COLUMNS),),
    )
    actual = {(table, column): (kind, nullable, identity, default)
              for table, column, kind, nullable, identity, default in cursor.fetchall()}
    nullable_columns = {
        "documents": {"content", "content_byte", "documentbaseid", "userid"},
        "document_feedback": {"userid"},
    }
    for table, columns in _REQUIRED_COLUMNS.items():
        for column, expected_types in columns.items():
            kind, nullable, identity, default = actual.get((table, column), (None, None, None, None))
            if kind not in expected_types:
                raise MigrationError(f"Unsupported column in public.{table}.{column}.")
            if column == "id" and identity != "YES" and not (default or "").startswith("nextval("):
                raise MigrationError(f"Missing ID generation in public.{table}.")
            if column in nullable_columns.get(table, ()) and nullable != "YES":
                raise MigrationError(f"Column public.{table}.{column} must allow NULL.")

    cursor.execute(
        """
        SELECT relation.relname, constraint_info.contype,
               array_agg(attribute.attname::text ORDER BY attribute.attname::text)
        FROM pg_constraint AS constraint_info
        JOIN pg_class AS relation ON relation.oid = constraint_info.conrelid
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = relation.oid AND attribute.attnum = ANY(constraint_info.conkey)
        WHERE relation.relnamespace = 'public'::regnamespace
          AND relation.relname = ANY(%s)
          AND constraint_info.contype IN ('p', 'u')
          AND (
              NOT constraint_info.condeferrable OR (
                  relation.relname = 'document_feedback'
                  AND constraint_info.conname = 'document_feedback_one_vote'
                  AND NOT constraint_info.condeferred
              )
          )
        GROUP BY relation.relname, constraint_info.oid, constraint_info.contype
        """,
        (list(_REQUIRED_COLUMNS),),
    )
    keys = {(table, kind, tuple(columns)) for table, kind, columns in cursor.fetchall()}
    missing = _REQUIRED_KEYS - keys
    if missing:
        table, kind, columns = min(missing)
        key = "primary" if kind == "p" else "unique"
        raise MigrationError(f"Missing {key} key in public.{table} ({', '.join(columns)}).")

    cursor.execute(
        """
        SELECT 1 FROM pg_constraint
        WHERE contype = 'f' AND confupdtype = 'c' AND confdeltype = 'c'
          AND conrelid = 'public.documents'::regclass
          AND confrelid = 'public.document_bases'::regclass
          AND conkey = ARRAY[
              (SELECT attnum FROM pg_attribute WHERE attrelid = conrelid AND attname = 'documentbaseid')
          ]
          AND confkey = ARRAY[
              (SELECT attnum FROM pg_attribute WHERE attrelid = confrelid AND attname = 'id')
          ]
        """
    )
    if cursor.fetchone() is None:
        raise MigrationError("Missing cascading document base reference in public.documents.")


def migrate():
    """Apply pending migrations and their version records in one PostgreSQL transaction."""
    if not all(os.environ.get(name) for name in ("DATABASE_HOST", "DATABASE_NAME", "DATABASE_USER")):
        raise MigrationError("Set DATABASE_HOST, DATABASE_NAME and DATABASE_USER before running migrations.")

    directory = Path(__file__).with_name("migrations")
    migrations = [(version, (directory / filename).read_bytes()) for version, filename in enumerate(MIGRATIONS, 1)]
    expected = [(version, sha256(script).hexdigest()) for version, script in migrations]

    with closing(connectPG()) as connection, connection, connection.cursor() as cursor:
        cursor.execute("SET LOCAL search_path = pg_catalog")
        cursor.execute("SET LOCAL lock_timeout = '30s'")
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", ADVISORY_LOCK)
        cursor.execute("SELECT to_regnamespace('public')")
        if cursor.fetchone()[0] is None:
            cursor.execute("CREATE SCHEMA public")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS public.wannadb_schema_migrations (
                version integer PRIMARY KEY,
                checksum text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
        cursor.execute("SELECT version, checksum FROM public.wannadb_schema_migrations ORDER BY version")
        applied = cursor.fetchall()
        if applied != expected[:len(applied)]:
            raise MigrationError("The database migration history does not match this release.")

        pending = migrations[len(applied):]
        for version, script in pending:
            cursor.execute(script.decode("utf-8"))
            cursor.execute(
                "INSERT INTO public.wannadb_schema_migrations (version, checksum) VALUES (%s, %s)",
                expected[version - 1],
            )
        _validate_schema(cursor)

    return [version for version, _ in pending]


def main():
    try:
        applied = migrate()
    except MigrationError as error:
        print(f"Database migration failed. {error}", file=sys.stderr)
        return 1
    except (Error, OSError) as error:
        # PostgreSQL exception details can include connection settings and row values.
        code = getattr(error, "pgcode", None) or "unavailable"
        print(f"Database migration failed ({type(error).__name__}, SQLSTATE={code}).", file=sys.stderr)
        return 1

    if applied:
        print(f"Applied database migrations: {', '.join(f'{version:04d}' for version in applied)}.")
    else:
        print("Database schema is current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
