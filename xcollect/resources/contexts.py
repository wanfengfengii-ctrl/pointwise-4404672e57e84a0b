from dataclasses import dataclass
from xcollect.errors import BusinessValidationError
from xcollect.documents.xml import container, leaf_text
from xcollect.resources.names import XBRLI_NS, XML_WS
from xcollect.resources.periods import make_instant_period, make_duration_period

P = "{" + XBRLI_NS + "}"


@dataclass(frozen=True)
class Context:
    id: str
    identifier: str
    scheme: str
    period: object


def parse_context(element):
    container(element, ("id",))
    resource_id = element.get("id")
    if not resource_id or resource_id.strip(XML_WS) != resource_id:
        raise BusinessValidationError("context needs a nonblank id")
    children = list(element)
    if [c.tag for c in children] != [P + "entity", P + "period"]:
        raise BusinessValidationError("context requires entity then period")
    entity, period = children
    container(entity)
    if len(entity) != 1 or entity[0].tag != P + "identifier":
        raise BusinessValidationError("unsupported entity structure")
    identifier = leaf_text(entity[0], ("scheme",)).strip(XML_WS)
    scheme = entity[0].get("scheme")
    if not identifier or not scheme or not scheme.strip(XML_WS):
        raise BusinessValidationError("identifier and scheme are required")
    container(period)
    tags = [c.tag for c in period]
    if tags == [P + "instant"]:
        parsed = make_instant_period(leaf_text(period[0]).strip(XML_WS))
    elif tags == [P + "startDate", P + "endDate"]:
        parsed = make_duration_period(*(leaf_text(c).strip(XML_WS) for c in period))
    else:
        raise BusinessValidationError("unsupported period structure")
    return Context(resource_id, identifier, scheme, parsed)
