from tests.support import ArchiveCase, document


class TestFixedResults(ArchiveCase):
    def test_new_document_revision(self):
        first = document()
        second = document('<r:Title contextRef="c1"> revised </r:Title>'
                          '<r:Revenue contextRef="c1" unitRef="u1">99.10</r:Revenue>')
        result_a = self.collector.ingest_xbrl("v1", first)
        result_b = self.collector.ingest_xbrl("v2", second)
        result_c = self.collector.ingest_xbrl("another-id", first)
        self.assertEqual(len({result_a, result_b, result_c}), 3)
        original = {r: self.collector.export_evidence(r) for r in (result_a, result_b, result_c)}
        self.reopen()
        for result_id in (result_b, result_a, result_c, result_a):
            self.assertEqual(self.collector.export_evidence(result_id), original[result_id])
        self.assertEqual([str(f.value) for f in self.collector.read_facts(result_a)], ["12.30"])
        self.assertEqual([str(f.value) for f in self.collector.read_facts(result_b)], [" revised ", "99.10"])
        self.assertEqual(original[result_a]["facts"][0]["source"]["path"], [1, 3])
        self.assertEqual(original[result_b]["facts"][1]["source"]["path"], [1, 4])
        self.assertNotEqual(original[result_a]["digest"], original[result_b]["digest"])
        self.assertEqual(self.collector.repository.sources.read("v1").body, first)
        self.assertEqual(self.collector.repository.sources.read("v2").body, second)
        self.assertEqual(self.collector.receipt("v2").result_id, result_b)
