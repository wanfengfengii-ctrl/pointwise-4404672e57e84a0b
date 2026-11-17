"""Offline XSD subset: structural parsing, import closure and type resolution."""
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import re
from xcollect.documents.xml import parse_xml
from xcollect.errors import BusinessValidationError
from xcollect.resources.names import XML_WS, expanded_name, is_ncname
from xcollect.typed.limits import BASE_DECIMAL, BASE_STRING, apply_restriction

XS = "http://www.w3.org/2001/XMLSchema"
X = "{" + XS + "}"
FACETS = ("minInclusive", "maxInclusive", "whiteSpace", "enumeration")
SINGLETON_FACETS = ("minInclusive", "maxInclusive", "whiteSpace")
SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")


def is_absolute_uri(value):
    """RFC 3986 scheme present, no whitespace; compared as a plain string elsewhere."""
    if type(value) is not str or not value or value != value.strip(XML_WS):
        return False
    if any(character in " \t\r\n" for character in value):
        return False
    match = SCHEME.match(value)
    return match is not None and len(value) > match.end()


def sha256_hex(body):
    return sha256(body).hexdigest()


def _qname(value, scope):
    """Expand a QName against the declaring element's scope; no implicit targetNamespace."""
    if not isinstance(value, str):
        raise BusinessValidationError("expected a QName")
    text = value.strip(XML_WS)
    parts = text.split(":") if text else []
    if len(parts) == 1:
        prefix, local = "", parts[0]
    elif len(parts) == 2 and is_ncname(parts[0]):
        prefix, local = parts
    else:
        raise BusinessValidationError("invalid schema QName: " + str(value))
    namespace = scope.get(prefix)
    if not namespace:
        raise BusinessValidationError("unbound schema QName prefix: " + str(value))
    return expanded_name(namespace, local)


def _attributes(element, allowed):
    if set(element.attrib) - set(allowed):
        raise BusinessValidationError("unsupported attributes on " + element.tag)
    return {name: element.get(name) for name in allowed}


def _container(element):
    if (element.text or "").strip(XML_WS):
        raise BusinessValidationError("unexpected schema text in " + element.tag)
    if any((child.tail or "").strip(XML_WS) for child in element):
        raise BusinessValidationError("unexpected schema tail in " + element.tag)


def _leaf(element, allowed, required):
    _attributes(element, allowed)
    if len(element):
        raise BusinessValidationError("schema leaf cannot have children")
    if (element.text or "").strip(XML_WS):
        raise BusinessValidationError("schema leaf cannot have text")
    for name in required:
        value = element.get(name)
        if value is None or not value.strip(XML_WS):
            raise BusinessValidationError("schema leaf requires " + name)
    return element


@dataclass(frozen=True)
class ImportDecl:
    namespace: str
    location: str


@dataclass(frozen=True)
class RawType:
    uri: str
    namespace: str
    name: str
    base: str
    facets: tuple

    @property
    def expanded(self):
        return "{" + self.namespace + "}" + self.name


@dataclass(frozen=True)
class RawConcept:
    uri: str
    namespace: str
    name: str
    type_name: str

    @property
    def expanded(self):
        return "{" + self.namespace + "}" + self.name


@dataclass(frozen=True)
class SchemaFile:
    uri: str
    body: bytes
    target_namespace: str
    imports: tuple
    types: tuple
    concepts: tuple


def _parse_facet(element, seen):
    if element.tag not in tuple(X + name for name in FACETS):
        raise BusinessValidationError("unsupported facet " + element.tag)
    _leaf(element, ("value",), ())
    if element.get("value") is None:
        raise BusinessValidationError("facet requires a value attribute")
    kind = element.tag[len(X):]
    if kind in SINGLETON_FACETS:
        if kind in seen:
            raise BusinessValidationError("duplicate " + kind + " facet")
        seen.add(kind)
    return kind, element.get("value")


def _parse_restriction(element, namespace, parsed):
    _attributes(element, ("base",))
    base = element.get("base")
    if base is None or not base.strip(XML_WS):
        raise BusinessValidationError("restriction requires a base")
    _container(element)
    facets, seen = [], set()
    for child in element:
        if not isinstance(child.tag, str):
            raise BusinessValidationError("unsupported restriction child")
        facets.append(_parse_facet(child, seen))
    return _qname(base, parsed.scope_for(element)), tuple(facets)


def _parse_simple_type(element, namespace, uri, parsed):
    _attributes(element, ("name",))
    name = element.get("name")
    if not name or not is_ncname(name):
        raise BusinessValidationError("simpleType requires an NCName")
    _container(element)
    if len(element) != 1 or element[0].tag != X + "restriction":
        raise BusinessValidationError("simpleType requires one restriction")
    base, facets = _parse_restriction(element[0], namespace, parsed)
    return RawType(uri, namespace, name, base, facets)


def _parse_element(element, namespace, uri, parsed):
    attributes = _attributes(element, ("name", "type"))
    name, type_name = attributes["name"], attributes["type"]
    if not name or not is_ncname(name) or not type_name or not type_name.strip(XML_WS):
        raise BusinessValidationError("element requires NCName name and QName type")
    if len(element):
        raise BusinessValidationError("element cannot have children")
    if (element.text or "").strip(XML_WS):
        raise BusinessValidationError("element cannot have text")
    return RawConcept(uri, namespace, name, _qname(type_name, parsed.scope_for(element)))


