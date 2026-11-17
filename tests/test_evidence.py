import json
import sqlite3
from pathlib import Path
from tests.support import ArchiveCase, SAMPLE, ROOT, document, matrix_document
from xcollect.documents.intake import Collector
from xcollect.errors import IntegrityError, NotFound


class TestEvidence(ArchiveCase):
    def copy_archive(self, name):
        destination = Collector(str(Path(self.directory.name) / (name + ".sqlite")))
        self.collector.repository.connection.backup(destination.repository.connection)
        return destination

    def test_reopen_filter_and_export(self):
        expected = json.loads((ROOT / "samples/expected.json").read_text())
        result_id = self.collector.ingest_xbrl("annual", SAMPLE)
        before = self.collector.export_evidence(result_id)
        self.reopen()
        self.assertEqual(self.collector.export_evidence(result_id), before)
        self.assertEqual(before["facts"], expected["facts"])
        facts = self.collector.read_facts(result_id, "{urn:report}Revenue",
                                         ("duration", "2025-01-01", "2025-12-31"))
        self.assertEqual([str(f.value) for f in facts], ["12.30"])

    def test_exact_filter(self):
        result_id = self.collector.ingest_xbrl("matrix", matrix_document())
        revenue = "{urn:report}Revenue"
        annual = ("duration", "2025-01-01", "2025-12-31")
        cases = [
            ({}, [1, 2, 3, 4]), ({"concept": revenue}, [1, 2, 3]),
            ({"period": annual}, [2, 4]), ({"concept": revenue, "period": annual}, [2]),
            ({"concept": revenue, "period": ("instant", "2025-12-31")}, [1]),
            ({"concept": revenue, "period": ("duration", "2025-10-01", "2025-12-31")}, [3]),
        ]
        self.reopen()
        for selection, expected in cases:
            self.assertEqual([f.ordinal for f in self.collector.read_facts(result_id, **selection)], expected)

    def test_unknown_inputs(self):
        result_id = self.collector.ingest_xbrl("known", document())
        before = self.counts()
        self.assertEqual(self.collector.read_facts(result_id, "{urn:report}Absent"), ())
        with self.assertRaises(NotFound):
            self.collector.read_facts("absent")
        with self.assertRaises(NotFound):
            self.collector.export_evidence("absent")
        for options in ({"concept": "Revenue"}, {"concept": 1}, {"period": ["instant", "2025-12-31"]},
                        {"period": ("instant", "2025-02-29")}, {"period": ("duration", "2025-12-31", "2025-01-01")},
                        {"period": ("instant", "2025-12-31", None)}):
            with self.assertRaises(ValueError):
                self.collector.read_facts("absent", **options)
        self.assertEqual(self.counts(), before)

    def test_evidence_integrity(self):
        a = self.collector.ingest_xbrl("a", document())
        b = self.collector.ingest_xbrl("b", document('<r:N contextRef="c1">different</r:N>'))
        exports = {r: self.collector.export_evidence(r) for r in (a, b)}
        self.reopen()
        for result_id in (a, b, a, b):
            self.assertEqual(self.collector.export_evidence(result_id), exports[result_id])
        self.assertEqual(exports[a]["facts"][0]["source"]["raw_text"], "12.30")
        self.assertEqual(exports[b]["facts"][0]["source"]["raw_text"], "different")
        for label, sql, parameters in [
            ("missing", "DELETE FROM single_sources WHERE result_id=?", (a,)),
            ("body", "UPDATE sources SET body=? WHERE document_id='a'", (b"tampered",)),
            ("text", "UPDATE single_sources SET raw_text='wrong' WHERE result_id=?", (a,)),
        ]:
            with self.copy_archive(label) as damaged:
                damaged.repository.connection.execute(sql, parameters)
                with self.assertRaises(IntegrityError):
                    damaged.read_facts(a)
                with self.assertRaises(IntegrityError):
                    damaged.export_evidence(a)
                self.assertEqual(damaged.export_evidence(b), exports[b])
        self.assertEqual(self.collector.export_evidence(a), exports[a])

    def test_count_reconcile(self):
        result_id = self.collector.ingest_xbrl("count", document())
        changes = [
            ("receipt", "UPDATE receipts SET fact_count=2"),
            ("result", "UPDATE results SET fact_count=2"),
            ("association", "UPDATE facts SET context_ref='missing'"),
            ("value", "UPDATE facts SET value='12.3'"),
        ]
        for label, sql in changes:
            with self.copy_archive(label) as damaged:
                if label == "association":
                    damaged.repository.connection.execute("PRAGMA foreign_keys=OFF")
                damaged.repository.connection.execute(sql)
                with self.assertRaises(IntegrityError):
                    damaged.read_facts(result_id)
                with self.assertRaises(IntegrityError):
                    damaged.export_evidence(result_id)

    def test_reinitialize(self):
        a = self.collector.ingest_xbrl("sample", SAMPLE)
        b = self.collector.ingest_xbrl("user", document('<r:User contextRef="c1">user text</r:User>'))
        before = self.counts(), self.collector.export_evidence(a), self.collector.export_evidence(b)
        for _ in range(2):
            self.reopen()
            self.assertEqual((self.counts(), self.collector.export_evidence(a), self.collector.export_evidence(b)), before)
            self.assertEqual(self.collector.repository.sources.read("sample").body, SAMPLE)

    def test_incompatible_schema_is_preserved(self):
        path = str(Path(self.directory.name) / "foreign.sqlite")
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE user_data(value TEXT)")
            connection.execute("INSERT INTO user_data VALUES('keep')")
        with self.assertRaises(IntegrityError):
            Collector(path)
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute("SELECT value FROM user_data").fetchall(), [("keep",)])

    def test_initialization_does_not_repair(self):
        result_id = self.collector.ingest_xbrl("damaged", document())
        self.collector.repository.connection.execute("DELETE FROM single_sources")
        self.reopen()
        with self.assertRaises(IntegrityError):
            self.collector.export_evidence(result_id)
        self.assertEqual(self.counts()["single_sources"], 0)
