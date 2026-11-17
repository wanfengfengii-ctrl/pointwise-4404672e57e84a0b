import sqlite3
from xcollect.errors import IntegrityError

SCHEMA_VERSION = 2

V1_TABLES = (
    """CREATE TABLE sources(
        document_id TEXT PRIMARY KEY, digest TEXT NOT NULL, body BLOB NOT NULL)""",
    """CREATE TABLE results(
        result_id TEXT PRIMARY KEY, document_id TEXT NOT NULL UNIQUE REFERENCES sources(document_id),
        digest TEXT NOT NULL, fact_count INTEGER NOT NULL CHECK(fact_count>=0))""",
    """CREATE TABLE contexts(
        result_id TEXT NOT NULL REFERENCES results(result_id), id TEXT NOT NULL,
        identifier TEXT NOT NULL, scheme TEXT NOT NULL, period TEXT NOT NULL,
        PRIMARY KEY(result_id,id))""",
    """CREATE TABLE units(
        result_id TEXT NOT NULL REFERENCES results(result_id), id TEXT NOT NULL,
        numerator TEXT NOT NULL, denominator TEXT NOT NULL, PRIMARY KEY(result_id,id))""",
    """CREATE TABLE facts(
        result_id TEXT NOT NULL REFERENCES results(result_id), ordinal INTEGER NOT NULL CHECK(ordinal>0),
        concept TEXT NOT NULL, context_ref TEXT NOT NULL, unit_ref TEXT,
        kind TEXT NOT NULL CHECK(kind IN ('text','numeric')), value TEXT,
        nil INTEGER NOT NULL CHECK(nil IN (0,1)), decimals TEXT,
        PRIMARY KEY(result_id,ordinal),
        FOREIGN KEY(result_id,context_ref) REFERENCES contexts(result_id,id),
        FOREIGN KEY(result_id,unit_ref) REFERENCES units(result_id,id))""",
    """CREATE TABLE single_sources(
        result_id TEXT NOT NULL, ordinal INTEGER NOT NULL, path TEXT NOT NULL,
        concept TEXT NOT NULL, raw_text TEXT NOT NULL,
        PRIMARY KEY(result_id,ordinal),
        FOREIGN KEY(result_id,ordinal) REFERENCES facts(result_id,ordinal))""",
    """CREATE TABLE receipts(
        document_id TEXT PRIMARY KEY REFERENCES sources(document_id),
        result_id TEXT NOT NULL UNIQUE REFERENCES results(result_id),
        digest TEXT NOT NULL, fact_count INTEGER NOT NULL CHECK(fact_count>=0))""",
)

TYPED_TABLES = (
    """CREATE TABLE source_modes(
        document_id TEXT PRIMARY KEY REFERENCES sources(document_id),
        mode TEXT NOT NULL CHECK(mode IN ('v1','typed')))""",
    """CREATE TABLE typed_results(
        result_id TEXT PRIMARY KEY REFERENCES results(result_id), root_uri TEXT NOT NULL)""",
    """CREATE TABLE typed_schemas(
        result_id TEXT NOT NULL REFERENCES results(result_id), uri TEXT NOT NULL,
        sha256 TEXT NOT NULL, body BLOB NOT NULL, PRIMARY KEY(result_id,uri))""",
    """CREATE TABLE typed_concepts(
        result_id TEXT NOT NULL REFERENCES results(result_id), concept TEXT NOT NULL,
        type_name TEXT NOT NULL, primitive TEXT NOT NULL,
        white_space TEXT NOT NULL, min_inclusive TEXT, max_inclusive TEXT, enumeration TEXT,
        PRIMARY KEY(result_id,concept))""",
)

TABLES = V1_TABLES + TYPED_TABLES


def _definitions(connection):
    return {r[0]: " ".join(r[1].split()) for r in connection.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _expected_definitions(statements):
    with sqlite3.connect(":memory:") as expected:
        for statement in statements:
            expected.execute(statement)
        return _definitions(expected)


def validate_schema(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise IntegrityError("incompatible archive schema version")
    if _definitions(connection) != _expected_definitions(TABLES):
        raise IntegrityError("incompatible archive table definitions")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise IntegrityError("foreign key enforcement is required")


def _migrate_v1(connection):
    if _definitions(connection) != _expected_definitions(V1_TABLES):
        raise IntegrityError("incompatible archive table definitions")
    for statement in TYPED_TABLES:
        connection.execute(statement)
    connection.execute("PRAGMA user_version=2")


def initialize_schema(connection):
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if existing is None and version == 0:
            for statement in TABLES:
                connection.execute(statement)
            connection.execute("PRAGMA user_version=2")
        elif version == 1:
            _migrate_v1(connection)
        validate_schema(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
