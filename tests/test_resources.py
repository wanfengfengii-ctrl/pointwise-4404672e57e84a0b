from tests.support import ArchiveCase, SAMPLE, CONTEXT, UNIT, HEAD, document
from xcollect.resources.periods import period_key
from xcollect.consumption.reconcile import reconcile_result


class TestResources(ArchiveCase):
    def test_missing_reference(self):
        for reference in ("contextRef", "unitRef"):
            body = document().replace((reference + '="' + ("c1" if reference == "contextRef" else "u1") + '"').encode(),
                                      (reference + '="absent"').encode())
            self.assert_rejected(reference, body)

    def test_cross_document(self):
        result_id = self.collector.ingest_xbrl("first", document())
        before = self.collector.export_evidence(result_id)
        for index, resources in enumerate(("", CONTEXT, UNIT)):
            self.assert_rejected("missing" + str(index), document(resources=resources))
        self.reopen()
        self.assert_rejected("fresh", document(resources=""))
        self.assertEqual(self.collector.export_evidence(result_id), before)

    def test_scoped_qname(self):
        units = (
            '<x:unit id="a"><x:measure xmlns:p="urn:A">p:USD</x:measure></x:unit>'
            '<x:unit id="b" xmlns:p="urn:B"><x:measure>p:USD</x:measure></x:unit>'
            '<x:unit id="alias"><x:measure xmlns:q="urn:A">q:USD</x:measure></x:unit>')
        facts = ''.join('<r:N contextRef="c1" unitRef="' + unit + '">1</r:N>' for unit in ("a", "b", "alias"))
        result_id = self.collector.ingest_xbrl("scopes", document(facts, CONTEXT + units))
        actual = self.collector.read_facts(result_id)
        self.assertEqual([f.unit.numerator for f in actual],
                         [("{urn:A}USD",), ("{urn:B}USD",), ("{urn:A}USD",)])
        alias_body = document('<q:Revenue xmlns:q="urn:report" contextRef="c1">yes</q:Revenue>')
        result_id = self.collector.ingest_xbrl("concept-alias", alias_body)
        self.assertEqual(self.collector.read_facts(result_id)[0].concept, "{urn:report}Revenue")

    def test_periods_units(self):
        result_id = self.collector.ingest_xbrl("resources", SAMPLE)
        catalog = reconcile_result(
            self.collector.repository.load_published(result_id)).catalog
        self.assertEqual(period_key(catalog.context("c_i").period), ("instant", "2025-12-31"))
        self.assertEqual(period_key(catalog.context("c_y").period), ("duration", "2025-01-01", "2025-12-31"))
        self.assertEqual(period_key(catalog.context("c_q").period), ("duration", "2025-10-01", "2025-12-31"))
        self.assertEqual(catalog.context("c_q").identifier, "OTHER")
        self.assertEqual(catalog.unit("usd").numerator, ("{urn:currency}USD",))
        self.assertEqual(catalog.unit("shares").numerator, ("{urn:measure}shares",))
        self.assertEqual(catalog.unit("price").numerator, ("{urn:currency}USD",))
        self.assertEqual(catalog.unit("price").denominator, ("{urn:measure}shares",))
        self.assertEqual(catalog.unit("inverse").numerator, ("{urn:measure}shares",))
        self.assertEqual(catalog.unit("inverse").denominator, ("{urn:currency}USD",))
        self.assertEqual(catalog.unit("repeated").numerator,
                         ("{urn:currency}USD", "{urn:measure}shares", "{urn:currency}USD"))

    def test_invalid_resources(self):
        bad_resources = [
            CONTEXT.replace("2025-12-31", "2025-02-29") + UNIT,
            CONTEXT.replace("<x:instant>2025-12-31</x:instant>",
                            "<x:startDate>2025-12-31</x:startDate><x:endDate>2025-01-01</x:endDate>") + UNIT,
            CONTEXT + CONTEXT + UNIT,
            CONTEXT + UNIT.replace('id="u1"', 'id="c1"'),
            CONTEXT + UNIT.replace("m:USD", "unbound:USD"),
            CONTEXT.replace("</x:entity>", "<x:segment/></x:entity>") + UNIT,
            CONTEXT.replace("</x:context>", "<x:scenario/></x:context>") + UNIT,
            CONTEXT.replace("<x:instant>2025-12-31</x:instant>", "<x:forever/>") + UNIT,
            CONTEXT + '<x:unit id="u1"><x:divide><x:unitNumerator><x:measure>m:USD</x:measure></x:unitNumerator><x:unitDenominator/></x:divide></x:unit>',
            CONTEXT + '<x:unit id="u1"><x:measure>m:USD</x:measure><x:divide/></x:unit>',
            CONTEXT + '<x:unit id="u1"/>',
        ]
        for index, resources in enumerate(bad_resources):
            self.assert_rejected("resource" + str(index), document(resources=resources))
