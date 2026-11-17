from dataclasses import dataclass
from xcollect.errors import BusinessValidationError
from xcollect.documents.xml import container, leaf_text
from xcollect.resources.names import XBRLI_NS, XML_WS, expand_qname

P = "{" + XBRLI_NS + "}"


@dataclass(frozen=True)
class Unit:
    id: str
    numerator: tuple
    denominator: tuple


def unit_key(unit):
    return (unit.numerator, unit.denominator)


def _measures(element, parsed):
    container(element)
    if not len(element) or any(c.tag != P + "measure" for c in element):
        raise BusinessValidationError("unit side requires measures")
    return tuple(expand_qname(leaf_text(c), parsed.scope_for(c)) for c in element)


def parse_unit(element, parsed):
    container(element, ("id",))
    resource_id = element.get("id")
    if not resource_id or resource_id.strip(XML_WS) != resource_id:
        raise BusinessValidationError("unit needs a nonblank id")
    if len(element) and all(c.tag == P + "measure" for c in element):
        # The outer unit permits its id; measure order and duplicates are retained.
        numerator = tuple(expand_qname(leaf_text(c), parsed.scope_for(c)) for c in element)
        return Unit(resource_id, numerator, ())
    if len(element) != 1 or element[0].tag != P + "divide":
        raise BusinessValidationError("mixed or empty unit")
    divide = element[0]
    container(divide)
    if [c.tag for c in divide] != [P + "unitNumerator", P + "unitDenominator"]:
        raise BusinessValidationError("divide requires numerator then denominator")
    return Unit(resource_id, _measures(divide[0], parsed), _measures(divide[1], parsed))
