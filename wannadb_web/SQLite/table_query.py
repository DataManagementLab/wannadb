import json
import re
import sqlite3
import time
from contextlib import closing

MAX_QUERY_BYTES = 8_192
MAX_RESULT_ROWS = 1_000
MAX_RESULT_BYTES = 2 * 1024 * 1024
QUERY_SECONDS = 2
MAX_QUERY_STEPS = 500_000
_SQLITE_TOKEN = re.compile(
    r"""--[^\n]* | /\*.*?(?:\*/|\Z) | '(?:[^']|'')*' | "(?:[^"]|"")*"
        | `(?:[^`]|``)*` | \[[^\]]*\] | [A-Za-z_\x80-\U0010ffff][A-Za-z0-9_$\x80-\U0010ffff]*
        | \s+ | .""",
    re.VERBOSE | re.DOTALL,
)
_FUNCTIONS = frozenset("""
    abs avg coalesce count cume_dist date datetime dense_rank first_value floor glob
    group_concat hex ifnull iif instr julianday lag last_value lead length like lower
    ltrim max min nullif nth_value ntile percent_rank rank replace round row_number
    rtrim strftime substr substring sum time total trim typeof unicode unixepoch upper
""".split())


class TableQueryError(ValueError):
    pass


def validate_table_query(query):
    if not isinstance(query, str) or not query.strip() or "\0" in query:
        raise TableQueryError("Enter a SQL query.")
    try:
        size = len(query.encode("utf-8"))
    except UnicodeEncodeError:
        raise TableQueryError("Enter a query with valid Unicode text.") from None
    if size > MAX_QUERY_BYTES:
        raise TableQueryError("The query exceeds the 8 KiB limit.")
    return query.strip()


def _with_document_source(query):
    """Add the default source to a simple SELECT while leaving explicit sources intact."""
    tokens = []
    depth = last_end = 0
    for token in _SQLITE_TOKEN.finditer(query):
        value = token.group()
        if value.isspace() or value.startswith(("--", "/*")):
            continue
        last_end = token.end()
        if value == ")":
            depth -= 1
            if depth < 0:
                return query
        if depth == 0:
            tokens.append((value.upper(), token.start()))
        if value == "(":
            depth += 1

    if depth or not tokens or tokens[0][0] != "SELECT":
        return query
    words = [word for word, _ in tokens]
    insertion = last_end
    for index, (word, start) in enumerate(tokens[1:], 1):
        if word == ";":
            insertion = min(insertion, start)
            break
        if word in ("UNION", "INTERSECT", "EXCEPT"):
            return query
        # IS [NOT] DISTINCT FROM compares two expressions.
        if word == "FROM" and words[index - 1] != "DISTINCT":
            return query
        if word in ("WHERE", "HAVING", "LIMIT"):
            insertion = min(insertion, start)
        elif word in ("GROUP", "ORDER") and words[index + 1:index + 2] == ["BY"]:
            insertion = min(insertion, start)
        elif word == "WINDOW" and words[index + 2:index + 4] == ["AS", "("]:
            insertion = min(insertion, start)

    return f"{query[:insertion]} FROM documents {query[insertion:]}"


def _authorize(action, first, second, database, _source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and first == "documents" and database in ("main", None):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and second in _FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _column_names(attributes):
    names = ["Document"]
    original_names = {attribute.name.casefold() for attribute in attributes}
    used = {"document"}
    for attribute in attributes:
        name = attribute.name
        if name.casefold() in used:
            blocked = original_names | used
            suffix = 2
            name = f"{attribute.name} ({suffix})"
            while name.casefold() in blocked:
                suffix += 1
                name = f"{attribute.name} ({suffix})"
        names.append(name)
        used.add(name.casefold())
    return names


def _text(value):
    if value is None or isinstance(value, str):
        return value
    return value.hex() if isinstance(value, bytes) else str(value)


def _read_results(cursor):
    columns = [column[0] for column in cursor.description]
    rows = []
    size = len(json.dumps(columns))
    for row in cursor:
        if len(rows) >= MAX_RESULT_ROWS:
            break
        cells = [_text(value) for value in row]
        size += len(json.dumps(cells)) + 1
        if size > MAX_RESULT_BYTES:
            break
        rows.append(cells)
    else:
        return {"columns": columns, "rows": rows, "truncated": False}
    return {"columns": columns, "rows": rows, "truncated": True}


def query_document_table(document_base, query):
    from wannadb_parsql.cache_db import SQLiteCacheDB

    query = _with_document_source(validate_table_query(query))

    columns = _column_names(document_base.attributes)
    schema = ", ".join('"' + column.replace('"', '""') + '" TEXT' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    with closing(SQLiteCacheDB(db_file=":memory:").conn) as conn:
        conn.execute("PRAGMA temp_store = FILE")
        conn.execute(f"CREATE TABLE documents ({schema})")
        conn.executemany(f"INSERT INTO documents VALUES ({placeholders})", (
            [document.name, *(
                ", ".join(nugget.text for nugget in document.attribute_mappings.get(attribute.name, ())) or None
                for attribute in document_base.attributes
            )] for document in document_base.documents
        ))
        conn.execute("PRAGMA query_only = ON")
        conn.set_authorizer(_authorize)
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_RESULT_BYTES)
        deadline = time.monotonic() + QUERY_SECONDS
        steps = 0

        def interrupt_expensive_query():
            nonlocal steps
            steps += 1_000
            return steps >= MAX_QUERY_STEPS or time.monotonic() >= deadline

        conn.set_progress_handler(interrupt_expensive_query, 1_000)
        try:
            cursor = conn.execute(query)
            if cursor.description is None:
                raise TableQueryError("Enter a read-only query that returns rows.")
            return _read_results(cursor)
        except sqlite3.ProgrammingError:
            raise TableQueryError("Enter one SQL statement without parameters.") from None
        except sqlite3.Error as error:
            code = getattr(error, "sqlite_errorcode", None)
            if code == sqlite3.SQLITE_INTERRUPT:
                raise TableQueryError("The query took too long. Try a simpler query.") from None
            if code in (sqlite3.SQLITE_AUTH, sqlite3.SQLITE_READONLY):
                raise TableQueryError("Queries may only read the documents table and use supported SQL functions.") from None
            if code == sqlite3.SQLITE_TOOBIG:
                raise TableQueryError("A value in the query result is too large.") from None
            if code == sqlite3.SQLITE_ERROR:
                raise TableQueryError(str(error)) from None
            raise TableQueryError("The SQL query could not be run.") from None
