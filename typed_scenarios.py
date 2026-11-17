"""Handwritten typed-input scenarios; no type resolver or target implementation."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

from tests.support import CONTEXT, UNIT, document
from xcollect.documents.intake import Collector
from xcollect.errors import BusinessValidationError, DocumentConflictError

ROOT_URI = "https://tax.example/report.xsd"
CORE_URI = "https://tax.example/core.xsd"
XS = "http://www.w3.org/2001/XMLSchema"
R = "{urn:report}"
T = "{urn:types}"
SCHEMA_REF = ('<l:schemaRef xmlns:l="http://www.xbrl.org/2003/linkbase" '
              'xmlns:z="http://www.w3.org/1999/xlink" z:type="simple" '
              'z:href="' + ROOT_URI + '"/>')
CORE = b"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:types">
 <xs:simpleType name="Amount"><xs:restriction base="xs:decimal">
  <xs:minInclusive value="0"/><xs:maxInclusive value="20"/>
 </xs:restriction></xs:simpleType>
 <xs:simpleType name="Collapsed"><xs:restriction base="xs:string">
  <xs:whiteSpace value="collapse"/>
 </xs:restriction></xs:simpleType>
</xs:schema>"""
REPORT = b"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:r="urn:report"
 xmlns:q="urn:wrong" xmlns:t="urn:types" targetNamespace="urn:report">
 <xs:import namespace="urn:types" schemaLocation="https://tax.example/core.xsd"/>
 <xs:element name="Revenue" type="r:Limited"/>
 <xs:element name="Title" type="r:TitleType"/>
 <xs:element name="Empty" type="xs:string"/>
 <xs:element name="Zero" type="t:Amount"/>
 <xs:element name="MissingNumber" type="t:Amount"/>
 <xs:element name="MissingText" type="xs:string"/>
 <xs:simpleType name="Limited"><xs:restriction xmlns:q="urn:types" base="q:Amount">
  <xs:enumeration value="12.30"/>
 </xs:restriction></xs:simpleType>
 <xs:simpleType name="TitleType"><xs:restriction base="t:Collapsed">
  <xs:enumeration value=" A   B "/>
 </xs:restriction></xs:simpleType>
