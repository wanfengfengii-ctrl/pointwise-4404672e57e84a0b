"""Persistence records for a typed result's fixed type basis."""
from decimal import Decimal, InvalidOperation
import json
from xcollect.errors import BusinessValidationError, IntegrityError
from xcollect.facts.candidates import OrdinaryFactCandidate
from xcollect.facts.numeric import parse_decimals
from xcollect.typed.basis import TypeBasis, load_closure, resolve_basis, sha256_hex
from xcollect.typed.limits import DECIMAL, STRING, canonical_decimal

XS = "http://www.w3.org/2001/XMLSchema"
PRIMITIVE_NAMES = {DECIMAL: "{" + XS + "}decimal", STRING: "{" + XS + "}string"}
PRIMITIVES = {value: key for key, value in PRIMITIVE_NAMES.items()}


def basis_record(item):
    """Export record for one concept's declaration type and effective limits."""
    if item.primitive == DECIMAL:
        enumeration = None if item.enumeration is None else [
            canonical_decimal(value) for value in item.enumeration]
        minimum = None if item.minimum is None else canonical_decimal(item.minimum)
        maximum = None if item.maximum is None else canonical_decimal(item.maximum)
    else:
        enumeration = None if item.enumeration is None else list(item.enumeration)
        minimum = maximum = None
    return {"concept": item.concept, "type": item.type_name,
            "primitive": PRIMITIVE_NAMES[item.primitive], "white_space": item.white_space,
            "min_inclusive": minimum, "max_inclusive": maximum, "enumeration": enumeration}


def concept_row(item):
    record = basis_record(item)
    enumeration = record["enumeration"]
    return (record["concept"], record["type"], record["primitive"], record["white_space"],
            record["min_inclusive"], record["max_inclusive"],
            None if enumeration is None else json.dumps(enumeration, ensure_ascii=False,
                                                        separators=(",", ":")))


def _canonical_literal(text):
    """Persisted decimal limits must already be in canonical fixed-point form."""
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise IntegrityError("invalid persisted decimal limit") from exc
    if not value.is_finite() or canonical_decimal(value) != text:
        raise IntegrityError("noncanonical persisted decimal limit")
    return value


def _stored_record(row):
    primitive = PRIMITIVES.get(row["primitive"])
    if primitive is None:
        raise IntegrityError("unknown persisted primitive type")
    enumeration = row["enumeration"]
    if enumeration is not None:
        try:
            enumeration = json.loads(enumeration)
        except ValueError as exc:
            raise IntegrityError("invalid persisted enumeration") from exc
        if not isinstance(enumeration, list) or not enumeration or not all(
                type(value) is str for value in enumeration):
            raise IntegrityError("invalid persisted enumeration")
    minimum, maximum = row["min_inclusive"], row["max_inclusive"]
    if (minimum is not None and type(minimum) is not str) or (
            maximum is not None and type(maximum) is not str):
        raise IntegrityError("invalid persisted bounds")
    if primitive == DECIMAL:
        values = None if enumeration is None else tuple(
            _canonical_literal(value) for value in enumeration)
        low = None if minimum is None else _canonical_literal(minimum)
        high = None if maximum is None else _canonical_literal(maximum)
    else:
        if minimum is not None or maximum is not None:
            raise IntegrityError("string type cannot persist numeric bounds")
        values, low, high = (None if enumeration is None else tuple(enumeration)), None, None
    return (row["concept"], row["type_name"], primitive, row["white_space"], low, high, values)


def persisted_concepts(snapshot):
    rows = snapshot.get("typed_concepts") or []
    if not rows:
        raise IntegrityError("missing persisted concept type basis")
    return tuple(_stored_record(row) for row in rows)


def check_file_digests(snapshot):
    """Every persisted reachable file must match its recorded SHA-256."""
    from hashlib import sha256
    files = snapshot.get("typed_schemas") or []
    if not files:
        raise IntegrityError("missing persisted schema files")
    if [row["uri"] for row in files] != sorted(row["uri"] for row in files) or len(
            {row["uri"] for row in files}) != len(files):
        raise IntegrityError("persisted schema files are not a sorted unique set")
    for row in files:
        if type(row["body"]) is not bytes or sha256(row["body"]).hexdigest() != row["sha256"]:
            raise IntegrityError("persisted schema digest mismatch")
    return files


def derived_basis(snapshot):
    """Rebuild the type basis from the persisted original schema bytes."""
    typed = snapshot.get("typed_result")
    files = check_file_digests(snapshot)
    if typed is None:
        raise IntegrityError("missing typed result metadata")
    bodies = {row["uri"]: row["body"] for row in files}
    try:
        return resolve_basis(load_closure(typed["root_uri"], bodies))
    except BusinessValidationError as exc:
        raise IntegrityError("persisted type basis is invalid: " + str(exc)) from exc


def check_basis(basis, snapshot):
    """Cross-check re-derived limits against the persisted rows and file digests."""
    files = check_file_digests(snapshot)
    if [(file.uri, sha256_hex(file.body)) for file in basis.files] != [
            (row["uri"], row["sha256"]) for row in files]:
        raise IntegrityError("persisted reachable schema set mismatch")
    persisted = persisted_concepts(snapshot)
    derived = tuple((item.concept, item.type_name, item.primitive, item.white_space,
                     item.minimum, item.maximum, item.enumeration) for item in basis.concepts)
    if derived != persisted:
        raise IntegrityError("persisted effective limits disagree with the type basis")
    if [item.concept for item in basis.concepts] != sorted(item[0] for item in persisted):
        raise IntegrityError("persisted concept order mismatch")
    return basis


def typed_fact_from_row(row, source):
    value = row["value"]
    if row["kind"] == "numeric" and value is not None:
        value = Decimal(value)
    return OrdinaryFactCandidate(row["ordinal"], row["concept"], row["context_ref"], row["unit_ref"],
                                 row["kind"], value, bool(row["nil"]),
                                 parse_decimals(row["decimals"]), source)


__all__ = ["basis_record", "concept_row", "check_basis", "derived_basis", "persisted_concepts",
           "typed_fact_from_row", "TypeBasis"]
