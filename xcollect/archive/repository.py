from contextlib import contextmanager
import json
import sqlite3
from xcollect.archive.schema import initialize_schema
from xcollect.documents.storage import SourceStore
from xcollect.errors import NotFound
from xcollect.facts.numeric import decimal_to_string
from xcollect.resources.periods import period_key
from xcollect.typed.records import concept_row

TYPED_TABLES = ("typed_result", "typed_schemas", "typed_concepts")


class ArchiveRepository:
    def __init__(self, database):
        self.connection = sqlite3.connect(database, isolation_level=None, timeout=10)
        self.connection.row_factory = sqlite3.Row
        try:
            initialize_schema(self.connection)
        except BaseException:
            self.connection.close()
            raise
        self.sources = SourceStore(self.connection)

    def close(self):
        self.connection.close()

    @contextmanager
    def transaction(self, write=True):
        self.connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def lookup_receipt(self, document_id):
        row = self.connection.execute("SELECT * FROM receipts WHERE document_id=?", (document_id,)).fetchone()
        return dict(row) if row is not None else None

    def read_mode(self, document_id):
        row = self.connection.execute("SELECT mode FROM source_modes WHERE document_id=?",
                                      (document_id,)).fetchone()
        return None if row is None else row["mode"]

    def load_published(self, result_id):
        with self.transaction(write=False):
            row = self.connection.execute("SELECT * FROM results WHERE result_id=?", (result_id,)).fetchone()
            if row is None:
                raise NotFound(result_id)
            result = dict(row)
            document_id = result["document_id"]
            snapshot = {"result": result, "source": self.sources.read(document_id),
                        "receipt": self.lookup_receipt(document_id),
                        "mode": self.read_mode(document_id)}
            for table in ("contexts", "units", "facts", "single_sources"):
                order = "ordinal" if table in ("facts", "single_sources") else "id"
                snapshot[table] = [dict(r) for r in self.connection.execute(
                    "SELECT * FROM " + table + " WHERE result_id=? ORDER BY " + order, (result_id,))]
            if snapshot["mode"] == "typed":
                typed = self.connection.execute(
                    "SELECT * FROM typed_results WHERE result_id=?", (result_id,)).fetchone()
                snapshot["typed_result"] = None if typed is None else dict(typed)
                snapshot["typed_schemas"] = [dict(r) for r in self.connection.execute(
                    "SELECT * FROM typed_schemas WHERE result_id=? ORDER BY uri", (result_id,))]
                snapshot["typed_concepts"] = [dict(r) for r in self.connection.execute(
                    "SELECT * FROM typed_concepts WHERE result_id=? ORDER BY concept", (result_id,))]
            return snapshot

    def insert_mode(self, identity):
        self.connection.execute("INSERT INTO source_modes VALUES(?,?)",
                                (identity.document_id, identity.mode))

    def insert_result(self, identity, fact_count):
        self.connection.execute("INSERT INTO results VALUES(?,?,?,?)",
                                (identity.result_id, identity.document_id, identity.digest, fact_count))

    def insert_type_basis(self, result_id, basis):
        self.connection.execute("INSERT INTO typed_results VALUES(?,?)", (result_id, basis.root_uri))
        for item in basis.files:
            self.connection.execute("INSERT INTO typed_schemas VALUES(?,?,?,?)",
                                    (result_id, item.uri, _digest(item.body), item.body))
        for concept in basis.concepts:
            self.connection.execute("INSERT INTO typed_concepts VALUES(?,?,?,?,?,?,?,?)",
                                    (result_id,) + concept_row(concept))

    def insert_resources(self, result_id, catalog):
        for context in catalog.contexts.values():
            self.connection.execute("INSERT INTO contexts VALUES(?,?,?,?,?)",
                                    (result_id, context.id, context.identifier, context.scheme,
                                     json.dumps(period_key(context.period), separators=(",", ":"))))
        for unit in catalog.units.values():
            self.connection.execute("INSERT INTO units VALUES(?,?,?,?)",
                                    (result_id, unit.id, json.dumps(unit.numerator), json.dumps(unit.denominator)))

    def insert_facts(self, result_id, facts):
        for fact in facts:
            value = decimal_to_string(fact.value) if fact.kind == "numeric" and not fact.nil else fact.value
            decimals = None if fact.decimals is None else str(fact.decimals)
            self.connection.execute("INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?)",
                                    (result_id, fact.ordinal, fact.concept, fact.context_ref, fact.unit_ref,
                                     fact.kind, value, int(fact.nil), decimals))

    def insert_single_sources(self, result_id, facts):
        for fact in facts:
            self.connection.execute("INSERT INTO single_sources VALUES(?,?,?,?,?)",
                                    (result_id, fact.ordinal, json.dumps(fact.source.path),
                                     fact.source.concept, fact.source.raw_text))

    def insert_receipt(self, identity, fact_count):
        self.connection.execute("INSERT INTO receipts VALUES(?,?,?,?)",
                                (identity.document_id, identity.result_id, identity.digest, fact_count))


def _digest(body):
    from hashlib import sha256
    return sha256(body).hexdigest()