def parse_schema_file(uri, body):
    if type(body) is not bytes or not body:
        raise BusinessValidationError("schema body must be nonempty bytes")
    parsed = parse_xml(body)
    root = parsed.root
    if root.tag != X + "schema":
        raise BusinessValidationError("expected xs:schema root")
    attributes = _attributes(root, ("targetNamespace",))
    target = attributes["targetNamespace"]
    if not target or not target.strip(XML_WS):
        raise BusinessValidationError("schema requires a targetNamespace")
    _container(root)
    imports, types, concepts = [], [], []
    for child in root:
        if not isinstance(child.tag, str):
            raise BusinessValidationError("unsupported schema child")
        if child.tag == X + "import":
            attributes = _attributes(child, ("namespace", "schemaLocation"))
            namespace = attributes["namespace"]
            location = attributes["schemaLocation"]
            if (not namespace or not namespace.strip(XML_WS)
                    or not location or not location.strip(XML_WS)):
                raise BusinessValidationError("import requires namespace and schemaLocation")
            if not is_absolute_uri(location):
                raise BusinessValidationError("import schemaLocation must be absolute")
            if len(child):
                raise BusinessValidationError("import cannot have children")
            if (child.text or "").strip(XML_WS):
                raise BusinessValidationError("import cannot have text")
            imports.append(ImportDecl(namespace, location))
        elif child.tag == X + "simpleType":
            types.append(_parse_simple_type(child, target, uri, parsed))
        elif child.tag == X + "element":
            concepts.append(_parse_element(child, target, uri, parsed))
        else:
            raise BusinessValidationError("unsupported schema child " + child.tag)
    return SchemaFile(uri, body, target, tuple(imports), tuple(types), tuple(concepts))


@dataclass(frozen=True)
class Closure:
    root_uri: str
    files: tuple

    def fingerprint(self):
        return tuple(sorted((file.uri, sha256_hex(file.body)) for file in self.files))

    def bodies(self):
        return {file.uri: file.body for file in self.files}


def load_closure(root_uri, schemas):
    """Parse the schemaRef file and follow xs:import schemaLocations offline."""
    if not isinstance(schemas, Mapping):
        raise BusinessValidationError("schemas must be a URI to bytes mapping")
    if not is_absolute_uri(root_uri):
        raise BusinessValidationError("schemaRef href must be an absolute URI")
    parsed_files = {}

    def load(uri, stack):
        if uri in parsed_files:
            return parsed_files[uri]
        if uri in stack:
            raise BusinessValidationError("schema import cycle")
        body = schemas.get(uri)
        if type(body) is not bytes or not body:
            raise BusinessValidationError("missing or empty schema file: " + str(uri))
        document = parse_schema_file(uri, body)
        stack.append(uri)
        for declaration in document.imports:
            if declaration.location in stack:
                raise BusinessValidationError("schema import cycle")
            target = load(declaration.location, stack)
            if target.target_namespace != declaration.namespace:
                raise BusinessValidationError("import targetNamespace mismatch")
        stack.pop()
        parsed_files[uri] = document
        return document

    load(root_uri, [])
    reachable = tuple(parsed_files[uri] for uri in sorted(parsed_files))
    return Closure(root_uri, reachable)


@dataclass(frozen=True)
class ConceptBasis:
    concept: str
    type_name: str
    primitive: str
    white_space: str
    minimum: object
    maximum: object
    enumeration: object


@dataclass(frozen=True)
class TypeBasis:
    root_uri: str
    files: tuple
    concepts: tuple

    def concept(self, expanded):
        for item in self.concepts:
            if item.concept == expanded:
                return item
        raise BusinessValidationError("fact concept has no global declaration: " + expanded)

    def fingerprint(self):
        return tuple(sorted((file.uri, sha256_hex(file.body)) for file in self.files))


def _type_table(files):
    table = {}
    for file in files:
        for declaration in file.types:
            if declaration.expanded in table:
                raise BusinessValidationError("duplicate type name " + declaration.expanded)
            table[declaration.expanded] = declaration
    return table


def _concept_table(files):
    table = {}
    for file in files:
        for declaration in file.concepts:
            if declaration.expanded in table:
                raise BusinessValidationError("duplicate concept name " + declaration.expanded)
            table[declaration.expanded] = declaration
    return table


def _base_domain(base, table, domains, visiting):
    if base == X + "decimal":
        return BASE_DECIMAL
    if base == X + "string":
        return BASE_STRING
    if base in visiting:
        raise BusinessValidationError("type inheritance cycle at " + base)
    if base not in table:
        raise BusinessValidationError("missing type declaration " + base)
    if base in domains:
        return domains[base]
    declaration = table[base]
    visiting.add(base)
    parent = _base_domain(declaration.base, table, domains, visiting)
    visiting.discard(base)
    domain = apply_restriction(parent, declaration.facets)
    domains[base] = domain
    return domain


def resolve_basis(closure):
    table = _type_table(closure.files)
    concepts = _concept_table(closure.files)
    domains = {}
    for name in table:
        _base_domain(name, table, domains, set())
    rows = []
    for name in concepts:
        declaration = concepts[name]
        domain = _base_domain(declaration.type_name, table, domains, set())
        rows.append(ConceptBasis(name, declaration.type_name, domain.primitive,
                                 domain.white_space, domain.minimum, domain.maximum,
                                 domain.enumeration))
    rows.sort(key=lambda item: item.concept)
    return TypeBasis(closure.root_uri, closure.files, tuple(rows))
