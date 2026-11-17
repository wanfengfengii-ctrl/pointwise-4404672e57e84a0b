from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from types import MappingProxyType
from xcollect.errors import IntegrityError, BusinessValidationError
from xcollect.archive.evidence import validate_evidence_bundle
from xcollect.resources.catalog import ResourceCatalog
from xcollect.resources.contexts import Context
from xcollect.resources.units import Unit
from xcollect.resources.periods import Period
from xcollect.resources.names import validate_expanded_name
from xcollect.facts.candidates import OrdinaryFactCandidate
from xcollect.facts.numeric import parse_decimals
from xcollect.facts.validation import validate_fact


@dataclass(frozen=True)
class Reconciliation:
    result_id: str
    fact_count: int
    facts: tuple
    catalog: ResourceCatalog
    evidence: object


def _reconcile(snapshot):
    result, receipt = snapshot["result"], snapshot["receipt"]
    if receipt is None or any(receipt[k] != result[k] for k in ("document_id", "result_id", "digest", "fact_count")):
        raise IntegrityError("receipt and result disagree")
    rows = snapshot["facts"]
    if result["fact_count"] != len(rows) or [r["ordinal"] for r in rows] != list(range(1, len(rows) + 1)):
        raise IntegrityError("fact count or ordinal mismatch")
    evidence = validate_evidence_bundle(snapshot)
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
    catalog = ResourceCatalog(MappingProxyType(contexts), MappingProxyType(units))
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
    return Reconciliation(result["result_id"], len(facts), tuple(facts), catalog, MappingProxyType(evidence))


def reconcile_result(snapshot):
    try:
        return _reconcile(snapshot)
    except (BusinessValidationError, ValueError, TypeError, KeyError, InvalidOperation) as exc:
        raise IntegrityError("invalid persisted result: " + str(exc)) from exc
