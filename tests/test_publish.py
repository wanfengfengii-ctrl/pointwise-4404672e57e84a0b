import sqlite3
from tests.support import ArchiveCase, document
from xcollect.errors import NotFound
from xcollect.documents.identity import make_result_id, source_digest


class TestPublish(ArchiveCase):
    def test_transaction_failure_and_retry(self):
        old_id = self.collector.ingest_xbrl("old", document())
        old_export = self.collector.export_evidence(old_id)
        before = self.counts()
        connection = self.collector.repository.connection
        connection.execute("""CREATE TRIGGER stop_receipt BEFORE INSERT ON receipts
                              WHEN NEW.document_id='new'
                              BEGIN SELECT RAISE(ABORT, 'receipt write blocked'); END""")
        body = document('<r:N contextRef="c1" unitRef="u1">99</r:N>')
        candidate_id = make_result_id("new", source_digest(body))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "receipt write blocked"):
            self.collector.ingest_xbrl("new", body)
        connection.execute("DROP TRIGGER stop_receipt")
        self.reopen()
        self.assertEqual(self.counts(), before)
        self.assertIsNone(self.collector.receipt("new"))
        self.assertIsNone(self.collector.repository.sources.read("new"))
        with self.assertRaises(NotFound):
            self.collector.read_facts(candidate_id)
        self.assertEqual(self.collector.export_evidence(old_id), old_export)
        self.assertEqual(self.collector.ingest_xbrl("new", body), candidate_id)
        self.assertEqual(self.collector.ingest_xbrl("new", body), candidate_id)
        self.assertEqual(self.counts()["results"], 2)
        self.assertEqual(self.collector.receipt("new").fact_count, 1)
        self.assertEqual(self.collector.export_evidence(candidate_id)["facts"][0]["value"], "99")
