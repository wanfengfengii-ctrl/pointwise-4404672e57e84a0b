from decimal import Decimal
import json
from tests.support import ArchiveCase, SAMPLE, ROOT, CONTEXT, UNIT, document
from xcollect.errors import BusinessValidationError
from xcollect.documents.dispatch import prepare_ordinary_document


class TestOrdinaryIngest(ArchiveCase):
    def test_numeric_and_text(self):
        expected = json.loads((ROOT / "samples/expected.json").read_text())
        result_id = self.collector.ingest_xbrl("annual", SAMPLE)
        facts = self.collector.read_facts(result_id)
        exported = self.collector.export_evidence(result_id)
        self.assertEqual(exported["facts"], expected["facts"])
        self.assertEqual(len(facts), 7)
        self.assertIsInstance(facts[1].value, Decimal)
        self.assertEqual(str(facts[1].value), "12.30")
        self.assertEqual(facts[0].value, " Annual & audited \n")
        self.assertEqual(facts[6].context.identifier, "OTHER")
        print("POINTWISE_SCENARIO " + json.dumps({
            "case_id": "V1", "input": {"document_id": "annual", "bytes": len(SAMPLE)},
            "expected": expected["values"], "actual": [r["value"] for r in exported["facts"]],
            "downstream_expected": expected["facts"][1]["source"],
            "downstream_actual": exported["facts"][1]["source"],
            "code_paths": ["xcollect/facts/numeric.py", "xcollect/archive/publish.py", "xcollect/consumption/export.py"],
            "oracle": "handwritten sample values and root child positions"
        }, sort_keys=True))

    def test_invalid_late_fact(self):
        old = self.collector.ingest_xbrl("old", document())
        evidence = self.collector.export_evidence(old)
        suffixes = [
            '<r:Bad contextRef="c1" unitRef="u1">1e3</r:Bad>',
            '<r:Bad contextRef="c1" xsi:nil="true">nonempty</r:Bad>',
            '<r:Bad contextRef="c1" unitRef="u1"/>',
        ]
        for index, suffix in enumerate(suffixes):
            self.assert_rejected("bad" + str(index), document(
                '<r:Good contextRef="c1">ok</r:Good>' + suffix))
        self.assertEqual(self.collector.export_evidence(old), evidence)
        self.collector.ingest_xbrl("bad0", document())

    def test_decimal_exact(self):
        values = ["12.30", "0.1", "9007199254740993.01", "0.123456789012345678901234567890", "-0.00", "+.50"]
        facts = ''.join('<r:N contextRef="c1" unitRef="u1" decimals="-2">' + v + '</r:N>' for v in values)
        result_id = self.collector.ingest_xbrl("exact", document(facts))
        actual = self.collector.read_facts(result_id)
        expected = ["12.30", "0.1", "9007199254740993.01", "0.123456789012345678901234567890", "-0.00", "0.50"]
        self.assertEqual([str(f.value) for f in actual], expected)
        self.assertEqual([f.decimals for f in actual], [-2] * 6)
        self.assertEqual([f["value"] for f in self.collector.export_evidence(result_id)["facts"]], expected)
        for index, value in enumerate(["1E2", "1,000", "NaN", "Infinity", "", "1 2", "\u00a01"]):
            self.assert_rejected("lex" + str(index), document(
                '<r:N contextRef="c1" unitRef="u1">' + value + '</r:N>'))
        for attribute in ['decimals="bad"', 'precision="2"', 'scale="2"', 'sign="-"', 'format="m:f"']:
            self.assert_rejected("attr" + attribute, document(
                '<r:N contextRef="c1" unitRef="u1" ' + attribute + '>12.30</r:N>'))

    def test_nil_empty_zero(self):
        body = document(
            '<r:N contextRef="c1" xsi:nil="true"> \t</r:N>'
            '<r:N contextRef="c1" unitRef="u1" xsi:nil="1"/>'
            '<r:N contextRef="c1"/>'
            '<r:N contextRef="c1" unitRef="u1" xsi:nil="false">0</r:N>'
            '<r:N contextRef="c1" xsi:nil="0">0</r:N>')
        facts = self.collector.read_facts(self.collector.ingest_xbrl("types", body))
        self.assertEqual([f.value for f in facts], [None, None, "", Decimal("0"), "0"])
        self.assertEqual([type(f.value) for f in facts], [type(None), type(None), str, Decimal, str])
        self.assertEqual([f.nil for f in facts], [True, True, False, False, False])
        self.assertEqual([f.unit_ref for f in facts], [None, "u1", None, "u1", None])
        for value in ["yes", "TRUE", "2", ""]:
            self.assert_rejected("nil" + value, document('<r:N contextRef="c1" xsi:nil="' + value + '"/>'))

    def test_source_leaf(self):
        body = document('<r:B contextRef="c1"> \nB&amp; \t</r:B><r:A contextRef="c1"/><r:B contextRef="c1">B</r:B>')
        prepared = prepare_ordinary_document(body)
        self.assertEqual([f.source.path for f in prepared.facts], [(1, 3), (1, 4), (1, 5)])
        self.assertEqual([f.source.raw_text for f in prepared.facts], [" \nB& \t", "", "B"])
        result_id = self.collector.ingest_xbrl("paths", body)
        self.assertEqual([f.ordinal for f in self.collector.read_facts(result_id)], [1, 2, 3])
        self.assertEqual([r["source"]["path"] for r in self.collector.export_evidence(result_id)["facts"]],
                         [[1, 3], [1, 4], [1, 5]])

    def test_reject_unsupported(self):
        bodies = [
            document('<r:Outer contextRef="c1"><r:Inner contextRef="c1">x</r:Inner></r:Outer>'),
            document('<r:Tuple><r:Inner contextRef="c1">x</r:Inner></r:Tuple>'),
            document('<ix:nonNumeric xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" contextRef="c1">x</ix:nonNumeric>'),
            b'<!DOCTYPE x [<!ENTITY e "hello">]>' + document(),
            b'<!DOCTYPE x SYSTEM "https://example.invalid/x">' + document(),
            document().decode().replace("<x:xbrl", '<!DOCTYPE x [<!ENTITY e "x">]><x:xbrl', 1).encode("utf-16"),
            b"<broken>",
            document('<r:T contextRef="c1"><r:b>bold</r:b></r:T>'),
        ]
        for index, body in enumerate(bodies):
            self.assert_rejected("unsupported" + str(index), body)

    def test_input_validation(self):
        for document_id, body in [("", document()), (" \n", document()), (1, document()), ("valid", b""), ("valid", "xml")]:
            with self.assertRaises(BusinessValidationError):
                self.collector.ingest_xbrl(document_id, body)
        self.assertTrue(all(v == 0 for v in self.counts().values()))

    def test_empty_document_and_schema_declaration(self):
        body = document("", resources="")
        result_id = self.collector.ingest_xbrl("empty", body)
        self.assertEqual(self.collector.read_facts(result_id), ())
        self.assertEqual(self.collector.export_evidence(result_id)["fact_count"], 0)
        declaration = '<l:schemaRef xmlns:l="http://www.xbrl.org/2003/linkbase" xmlns:z="http://www.w3.org/1999/xlink" z:type="simple" z:href="https://example.invalid/schema.xsd"/>'
        result_id = self.collector.ingest_xbrl("declared", document(resources=declaration +
                CONTEXT + UNIT))
        self.assertEqual(str(self.collector.read_facts(result_id)[0].value), "12.30")

    def test_cli_failure_exit_codes(self):
        import subprocess
        import sys
        from pathlib import Path
        base = [sys.executable, "-B", "-m", "xcollect.documents.intake"]
        missing = subprocess.run(base + ["ingest"], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(missing.returncode, 2)
        bad_file = Path(self.directory.name) / "bad.xml"
        bad_file.write_bytes(b"<broken>")
        bad_db = str(Path(self.directory.name) / "cli.sqlite")
        invalid = subprocess.run(base + ["ingest", "--db", bad_db, "--document-id", "bad",
                                        "--file", str(bad_file)], cwd=ROOT,
                                 capture_output=True, text=True, timeout=20)
        self.assertNotEqual(invalid.returncode, 0)
        from xcollect.documents.intake import Collector
        with Collector(bad_db) as collector:
            self.assertIsNone(collector.receipt("bad"))
            self.assertEqual(collector.repository.connection.execute("SELECT count(*) FROM sources").fetchone()[0], 0)