</xs:schema>"""
FACTS = ('<r:Revenue contextRef="c1" unitRef="u1" decimals="2">12.3</r:Revenue>'
         '<r:Title contextRef="c1"> \t A \n B  </r:Title>'
         '<r:Empty contextRef="c1"/>'
         '<r:Zero contextRef="c1" unitRef="u1">-0.00</r:Zero>'
         '<r:MissingNumber contextRef="c1" unitRef="u1" xsi:nil="true"/>'
         '<r:MissingText contextRef="c1" xsi:nil="1"> </r:MissingText>')
BODY = document(FACTS, SCHEMA_REF + CONTEXT + UNIT)
EXPECTED_VALUES = ["12.3", "A B", "", "-0.00", None, None]


def package():
    return {ROOT_URI: REPORT, CORE_URI: CORE}


def values(collector, result):
    return [record["value"] for record in collector.export_evidence(result)["facts"]]


def check_basis(case, exported, pack):
    basis = exported["type_basis"]
    case.assertEqual(basis["root_uri"], ROOT_URI)
    case.assertEqual([s["uri"] for s in basis["schemas"]], sorted(pack))
    for item in basis["schemas"]:
        body = pack[item["uri"]]
        case.assertEqual(item["sha256"], hashlib.sha256(body).hexdigest())
        case.assertEqual(base64.b64decode(item["body_base64"], validate=True), body)
    rows = basis["concepts"]
    case.assertEqual([r["concept"] for r in rows], sorted(R + name for name in
        ("Revenue", "Title", "Empty", "Zero", "MissingNumber", "MissingText")))
    by_name = {r["concept"]: r for r in rows}
    case.assertEqual(by_name[R + "Revenue"], {
        "concept": R + "Revenue", "type": R + "Limited", "primitive": "{" + XS + "}decimal",
        "white_space": "collapse", "min_inclusive": "0", "max_inclusive": "20",
        "enumeration": ["12.3"]})
    case.assertEqual(by_name[R + "Title"], {
        "concept": R + "Title", "type": R + "TitleType", "primitive": "{" + XS + "}string",
        "white_space": "collapse", "min_inclusive": None, "max_inclusive": None,
        "enumeration": ["A B"]})


class TypedScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="typed-xcollect-")
        self.addCleanup(self.tmp.cleanup)
        self.database = str(Path(self.tmp.name) / "archive.sqlite")
        self.c = Collector(self.database)
        self.addCleanup(lambda: self.c.close())

    def reopen(self):
        self.c.close()
        self.c = Collector(self.database)

    def test_binding_and_reopen(self):
        pack = package()
        rid = self.c.ingest_typed("typed", BODY, pack)
        self.assertEqual(values(self.c, rid), EXPECTED_VALUES)
        views = self.c.read_facts(rid)
        self.assertEqual([str(v.value) if v.kind == "numeric" and not v.nil else v.value
                          for v in views], EXPECTED_VALUES)
        before = self.c.export_evidence(rid)
        self.assertEqual(before["digest"], hashlib.sha256(BODY).hexdigest())
        self.assertEqual(self.c.receipt("typed").digest, before["digest"])
        self.assertEqual(before["facts"][1]["source"]["raw_text"], " \t A \n B  ")
        self.assertEqual(before["facts"][1]["source"]["path"], [1, 5])
        check_basis(self, before, pack)
        self.assertEqual(self.c.ingest_typed("typed", BODY, dict(reversed(list(pack.items())))), rid)
        extra = dict(pack, **{"https://tax.example/unused.xsd": b"not XML"})
        self.assertEqual(self.c.ingest_typed("typed", BODY, extra), rid)
        pack.clear()
        self.reopen()
        self.assertEqual(self.c.export_evidence(rid), before)
        self.assertEqual(values(self.c, rid), EXPECTED_VALUES)
        with Collector() as other:
            self.assertEqual(other.ingest_typed("typed", BODY, package()), rid)

    def test_changed_basis_and_modes(self):
        rid = self.c.ingest_typed("typed", BODY, package())
        before = self.c.export_evidence(rid)
        for core in (CORE + b"\n", CORE.replace(b'value="20"', b'value="10"')):
            changed = package()
            changed[CORE_URI] = core
            with self.assertRaises(DocumentConflictError):
                self.c.ingest_typed("typed", BODY, changed)
        with self.assertRaises(BusinessValidationError):
            self.c.ingest_typed("tight-new", BODY, changed)
        with self.assertRaises(DocumentConflictError):
            self.c.ingest_xbrl("typed", BODY)
        old = self.c.ingest_xbrl("ordinary", BODY)
        self.assertEqual(self.c.read_facts(old)[1].value, " \t A \n B  ")
        self.assertNotIn("type_basis", self.c.export_evidence(old))
        with self.assertRaises(DocumentConflictError):
            self.c.ingest_typed("ordinary", BODY, package())
        self.reopen()
        self.assertEqual(self.c.export_evidence(rid), before)
        self.assertEqual(self.c.read_facts(old)[1].value, " \t A \n B  ")

    def test_invalid_packages_and_values(self):
        good = self.c.ingest_typed("good", BODY, package())
        before = self.c.export_evidence(good)
        loosened = REPORT.replace(b'<xs:enumeration value="12.30"/>',
                                 b'<xs:maxInclusive value="30"/>')
        self_cycle = REPORT.replace(b'base="q:Amount"', b'base="r:Limited"')
        duplicate = REPORT.replace(b'</xs:schema>', b'<xs:element name="Revenue" type="xs:string"/></xs:schema>')
        import_cycle = CORE.replace(b'<xs:simpleType name="Amount">',
            ('<xs:import namespace="urn:report" schemaLocation="' + ROOT_URI + '"/>'
             '<xs:simpleType name="Amount">').encode())
        wrong_namespace = CORE.replace(b'targetNamespace="urn:types"', b'targetNamespace="urn:other"')
        cases = [
            (BODY, {ROOT_URI: REPORT}),
            (BODY, {ROOT_URI: loosened, CORE_URI: CORE}),
            (BODY, {ROOT_URI: self_cycle, CORE_URI: CORE}),
            (BODY, {ROOT_URI: duplicate, CORE_URI: CORE}),
            (BODY, {ROOT_URI: REPORT, CORE_URI: import_cycle}),
            (BODY, {ROOT_URI: REPORT, CORE_URI: wrong_namespace}),
            (BODY.replace(b' A \n B ', b' A C '), package()),
            (BODY.replace(b'<r:Title contextRef="c1">', b'<r:Title contextRef="c1" unitRef="u1">'), package()),
            (BODY.replace(b'unitRef="u1" decimals="2"', b'decimals="2"'), package()),
            (BODY.replace(b'r:Empty', b'r:Unknown'), package()),
            (BODY.replace(SCHEMA_REF.encode(), b""), package()),
            (BODY.replace(SCHEMA_REF.encode(), (SCHEMA_REF * 2).encode()), package()),
        ]
        for index, (body, pack) in enumerate(cases):
            name = "bad-" + str(index)
            with self.subTest(index=index):
                with self.assertRaises(BusinessValidationError):
                    self.c.ingest_typed(name, body, pack)
                self.assertIsNone(self.c.receipt(name))
                self.assertEqual(self.c.export_evidence(good), before)
        self.c.ingest_typed("bad-0", BODY, package())

    def test_transaction_rollback(self):
        rid = self.c.ingest_typed("good", BODY, package())
        before = self.c.export_evidence(rid)
        con = self.c.repository.connection
        con.execute("""CREATE TRIGGER stop_typed_receipt BEFORE INSERT ON receipts
            WHEN NEW.document_id='blocked'
            BEGIN SELECT RAISE(ABORT, 'typed receipt blocked'); END""")
        state = tuple(con.iterdump())
        with self.assertRaisesRegex(sqlite3.IntegrityError, "typed receipt blocked"):
            self.c.ingest_typed("blocked", BODY, package())
        self.assertEqual(tuple(con.iterdump()), state)
        self.assertIsNone(self.c.receipt("blocked"))
        con.execute("DROP TRIGGER stop_typed_receipt")
        self.reopen()
        self.assertEqual(self.c.export_evidence(rid), before)
        new = self.c.ingest_typed("blocked", BODY, package())
        self.assertEqual(values(self.c, new), EXPECTED_VALUES)


def materials():
    for uri, body in package().items():
        root = ET.fromstring(body)
        assert root.tag == "{" + XS + "}schema"
        print(uri, hashlib.sha256(body).hexdigest(), len(body))
    root = ET.fromstring(BODY)
    assert len(root) == 9
    assert root[4].text == " \t A \n B  "
    with Collector() as c:
        rid = c.ingest_xbrl("materials-v1", BODY)
        assert c.read_facts(rid)[1].value == " \t A \n B  "
        assert "type_basis" not in c.export_evidence(rid)
    print("MATERIALS_OK", json.dumps({"handwritten_typed_values": EXPECTED_VALUES,
          "scope": "input syntax and ordinary V1 only"}, ensure_ascii=False))


def run_demo():
    case = unittest.TestCase()
    with tempfile.TemporaryDirectory(prefix="typed-demo-") as directory:
        database = str(Path(directory) / "archive.sqlite")
        with Collector(database) as c:
            result = c.ingest_typed("report-old", BODY, package())
            case.assertEqual(values(c, result), EXPECTED_VALUES)
            before = c.export_evidence(result)
            check_basis(case, before, package())
            tighter = package()
            tighter[CORE_URI] = CORE.replace(b'value="20"', b'value="10"')
            with case.assertRaises(BusinessValidationError):
                c.ingest_typed("report-new", BODY, tighter)
            case.assertIsNone(c.receipt("report-new"))
        with Collector(database) as c:
            case.assertEqual(c.export_evidence(result), before)
            print(json.dumps({"fixed_result": result, "values": values(c, result),
                  "new_upper_10": "rejected", "reopened_type_basis": before["type_basis"]},
                  ensure_ascii=False, sort_keys=True))


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ["materials"]:
        materials()
        return 0
    if args == ["verify"]:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(TypedScenarios)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args == ["demo"]:
        run_demo()
        return 0
    raise SystemExit("usage: typed_scenarios.py materials|verify|demo")


if __name__ == "__main__":
    raise SystemExit(main())
