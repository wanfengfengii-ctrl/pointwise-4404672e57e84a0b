import json
import sqlite3
from decimal import Decimal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.support import ROOT, document
from tests.support import ArchiveCase
from typed_scenarios import BODY, CORE, CORE_URI, REPORT, ROOT_URI, package
from xcollect.archive.schema import V1_TABLES
from xcollect.documents.identity import make_result_id, source_digest
from xcollect.documents.intake import Collector
from xcollect.errors import BusinessValidationError, DocumentConflictError, IntegrityError

TYPED_TABLES = ("typed_concepts", "typed_schemas", "typed_results", "source_modes")


class TestTypedContract(ArchiveCase):
    def test_generated_identity_is_stable_and_isolated(self):
        first = self.collector.ingest_typed("typed", BODY, package())
        self.assertTrue(first.startswith("xt1-"))
        self.assertNotEqual(first, make_result_id("typed", source_digest(BODY)))
        self.assertEqual(self.collector.ingest_typed("typed", BODY, package()), first)
        reversed_pack = dict(reversed(list(package().items())))
        self.assertEqual(self.collector.ingest_typed("typed", BODY, reversed_pack), first)

    def test_typed_and_v1_never_attempt_replay_across_modes(self):
        typed = self.collector.ingest_typed("typed", BODY, package())
        with self.assertRaises(DocumentConflictError):
            self.collector.ingest_xbrl("typed", BODY)
        ordinary = self.collector.ingest_xbrl("ordinary", BODY)
        with self.assertRaises(DocumentConflictError):
            self.collector.ingest_typed("ordinary", BODY, package())
        self.assertEqual(self.collector.receipt("typed").result_id, typed)
        self.assertEqual(self.collector.receipt("ordinary").result_id, ordinary)

    def test_typed_read_filter_and_deterministic_export(self):
        result_id = self.collector.ingest_typed("typed", BODY, package())
        revenue = "{urn:report}Revenue"
        self.assertEqual([f.ordinal for f in self.collector.read_facts(result_id, revenue)], [1])
        self.assertEqual(self.collector.read_facts(result_id, "{urn:report}Absent"), ())
        exported = self.collector.export_evidence(result_id)
        self.assertEqual(json.loads(json.dumps(exported, ensure_ascii=False)), exported)
        self.assertEqual([record["value"] for record in exported["facts"]],
                         ["12.3", "A B", "", "-0.00", None, None])
        self.assertIsInstance(self.collector.read_facts(result_id)[0].value, Decimal)
        self.assertEqual(exported["facts"][0]["source"]["raw_text"], "12.3")
        self.assertEqual(exported["facts"][1]["source"]["raw_text"], " \t A \n B  ")

    def test_typed_tampering_is_detected(self):
        result_id = self.collector.ingest_typed("typed", BODY, package())
        before = self.collector.export_evidence(result_id)
        damages = [
            ("missing-schema", "DELETE FROM typed_schemas WHERE result_id=? AND uri=?",
             (result_id, CORE_URI)),
            ("swapped-body", "UPDATE typed_schemas SET body=? WHERE uri=? AND result_id=?",
             (b"junk", CORE_URI, result_id)),
            ("limit", "UPDATE typed_concepts SET max_inclusive='99' WHERE result_id=? AND concept=?",
             (result_id, "{urn:report}Revenue")),
            ("type", "UPDATE typed_concepts SET type_name='{urn:report}Limited2' "
                     "WHERE result_id=? AND concept=?", (result_id, "{urn:report}Revenue")),
            ("fact", "UPDATE facts SET value='12.4' WHERE result_id=? AND ordinal=?",
             (result_id, 1)),
            ("source", "UPDATE single_sources SET raw_text='12.40' WHERE result_id=? AND ordinal=?",
             (result_id, 1)),
        ]
        for label, sql, parameters in damages:
            with self.subTest(label=label):
                destination = Collector(str(Path(self.directory.name) / (label + ".sqlite")))
                self.addCleanup(destination.close)
                self.collector.repository.connection.backup(destination.repository.connection)
                destination.repository.connection.execute(sql, parameters)
                with self.assertRaises(IntegrityError):
                    destination.read_facts(result_id)
                with self.assertRaises(IntegrityError):
                    destination.export_evidence(result_id)
        self.assertEqual(self.collector.export_evidence(result_id), before)

    def test_extra_schema_row_is_not_part_of_the_reachable_set(self):
        result_id = self.collector.ingest_typed("typed", BODY, package())
        destination = Collector(str(Path(self.directory.name) / "extra.sqlite"))
        self.addCleanup(destination.close)
        self.collector.repository.connection.backup(destination.repository.connection)
        destination.repository.connection.execute(
            "INSERT INTO typed_schemas VALUES(?,?,?,?)",
            (result_id, "https://tax.example/unrelated.xsd", source_digest(b"x"), b"x"))
        with self.assertRaises(IntegrityError):
            destination.export_evidence(result_id)

    def test_import_closure_rejections(self):
        cases = {
            "missing-file": (BODY, {ROOT_URI: REPORT}),
            "empty-file": (BODY, {ROOT_URI: REPORT, CORE_URI: b""}),
            "not-bytes": (BODY, {ROOT_URI: REPORT, CORE_URI: "text"}),
            "mismatched-namespace": (BODY, {
                ROOT_URI: REPORT.replace(b'namespace="urn:types"', b'namespace="urn:other"'),
                CORE_URI: CORE}),
            "relative-location": (BODY, {
                ROOT_URI: REPORT.replace(CORE_URI.encode(), b"core.xsd"), CORE_URI: CORE}),
            "duplicate-type": (BODY, {
                ROOT_URI: REPORT,
                CORE_URI: CORE.replace(b"</xs:schema>",
                                       b'<xs:simpleType name="Amount"><xs:restriction base="xs:decimal"/></xs:simpleType></xs:schema>')}),
            "unused-but-invalid": (BODY, {ROOT_URI: REPORT + b"<not-a-schema/>", CORE_URI: CORE}),
            "facet-attribute": (BODY, {
                ROOT_URI: REPORT, CORE_URI: CORE.replace(b'value="20"', b'value="20" bad="1"')}),
        }
        good = self.collector.ingest_typed("good", BODY, package())
        before = self.collector.export_evidence(good)
        for label, (body, pack) in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(BusinessValidationError):
                    self.collector.ingest_typed(label, body, pack)
                self.assertIsNone(self.collector.receipt(label))
        self.assertEqual(self.collector.export_evidence(good), before)

    def test_concurrent_typed_retry(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(2)

        def submit():
            with Collector(self.database) as collector:
                barrier.wait(timeout=10)
                return collector.ingest_typed("shared-typed", BODY, package())

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
            result_ids = [future.result(timeout=20) for future in futures]
        self.assertEqual(result_ids[0], result_ids[1])
        with Collector(self.database) as reopened:
            exported = reopened.export_evidence(result_ids[0])
            self.assertEqual([f["value"] for f in exported["facts"]],
                             ["12.3", "A B", "", "-0.00", None, None])
            connection = reopened.repository.connection
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM typed_schemas WHERE result_id=?", (result_ids[0],)
            ).fetchone()[0], 2)

    def test_identity_precedes_type_evaluation(self):
        """A parseable package that already binds a different basis conflicts, not rejects."""
        result_id = self.collector.ingest_typed("typed", BODY, package())
        before = self.collector.export_evidence(result_id)
        # Structurally parseable, but the symbol space is invalid (duplicate type name).
        duplicate_type = CORE.replace(
            b"</xs:schema>",
            b'<xs:simpleType name="Amount"><xs:restriction base="xs:decimal"/>'
            b"</xs:simpleType></xs:schema>")
        with self.assertRaises(DocumentConflictError):
            self.collector.ingest_typed("typed", BODY, {ROOT_URI: REPORT, CORE_URI: duplicate_type})
        # A new identifier does evaluate the types and rejects them.
        with self.assertRaises(BusinessValidationError):
            self.collector.ingest_typed("fresh", BODY, {ROOT_URI: REPORT, CORE_URI: duplicate_type})
        self.assertIsNone(self.collector.receipt("fresh"))
        # An unresolvable closure stays a business validation error even for an existing id.
        with self.assertRaises(BusinessValidationError):
            self.collector.ingest_typed("typed", BODY, {ROOT_URI: REPORT})
        self.assertEqual(self.collector.export_evidence(result_id), before)

    def test_unrelated_mapping_entries_are_ignored(self):
        pack = package()
        pack["https://tax.example/unused.xsd"] = b"not even XML"
        result_id = self.collector.ingest_typed("typed", BODY, pack)
        self.assertEqual(self.collector.ingest_typed("typed", BODY, pack), result_id)
        exported = self.collector.export_evidence(result_id)
        self.assertEqual([row["uri"] for row in exported["type_basis"]["schemas"]],
                         sorted(package()))
        changed_unrelated = dict(pack, **{"https://tax.example/other.xsd": b"different"})
        self.assertEqual(self.collector.ingest_typed("typed", BODY, changed_unrelated), result_id)

    def test_typed_cli_round_trip(self):
        directory = Path(self.directory.name)
        schemas = []
        for index, (uri, body) in enumerate(sorted(package().items())):
            path = directory / (str(index) + ".xsd")
            path.write_bytes(body)
            schemas += ["--schema", uri + "=" + str(path)]
        instance = directory / "instance.xml"
        instance.write_bytes(BODY)
        database = str(directory / "cli-typed.sqlite")
        base = [sys.executable, "-B", "-m", "xcollect.documents.intake"]
        ingested = subprocess.run(base + ["ingest-typed", "--db", database, "--document-id", "cli",
                                          "--file", str(instance)] + schemas,
                                  cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(ingested.returncode, 0, ingested.stderr)
        result_id = ingested.stdout.strip()
        self.assertTrue(result_id.startswith("xt1-"))
        exported = subprocess.run(base + ["export", "--db", database, "--result-id", result_id],
                                  cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        record = json.loads(exported.stdout)
        self.assertEqual(record["type_basis"]["root_uri"], ROOT_URI)
        self.assertEqual([f["value"] for f in record["facts"]],
                         ["12.3", "A B", "", "-0.00", None, None])


class TestSchemaMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="typed-migrate-")
        self.addCleanup(self.tmp.cleanup)
        self.database = str(Path(self.tmp.name) / "legacy.sqlite")

    def _v1_archive(self):
        connection = sqlite3.connect(self.database)
        for statement in V1_TABLES:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")
        connection.commit()
        connection.close()
        body = document()
        with Collector(self.database) as collector:
            result_id = collector.ingest_xbrl("legacy", body)
            expected = collector.export_evidence(result_id)
        raw = sqlite3.connect(self.database)
        dump = {table: raw.execute("SELECT * FROM " + table).fetchall()
                for table in ("sources", "results", "contexts", "units", "facts",
                              "single_sources", "receipts")}
        for table in TYPED_TABLES:
            raw.execute("DROP TABLE " + table)
        raw.execute("PRAGMA user_version=1")
        raw.commit()
        raw.close()
        return body, result_id, expected, dump

    def test_v1_archive_upgrades_and_keeps_old_results(self):
        body, result_id, expected, dump = self._v1_archive()
        with Collector(self.database) as migrated:
            self.assertEqual(migrated.export_evidence(result_id), expected)
            self.assertEqual(migrated.receipt("legacy").result_id, result_id)
            self.assertIsNone(migrated.repository.read_mode("legacy"))
            self.assertEqual(migrated.ingest_xbrl("legacy", body), result_id)
        raw = sqlite3.connect(self.database)
        try:
            for table, rows in dump.items():
                self.assertEqual(raw.execute("SELECT * FROM " + table).fetchall(), rows)
        finally:
            raw.close()
        with Collector(self.database) as extended:
            typed = extended.ingest_typed("typed", BODY, package())
            self.assertEqual(extended.read_facts(typed)[0].value, Decimal("12.3"))
            self.assertEqual(extended.export_evidence(result_id), expected)

    def test_incompatible_v1_tables_still_fail(self):
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE sources(document_id TEXT PRIMARY KEY)")
        connection.execute("PRAGMA user_version=1")
        connection.commit()
        connection.close()
        with self.assertRaises(IntegrityError):
            Collector(self.database)


if __name__ == "__main__":
    unittest.main()
