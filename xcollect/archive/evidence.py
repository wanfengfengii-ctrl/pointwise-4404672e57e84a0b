from dataclasses import dataclass
import json
from xcollect.errors import IntegrityError
from xcollect.documents.identity import source_digest, make_result_id
from xcollect.facts.candidates import SingleElementSource
from xcollect.resources.names import validate_expanded_name


@dataclass(frozen=True)
class SingleElementEvidence:
    result_id: str
    ordinal: int
    source: SingleElementSource


def load_single_evidence(row):
    path = json.loads(row["path"])
    if not isinstance(path, list) or len(path) != 2 or path[0] != 1:
        raise IntegrityError("invalid single-element path")
    if any(type(i) is not int or i < 1 for i in path):
        raise IntegrityError("invalid path indices")
    validate_expanded_name(row["concept"])
    if type(row["raw_text"]) is not str:
        raise IntegrityError("invalid persisted source text")
    return SingleElementEvidence(row["result_id"], row["ordinal"],
                                 SingleElementSource(tuple(path), row["concept"], row["raw_text"]))


def validate_evidence_bundle(snapshot):
    result, source = snapshot["result"], snapshot["source"]
    if source is None or source.document_id != result["document_id"]:
        raise IntegrityError("missing source document")
    if source_digest(source.body) != source.digest or result["digest"] != source.digest:
        raise IntegrityError("source digest mismatch")
    if make_result_id(source.document_id, source.digest) != result["result_id"]:
        raise IntegrityError("fixed result identity mismatch")
    evidence, paths = {}, set()
    for row in snapshot["single_sources"]:
        item = load_single_evidence(row)
        if item.result_id != result["result_id"] or item.ordinal in evidence:
            raise IntegrityError("evidence belongs to another result")
        if item.source.path in paths:
            raise IntegrityError("ordinary sources cannot share an element")
        paths.add(item.source.path)
        evidence[item.ordinal] = item
    if set(evidence) != {row["ordinal"] for row in snapshot["facts"]}:
        raise IntegrityError("incomplete evidence coverage")
    for row in snapshot["facts"]:
        if evidence[row["ordinal"]].source.concept != row["concept"]:
            raise IntegrityError("evidence concept mismatch")
    return evidence
