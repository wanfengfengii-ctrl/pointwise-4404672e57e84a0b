import argparse
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from xcollect.errors import BusinessValidationError, DocumentConflictError, IntegrityError
from xcollect.documents.identity import (SourceIdentity, validate_document_input, source_digest,
                                         make_result_id, make_typed_identity,
                                         classify_submission, classify_typed_submission)
from xcollect.documents.dispatch import prepare_ordinary_document
from xcollect.typed.dispatch import prepare_typed_document, typed_identity
from xcollect.archive.repository import ArchiveRepository
from xcollect.archive.publish import publish_document, publish_typed_document
from xcollect.archive.receipts import ReceiptLookup
from xcollect.consumption.read import FactReader
from xcollect.consumption.export import EvidenceExporter
from xcollect.consumption.reconcile import reconcile_result


def _v1_identity(document_id, digest):
    return SourceIdentity(document_id, digest, make_result_id(document_id, digest))


class Collector:
    def __init__(self, database=":memory:"):
        self.repository = ArchiveRepository(database)

    def ingest_xbrl(self, document_id, xml_bytes):
        validate_document_input(document_id, xml_bytes)
        digest = source_digest(xml_bytes)
        identity = _v1_identity(document_id, digest)
        if classify_submission(self.repository.sources, identity, xml_bytes) == "retry":
            return self._retried(identity)
        prepared = prepare_ordinary_document(xml_bytes)
        return publish_document(self.repository, identity, xml_bytes, prepared)

    def ingest_typed(self, document_id, xml_bytes, schemas):
        validate_document_input(document_id, xml_bytes)
        digest = source_digest(xml_bytes)
        if self.repository.sources.read(document_id) is None:
            prepared = prepare_typed_document(xml_bytes, schemas)
            identity = make_typed_identity(document_id, digest,
                                           [(file.uri, source_digest(file.body))
                                            for file in prepared.basis.files])
            return publish_typed_document(self.repository, identity, xml_bytes, prepared)
        if self.repository.read_mode(document_id) != "typed":
            raise DocumentConflictError("document_id already binds a V1 result")
        # Replay check: identity from structure and the import closure only, so an existing
        # binding is compared before type evaluation or fact-domain checks run.
        identity, closure = typed_identity(document_id, digest, xml_bytes, schemas)
        if classify_typed_submission(self.repository.connection, self.repository.sources,
                                     document_id, xml_bytes, closure.bodies()) != "retry":
            raise IntegrityError("typed source disappeared during submission")
        return self._retried(identity)

    def _retried(self, identity):
        receipt = self.receipt(identity.document_id)
        if receipt is None or receipt.result_id != identity.result_id:
            raise IntegrityError("successful source lacks a receipt")
        reconcile_result(self.repository.load_published(receipt.result_id))
        return receipt.result_id

    def receipt(self, document_id):
        return ReceiptLookup(self.repository).receipt(document_id)

    def read_facts(self, result_id, concept=None, period=None):
        return FactReader(self.repository).read_facts(result_id, concept, period)

    def export_evidence(self, result_id):
        return EvidenceExporter(self.repository).export_evidence(result_id)

    def close(self):
        self.repository.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def run_demo():
    root = Path(__file__).resolve().parents[2]
    body = (root / "samples/ordinary.xml").read_bytes()
    expected = json.loads((root / "samples/expected.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="xcollect-demo-") as directory:
        database = str(Path(directory) / "archive.sqlite")
        with Collector(database) as collector:
            result_id = collector.ingest_xbrl("annual-2025", body)
            assert collector.ingest_xbrl("annual-2025", body) == result_id
            before = collector.export_evidence(result_id)
        with Collector(database) as reopened:
            exported = reopened.export_evidence(result_id)
            assert before == exported
            assert exported["facts"] == expected["facts"]
            assert len(reopened.read_facts(result_id)) == expected["fact_count"]
            actual = [r["value"] for r in exported["facts"]]
            assert actual == expected["values"]
            selected = reopened.read_facts(result_id, "{urn:report}Revenue", ("duration", "2025-01-01", "2025-12-31"))
            assert [str(f.value) for f in selected] == ["12.30"]
            print("POINTWISE_SCENARIO " + json.dumps({
                "case_id": "V1", "input": {"document_id": "annual-2025", "bytes": len(body)},
                "expected": expected["values"], "actual": actual,
                "downstream_expected": ["12.30"], "downstream_actual": [str(f.value) for f in selected],
                "code_paths": ["xcollect/documents/dispatch.py", "xcollect/facts/numeric.py",
                               "xcollect/archive/publish.py", "xcollect/consumption/export.py"],
                "oracle": "handwritten sample records, exact decimal strings and source paths"
            }, ensure_ascii=False, sort_keys=True))
            print(json.dumps(exported, ensure_ascii=False, sort_keys=True))


def run_typed_demo():
    import typed_scenarios as scenarios
    scenarios.run_demo()
    with tempfile.TemporaryDirectory(prefix="xcollect-typed-demo-") as directory:
        database = str(Path(directory) / "archive.sqlite")
        with Collector(database) as collector:
            result_id = collector.ingest_typed("report-old", scenarios.BODY, scenarios.package())
            exported = collector.export_evidence(result_id)
            revenue = collector.read_facts(result_id, "{urn:report}Revenue")[0]
            title = collector.read_facts(result_id, "{urn:report}Title")[0]
            title_record = exported["facts"][1]
            basis = {row["concept"]: row for row in exported["type_basis"]["concepts"]}
            tightened = scenarios.package()
            tightened[scenarios.CORE_URI] = scenarios.CORE.replace(b'value="20"', b'value="10"')
            try:
                collector.ingest_typed("report-new", scenarios.BODY, tightened)
                rejected = False
            except BusinessValidationError:
                rejected = True
        with Collector(database) as reopened:
            fixed = reopened.export_evidence(result_id)
            room = basis["{urn:report}Revenue"]
            print("TYPED_BINDING " + json.dumps({
                "enumeration_declared_in_xsd": "12.30",
                "enumeration_canonical_in_basis": room["enumeration"],
                "fact_lexical": exported["facts"][0]["source"]["raw_text"],
                "fact_value": exported["facts"][0]["value"],
                "fact_matches_enumeration": revenue.value in [
                    Decimal(value) for value in room["enumeration"]],
                "declared_12_30_matches_fact_12_3": Decimal("12.30") == revenue.value,
                "collapse_source_raw": title_record["source"]["raw_text"],
                "collapse_value": title.value,
                "tightened_upper_10_rejected": rejected,
                "reopened_export_unchanged": fixed == exported,
            }, ensure_ascii=False, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ordinary and typed XBRL collection archive")
    parser.add_argument("command", choices=("verify", "demo", "ingest", "ingest-typed",
                                            "read", "export"))
    parser.add_argument("--db")
    parser.add_argument("--document-id")
    parser.add_argument("--file")
    parser.add_argument("--schema", action="append", default=[])
    parser.add_argument("--result-id")
    args = parser.parse_args(argv)
    if args.command == "verify":
        root = Path(__file__).resolve().parents[2]
        suite = unittest.TestSuite([
            unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py",
                                                top_level_dir=str(root)),
            typed_scenarios_suite(),
        ])
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.command == "demo":
        run_demo()
        run_typed_demo()
        return 0
    if not args.db:
        parser.error("--db is required")
    if args.command in ("ingest", "ingest-typed") and (not args.document_id or not args.file):
        parser.error(args.command + " requires --document-id and --file")
    if args.command == "ingest-typed" and not args.schema:
        parser.error("ingest-typed requires at least one --schema URI=PATH")
    if args.command in ("read", "export") and not args.result_id:
        parser.error("read/export requires --result-id")
    with Collector(args.db) as collector:
        if args.command == "ingest":
            print(collector.ingest_xbrl(args.document_id, Path(args.file).read_bytes()))
        elif args.command == "ingest-typed":
            print(collector.ingest_typed(args.document_id, Path(args.file).read_bytes(),
                                         _read_schemas(parser, args.schema)))
        elif args.command == "export":
            print(json.dumps(collector.export_evidence(args.result_id), ensure_ascii=False, sort_keys=True))
        else:
            for fact in collector.read_facts(args.result_id):
                print(fact)
    return 0


def _read_schemas(parser, declarations):
    schemas = {}
    for declaration in declarations:
        uri, separator, path = declaration.partition("=")
        if not separator or not uri or not path:
            parser.error("--schema must be URI=PATH")
        if uri in schemas:
            parser.error("duplicate --schema URI: " + uri)
        schemas[uri] = Path(path).read_bytes()
    return schemas


def typed_scenarios_suite():
    import typed_scenarios
    return unittest.defaultTestLoader.loadTestsFromTestCase(typed_scenarios.TypedScenarios)


if __name__ == "__main__":
    raise SystemExit(main())
