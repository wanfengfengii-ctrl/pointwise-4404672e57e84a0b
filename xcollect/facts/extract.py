from xcollect.errors import BusinessValidationError
from xcollect.resources.names import XBRLI_NS, XSI_NS, LINK_NS, validate_expanded_name
from xcollect.facts.candidates import RawOrdinaryFact, SingleElementSource

ALLOWED_ATTRIBUTES = {"contextRef", "unitRef", "decimals", "{" + XSI_NS + "}nil", "id",
                      "{http://www.w3.org/XML/1998/namespace}lang"}


def extract_leaf_fact(element, ordinal, parsed):
    if len(element) or set(element.attrib) - ALLOWED_ATTRIBUTES:
        raise BusinessValidationError("unsupported fact structure or attribute")
    validate_expanded_name(element.tag)
    if element.tag.startswith(("{" + XBRLI_NS + "}", "{" + LINK_NS + "}")):
        raise BusinessValidationError("infrastructure cannot be a fact")
    context_ref = element.get("contextRef")
    unit_ref = element.get("unitRef")
    if not context_ref or (unit_ref is not None and not unit_ref):
        raise BusinessValidationError("empty resource reference")
    text = element.text or ""
    return RawOrdinaryFact(ordinal, element.tag, context_ref, unit_ref, text,
                           element.get("{" + XSI_NS + "}nil"), element.get("decimals"),
                           SingleElementSource(parsed.path_for(element), element.tag, text))


def extract_ordinary_facts(parsed):
    facts = []
    for element in parsed.root:
        if "contextRef" in element.attrib:
            facts.append(extract_leaf_fact(element, len(facts) + 1, parsed))
    return tuple(facts)
