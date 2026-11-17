"""Typed fact normalization and batch validation against a resolved type basis."""
from decimal import Decimal
from xcollect.errors import BusinessValidationError
from xcollect.facts.candidates import OrdinaryFactCandidate, SingleElementSource
from xcollect.facts.extract import extract_leaf_fact
from xcollect.facts.numeric import parse_nil, parse_decimals, parse_numeric_value
from xcollect.resources.names import XML_WS, validate_expanded_name
from xcollect.typed.limits import DECIMAL, normalize_text
from xcollect.typed.basis import TypeBasis


def _declaration(basis, concept):
    if type(basis) is not TypeBasis:
        raise BusinessValidationError("typed fact requires a resolved type basis")
    return basis.concept(concept)


def _permits(declaration, value):
    if declaration.primitive == DECIMAL:
        if declaration.minimum is not None and value < declaration.minimum:
            return False
        if declaration.maximum is not None and value > declaration.maximum:
            return False
    return declaration.enumeration is None or value in declaration.enumeration


def normalize_typed_fact(raw, basis):
    declaration = _declaration(basis, raw.concept)
    numeric = declaration.primitive == DECIMAL
    if (raw.unit_ref is not None) != numeric:
        raise BusinessValidationError("unitRef disagrees with the declared concept type")
    nil = parse_nil(raw.nil_lexical)
    decimals = parse_decimals(raw.decimals_lexical)
    if not numeric and decimals is not None:
        raise BusinessValidationError("text cannot declare decimals")
    if nil:
        if raw.raw_text.strip(XML_WS):
            raise BusinessValidationError("nil fact contains content")
        value = None
    elif numeric:
        value = parse_numeric_value(raw.raw_text)
        if not _permits(declaration, value):
            raise BusinessValidationError("numeric fact outside the declared type domain")
    else:
        value = normalize_text(raw.raw_text, declaration.white_space)
        if not _permits(declaration, value):
            raise BusinessValidationError("text fact outside the declared type domain")
    kind = "numeric" if numeric else "text"
    return OrdinaryFactCandidate(raw.ordinal, raw.concept, raw.context_ref, raw.unit_ref,
                                 kind, value, nil, decimals, raw.source)


def validate_typed_fact(fact, catalog, basis):
    if type(fact) is not OrdinaryFactCandidate or type(fact.ordinal) is not int or fact.ordinal < 1:
        raise BusinessValidationError("invalid candidate identity")
    validate_expanded_name(fact.concept)
    declaration = _declaration(basis, fact.concept)
    catalog.context(fact.context_ref)
    if fact.unit_ref is not None:
        catalog.unit(fact.unit_ref)
    expected_kind = "numeric" if declaration.primitive == DECIMAL else "text"
    if fact.kind != expected_kind:
        raise BusinessValidationError("fact kind disagrees with its declared type")
    if (fact.unit_ref is not None) != (expected_kind == "numeric"):
        raise BusinessValidationError("fact unit disagrees with its declared type")
    if type(fact.nil) is not bool:
        raise BusinessValidationError("nil must be bool")
    if fact.decimals is not None and fact.decimals != "INF" and type(fact.decimals) is not int:
        raise BusinessValidationError("invalid decimals metadata")
    if expected_kind == "text" and fact.decimals is not None:
        raise BusinessValidationError("text decimals metadata")
    if fact.nil:
        if fact.value is not None or fact.source.raw_text.strip(XML_WS):
            raise BusinessValidationError("invalid nil candidate")
        return
    if expected_kind == "numeric":
        if not isinstance(fact.value, Decimal) or not fact.value.is_finite():
            raise BusinessValidationError("invalid numeric candidate")
        if parse_numeric_value(fact.source.raw_text).as_tuple() != fact.value.as_tuple():
            raise BusinessValidationError("numeric value does not match its source")
        if not _permits(declaration, fact.value):
            raise BusinessValidationError("numeric value outside the declared type domain")
    else:
        if type(fact.value) is not str:
            raise BusinessValidationError("invalid text candidate")
        if normalize_text(fact.source.raw_text, declaration.white_space) != fact.value:
            raise BusinessValidationError("text value does not match its source")
        if not _permits(declaration, fact.value):
            raise BusinessValidationError("text value outside the declared type domain")


def validate_typed_source(fact, parsed, basis):
    source = fact.source
    if type(source) is not SingleElementSource:
        raise BusinessValidationError("typed facts require a single element source")
    if source.concept != fact.concept or not isinstance(source.raw_text, str):
        raise BusinessValidationError("source identity mismatch")
    if any(type(i) is not int for i in source.path):
        raise BusinessValidationError("invalid source path")
    element = parsed.element_at(source.path)
    if len(source.path) != 2 or element.tag != source.concept or len(element):
        raise BusinessValidationError("source must locate a direct ordinary leaf")
    if (element.text or "") != source.raw_text:
        raise BusinessValidationError("source text mismatch")
    expected = normalize_typed_fact(extract_leaf_fact(element, fact.ordinal, parsed), basis)
    if fact != expected:
        raise BusinessValidationError("candidate does not match source")


def validate_typed_batch(facts, catalog, parsed, basis):
    facts = tuple(facts)
    paths = set()
    for ordinal, fact in enumerate(facts, 1):
        if fact.ordinal != ordinal or fact.source.path in paths:
            raise BusinessValidationError("duplicate or discontinuous fact identity")
        validate_typed_fact(fact, catalog, basis)
        validate_typed_source(fact, parsed, basis)
        paths.add(fact.source.path)
    expected_count = sum("contextRef" in e.attrib for e in parsed.root)
    if len(facts) != expected_count:
        raise BusinessValidationError("incomplete fact batch")
    return facts
