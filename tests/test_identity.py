from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from tests.support import ArchiveCase, document
from xcollect.documents.intake import Collector
from xcollect.errors import DocumentConflictError


class TestDocumentIdentity(ArchiveCase):
    def test_same_bytes_retry(self):
        body = document()
        self.assertIsNone(self.collector.receipt("report"))
        self.assertTrue(all(v == 0 for v in self.counts().values()))
        result_id = self.collector.ingest_xbrl("report", body)
        before = self.counts(), self.collector.receipt("report"), self.collector.export_evidence(result_id)
        for attempt in range(2):
            collector = self.collector if attempt == 0 else self.reopen()
            self.assertEqual(collector.ingest_xbrl("report", body), result_id)
            self.assertEqual(collector.repository.sources.read("report").body, body)
            self.assertEqual((self.counts(), collector.receipt("report"), collector.export_evidence(result_id)), before)

    def test_conflicting_bytes(self):
        body = document()
        result_id = self.collector.ingest_xbrl("report", body)
        before = self.counts(), self.collector.receipt("report"), self.collector.export_evidence(result_id)
        for changed in (body.replace(b"12.30", b"99.10"), body.replace(b">12.30<", b"> 12.30 <"),
                        body.replace(b"12.30", b"12.3&#48;")):
            with self.assertRaises(DocumentConflictError):
                self.collector.ingest_xbrl("report", changed)
            self.assertEqual(self.collector.repository.sources.read("report").body, body)
            self.assertEqual((self.counts(), self.collector.receipt("report"), self.collector.export_evidence(result_id)), before)

    def test_concurrent_retry(self):
        barrier = Barrier(2)
        body = document()

        def submit():
            with Collector(self.database) as collector:
                barrier.wait(timeout=10)
                return collector.ingest_xbrl("shared", body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit) for _ in range(2)]
            result_ids = [future.result(timeout=20) for future in futures]
        self.assertEqual(result_ids[0], result_ids[1])
        self.assertEqual(self.counts(), {"sources": 1, "results": 1, "contexts": 1,
                                      "units": 1, "facts": 1, "single_sources": 1, "receipts": 1})
        self.assertEqual(self.collector.receipt("shared").fact_count, 1)
        self.assertEqual(str(self.collector.read_facts(result_ids[0])[0].value), "12.30")
