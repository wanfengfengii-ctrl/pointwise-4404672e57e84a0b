import argparse
import json
from pathlib import Path
import tempfile
import unittest
from xcollect.errors import IntegrityError
from xcollect.documents.identity import (SourceIdentity, validate_document_input, source_digest,
                                         make_result_id, classify_submission)
from xcollect.documents.dispatch import prepare_ordinary_document
from xcollect.archive.repository import ArchiveRepository
from xcollect.archive.publish import publish_document
from xcollect.archive.receipts import ReceiptLookup
from xcollect.consumption.read import FactReader
from xcollect.consumption.export import EvidenceExporter
from xcollect.consumption.reconcile import reconcile_result


class Collector:
    def __init__(self, database=":memory:"):
        self.repository = ArchiveRepository(database)

    def ingest_xbrl(self, document_id, xml_bytes):
        validate_document_input(document_id, xml_bytes)
        digest = source_digest(xml_bytes)
        identity = SourceIdentity(document_id, digest, make_result_id(document_id, digest))
        if classify_submission(self.repository.sources, identity, xml_bytes) == "retry":
            receipt = self.receipt(document_id)
            if receipt is None or receipt.result_id != identity.result_id:
                raise IntegrityError("successful source lacks a receipt")
            reconcile_result(self.repository.load_published(receipt.result_id))
            return receipt.result_id
        prepared = prepare_ordinary_document(xml_bytes)
        result_id = publish_document(self.repository, identity, xml_bytes, prepared)
        return result_id

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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ordinary XBRL collection and evidence archive")
    parser.add_argument("command", choices=("verify", "demo", "ingest", "read", "export"))
    parser.add_argument("--db")
    parser.add_argument("--document-id")
    parser.add_argument("--file")
    parser.add_argument("--result-id")
    args = parser.parse_args(argv)
    if args.command == "verify":
        root = Path(__file__).resolve().parents[2]
        suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py", top_level_dir=str(root))
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.command == "demo":
        run_demo()
        return 0
    if not args.db:
        parser.error("--db is required")
    if args.command == "ingest" and (not args.document_id or not args.file):
        parser.error("ingest requires --document-id and --file")
    if args.command in ("read", "export") and not args.result_id:
        parser.error("read/export requires --result-id")
    with Collector(args.db) as collector:
        if args.command == "ingest":
            print(collector.ingest_xbrl(args.document_id, Path(args.file).read_bytes()))
        elif args.command == "export":
            print(json.dumps(collector.export_evidence(args.result_id), ensure_ascii=False, sort_keys=True))
        else:
            for fact in collector.read_facts(args.result_id):
                print(fact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
