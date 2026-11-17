from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from types import MappingProxyType
from xcollect.errors import IntegrityError, BusinessValidationError
from xcollect.archive.evidence import validate_evidence_bundle
from xcollect.documents.identity import make_result_id, make_typed_result_id
from xcollect.documents.xml import parse_xml
from xcollect.resources.catalog import ResourceCatalog
from xcollect.resources.contexts import Context
from xcollect.resources.units import Unit
from xcollect.resources.periods import Period
from xcollect.resources.names import validate_expanded_name
from xcollect.facts.candidates import OrdinaryFactCandidate
from xcollect.facts.numeric import parse_decimals
from xcollect.facts.validation import validate_fact
from xcollect.typed.records import check_basis, derived_basis, typed_fact_from_row
from xcollect.typed.validate import validate_typed_batch


@dataclass(frozen=True)
class Reconciliation:
    result_id: str
    fact_count: int
    facts: tuple
    catalog: ResourceCatalog
    evidence: object
    basis: object = None
    mode: str = "v1"


def _catalog(snapshot):
    contexts, units = {}, {}
    for row in snapshot["contexts"]:
        key = json.loads(row["period"])
        if not isinstance(key, list) or len(key) not in (2, 3):
            raise IntegrityError("invalid stored period")
        period = Period(*key)
        if not row["identifier"] or not row["scheme"]:
            raise IntegrityError("invalid stored entity")
        contexts[row["id"]] = Context(row["id"], row["identifier"], row["scheme"], period)
    for row in snapshot["units"]:
        numerator, denominator = json.loads(row["numerator"]), json.loads(row["denominator"])
        if not isinstance(numerator, list) or not numerator or not isinstance(denominator, list):
            raise IntegrityError("invalid stored unit")
        for name in numerator + denominator:
            validate_expanded_name(name)
        units[row["id"]] = Unit(row["id"], tuple(numerator), tuple(denominator))
    if set(contexts) & set(units):
        raise IntegrityError("resource identity collision")
    return ResourceCatalog(MappingProxyType(contexts), MappingProxyType(units))


def _check_envelope(snapshot):
    result, receipt = snapshot["result"], snapshot["receipt"]
    if receipt is None or any(receipt[k] != result[k] for k in ("document_id", "result_id", "digest", "fact_count")):
        raise IntegrityError("receipt and result disagree")
    rows = snapshot["facts"]
    if result["fact_count"] != len(rows) or [r["ordinal"] for r in rows] != list(range(1, len(rows) + 1)):
        raise IntegrityError("fact count or ordinal mismatch")
    return rows


def _v1(snapshot, rows, evidence):
    result = snapshot["result"]
    if make_result_id(result["document_id"], result["digest"]) != result["result_id"]:
        raise IntegrityError("fixed result identity mismatch")
    if snapshot.get("typed_result") is not None or snapshot.get("typed_schemas") \
            or snapshot.get("typed_concepts"):
        raise IntegrityError("ordinary result carries typed type basis")
    catalog = _catalog(snapshot)
    facts = []
    for row in rows:
        if row["nil"] not in (0, 1):
            raise IntegrityError("invalid persisted nil")
        value = row["value"]
        if row["kind"] == "numeric" and value is not None:
            value = Decimal(value)
        fact = OrdinaryFactCandidate(row["ordinal"], row["concept"], row["context_ref"], row["unit_ref"],
                                     row["kind"], value, bool(row["nil"]), parse_decimals(row["decimals"]),
                                     evidence[row["ordinal"]].source)
        validate_fact(fact, catalog)
        facts.append(fact)
    return Reconciliation(result["result_id"], len(facts), tuple(facts), catalog,
                          MappingProxyType(evidence))


def _typed(snapshot, rows, evidence):
    result = snapshot["result"]
    typed = snapshot.get("typed_result")
    if typed is None:
        raise IntegrityError("typed result lacks its type metadata")
    files = snapshot.get("typed_schemas") or []
    fingerprint = sorted((row["uri"], row["sha256"]) for row in files)
    if make_typed_result_id(result["document_id"], result["digest"], fingerprint) != result["result_id"]:
        raise IntegrityError("fixed typed result identity mismatch")
    basis = check_basis(derived_basis(snapshot), snapshot)
    if basis.root_uri != typed["root_uri"]:
        raise IntegrityError("typed result root schema disagrees with its basis")
    catalog = _catalog(snapshot)
    facts = []
    for row in rows:
        if row["nil"] not in (0, 1):
            raise IntegrityError("invalid persisted nil")
        fact = typed_fact_from_row(row, evidence[row["ordinal"]].source)
        declaration = basis.concept(fact.concept)
        if fact.kind != ("numeric" if declaration.primitive == "decimal" else "text"):
            raise IntegrityError("persisted fact kind disagrees with its declared type")
        facts.append(fact)
    try:
        validate_typed_batch(facts, catalog, parse_xml(snapshot["source"].body), basis)
    except BusinessValidationError as exc:
        raise IntegrityError("persisted typed facts do not match the instance: " + str(exc)) from exc
    return Reconciliation(result["result_id"], len(facts), tuple(facts), catalog,
                          MappingProxyType(evidence), basis, "typed")


def _reconcile(snapshot):
    rows = _check_envelope(snapshot)
    evidence = validate_evidence_bundle(snapshot)
    mode = snapshot.get("mode")
    if mode == "typed":
        return _typed(snapshot, rows, evidence)
    if mode not in (None, "v1"):
        raise IntegrityError("unknown acceptance mode")
    return _v1(snapshot, rows, evidence)


def reconcile_result(snapshot):
    try:
        return _reconcile(snapshot)
    except (BusinessValidationError, ValueError, TypeError, KeyError, InvalidOperation) as exc:
        raise IntegrityError("invalid persisted result: " + str(exc)) from exc

