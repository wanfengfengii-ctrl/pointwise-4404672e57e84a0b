from decimal import Decimal
from xcollect.errors import BusinessValidationError
from xcollect.facts.candidates import OrdinaryFactCandidate, SingleElementSource, normalize_candidate
from xcollect.facts.extract import extract_leaf_fact
from xcollect.facts.numeric import parse_numeric_value
from xcollect.resources.names import validate_expanded_name, XML_WS


def validate_single_source(fact, parsed):
    source = fact.source
    if type(source) is not SingleElementSource:
        raise BusinessValidationError("V1 requires a single element source")
    if source.concept != fact.concept or not isinstance(source.raw_text, str):
        raise BusinessValidationError("source identity mismatch")
    if any(type(i) is not int for i in source.path):
        raise BusinessValidationError("invalid source path")
    element = parsed.element_at(source.path)
    if len(source.path) != 2 or element.tag != source.concept or len(element):
        raise BusinessValidationError("source must locate a direct ordinary leaf")
    if (element.text or "") != source.raw_text:
        raise BusinessValidationError("source text mismatch")
    expected = normalize_candidate(extract_leaf_fact(element, fact.ordinal, parsed))
    if fact != expected:
        raise BusinessValidationError("candidate does not match source")


def validate_fact(fact, catalog):
    if type(fact) is not OrdinaryFactCandidate or type(fact.ordinal) is not int or fact.ordinal < 1:
        raise BusinessValidationError("invalid candidate identity")
    validate_expanded_name(fact.concept)
    catalog.context(fact.context_ref)
    if fact.unit_ref is not None:
        catalog.unit(fact.unit_ref)
    if fact.kind != ("numeric" if fact.unit_ref is not None else "text"):
        raise BusinessValidationError("fact kind and unit disagree")
    if type(fact.nil) is not bool:
        raise BusinessValidationError("nil must be bool")
    if fact.decimals is not None and fact.decimals != "INF" and type(fact.decimals) is not int:
        raise BusinessValidationError("invalid decimals metadata")
    if fact.kind == "text" and fact.decimals is not None:
        raise BusinessValidationError("text decimals metadata")
    if fact.nil:
        if fact.value is not None or fact.source.raw_text.strip(XML_WS):
            raise BusinessValidationError("invalid nil candidate")
    elif fact.kind == "text":
        if type(fact.value) is not str or fact.value != fact.source.raw_text:
            raise BusinessValidationError("text source mismatch")
    else:
        if not isinstance(fact.value, Decimal) or not fact.value.is_finite():
            raise BusinessValidationError("invalid numeric candidate")
        original = parse_numeric_value(fact.source.raw_text)
        if fact.value.as_tuple() != original.as_tuple():
            raise BusinessValidationError("numeric source mismatch")


def validate_batch(facts, catalog, parsed):
    facts = tuple(facts)
    paths = set()
    for ordinal, fact in enumerate(facts, 1):
        if fact.ordinal != ordinal or fact.source.path in paths:
            raise BusinessValidationError("duplicate or discontinuous fact identity")
        validate_fact(fact, catalog)
        validate_single_source(fact, parsed)
        paths.add(fact.source.path)
    expected_count = sum("contextRef" in e.attrib for e in parsed.root)
    if len(facts) != expected_count:
        raise BusinessValidationError("incomplete fact batch")
    return facts
