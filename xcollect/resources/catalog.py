from dataclasses import dataclass
from types import MappingProxyType
from xcollect.errors import BusinessValidationError
from xcollect.resources.names import XBRLI_NS
from xcollect.resources.contexts import parse_context
from xcollect.resources.units import parse_unit

P = "{" + XBRLI_NS + "}"


@dataclass(frozen=True)
class ResourceCatalog:
    contexts: object
    units: object

    def context(self, resource_id):
        try:
            return self.contexts[resource_id]
        except KeyError as exc:
            raise BusinessValidationError("missing local context: " + str(resource_id)) from exc

    def unit(self, resource_id):
        try:
            return self.units[resource_id]
        except KeyError as exc:
            raise BusinessValidationError("missing local unit: " + str(resource_id)) from exc


def build_catalog(parsed):
    contexts, units, ids = {}, {}, set()
    for element in parsed.root:
        if element.tag == P + "context":
            value = parse_context(element)
            target = contexts
        elif element.tag == P + "unit":
            value = parse_unit(element, parsed)
            target = units
        else:
            continue
        if value.id in ids:
            raise BusinessValidationError("duplicate resource id: " + value.id)
        ids.add(value.id)
        target[value.id] = value
    return ResourceCatalog(MappingProxyType(contexts), MappingProxyType(units))
