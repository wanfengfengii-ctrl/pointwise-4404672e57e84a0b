from pathlib import Path
import tempfile
import unittest
from xcollect.documents.intake import Collector

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "samples/ordinary.xml").read_bytes()
HEAD = '<x:xbrl xmlns:x="http://www.xbrl.org/2003/instance" xmlns:r="urn:report" xmlns:m="urn:money" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
CONTEXT = '<x:context id="c1"><x:entity><x:identifier scheme="urn:lei">ACME</x:identifier></x:entity><x:period><x:instant>2025-12-31</x:instant></x:period></x:context>'
UNIT = '<x:unit id="u1"><x:measure>m:USD</x:measure></x:unit>'


def document(facts='<r:Revenue contextRef="c1" unitRef="u1" decimals="2">12.30</r:Revenue>',
             resources=None, head=HEAD):
    if resources is None:
        resources = CONTEXT + UNIT
    return (head + resources + facts + '</x:xbrl>').encode("utf-8")


def matrix_document():
    year = CONTEXT.replace('id="c1"', 'id="year"').replace(
        '<x:instant>2025-12-31</x:instant>',
        '<x:startDate>2025-01-01</x:startDate><x:endDate>2025-12-31</x:endDate>')
    quarter = year.replace('id="year"', 'id="quarter"').replace("2025-01-01", "2025-10-01")
    facts = ''.join('<r:' + concept + ' contextRef="' + context + '">' + value + '</r:' + concept + '>'
                    for concept, context, value in [
                        ("Revenue", "c1", "instant"), ("Revenue", "year", "annual"),
                        ("Revenue", "quarter", "quarter"), ("Title", "year", "title")])
    return document(facts, CONTEXT + year + quarter)


class ArchiveCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="xcollect-test-")
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "archive.sqlite")
        self.collector = Collector(self.database)
        self.addCleanup(lambda: self.collector.close())

    def reopen(self):
        self.collector.close()
        self.collector = Collector(self.database)
        return self.collector

    def counts(self):
        connection = self.collector.repository.connection
        return {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0]
                for name in ("sources", "results", "contexts", "units", "facts", "single_sources", "receipts")}

    def assert_rejected(self, document_id, body):
        from xcollect.errors import BusinessValidationError
        before = self.counts()
        with self.assertRaises(BusinessValidationError):
            self.collector.ingest_xbrl(document_id, body)
        self.assertIsNone(self.collector.receipt(document_id))
        self.assertEqual(before, self.counts())
