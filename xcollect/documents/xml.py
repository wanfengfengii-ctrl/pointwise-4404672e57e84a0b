from dataclasses import dataclass
from io import BytesIO
from types import MappingProxyType
from xml.etree import ElementTree as ET
from xml.parsers import expat
from xcollect.errors import BusinessValidationError
from xcollect.resources.names import XML_WS


def container(element, attributes=()):
    if set(element.attrib) - set(attributes):
        raise BusinessValidationError("unsupported attributes on " + element.tag)
    if (element.text or "").strip(XML_WS):
        raise BusinessValidationError("unexpected container text")
    if any((child.tail or "").strip(XML_WS) for child in element):
        raise BusinessValidationError("unexpected child tail")


def leaf_text(element, attributes=()):
    if len(element) or set(element.attrib) - set(attributes):
        raise BusinessValidationError("expected supported leaf " + element.tag)
    return element.text or ""


@dataclass(frozen=True)
class ParsedXML:
    root: object
    scopes: object
    paths: object

    def scope_for(self, element):
        return self.scopes[element]

    def path_for(self, element):
        return self.paths[element]

    def element_at(self, path):
        if not isinstance(path, tuple) or not path or path[0] != 1:
            raise BusinessValidationError("invalid element path")
        element = self.root
        for index in path[1:]:
            if type(index) is not int or not 1 <= index <= len(element):
                raise BusinessValidationError("element path does not exist")
            element = element[index - 1]
        return element


def parse_xml(data):
    def forbidden(*args):
        raise BusinessValidationError("DTD and entity declarations are unsupported")
    try:
        guard = expat.ParserCreate()
        guard.StartDoctypeDeclHandler = forbidden
        guard.EntityDeclHandler = forbidden
        guard.ExternalEntityRefHandler = forbidden
        guard.Parse(data, True)
        pending, stack, scopes, paths, counts = [], [], {}, {}, []
        root = None
        for event, item in ET.iterparse(BytesIO(data), events=("start-ns", "start", "end")):
            if event == "start-ns":
                pending.append(item)
            elif event == "start":
                scope = dict(stack[-1][1]) if stack else {"xml": "http://www.w3.org/XML/1998/namespace"}
                scope.update(pending)
                pending.clear()
                if stack:
                    counts[-1] += 1
                    path = paths[stack[-1][0]] + (counts[-1],)
                else:
                    root, path = item, (1,)
                scopes[item] = MappingProxyType(scope)
                paths[item] = path
                stack.append((item, scope))
                counts.append(0)
            else:
                stack.pop()
                counts.pop()
        return ParsedXML(root, MappingProxyType(scopes), MappingProxyType(paths))
    except (ET.ParseError, expat.ExpatError, UnicodeError, ValueError) as exc:
        if isinstance(exc, BusinessValidationError):
            raise
        raise BusinessValidationError("malformed XML: " + str(exc)) from exc
