"""Typed document preparation: schemaRef, offline type basis and typed facts."""
from dataclasses import dataclass
from xcollect.documents.xml import parse_xml, container
from xcollect.documents.dispatch import ensure_ordinary_document
from xcollect.errors import BusinessValidationError
from xcollect.resources.catalog import build_catalog
from xcollect.resources.names import LINK_NS, XML_WS
from xcollect.facts.extract import extract_ordinary_facts
from xcollect.typed.basis import load_closure, resolve_basis
from xcollect.typed.validate import normalize_typed_fact, validate_typed_batch

XLINK = "{http://www.w3.org/1999/xlink}"


@dataclass(frozen=True)
class TypedPreparedDocument:
    parsed: object
    catalog: object
    facts: tuple
    basis: object

    def file_bodies(self):
        return {file.uri: file.body for file in self.basis.files}


def schema_ref(parsed):
    root = parsed.root
    container(root)
    refs = [element for element in root if element.tag == "{" + LINK_NS + "}schemaRef"]
    if len(refs) != 1:
        raise BusinessValidationError("typed document requires exactly one schemaRef")
    ref = refs[0]
    if len(ref) or set(ref.attrib) - {XLINK + "type", XLINK + "href"}:
        raise BusinessValidationError("invalid schemaRef declaration")
    if (ref.text or "").strip(XML_WS):
        raise BusinessValidationError("schemaRef must be empty")
    if ref.get(XLINK + "type") != "simple":
        raise BusinessValidationError("schemaRef must be simple")
    href = ref.get(XLINK + "href")
    if not href:
        raise BusinessValidationError("schemaRef requires an href")
    return href


def ensure_typed_document(parsed):
    ensure_ordinary_document(parsed)
    return schema_ref(parsed)


def prepare_typed_document(xml_bytes, schemas):
    parsed = parse_xml(xml_bytes)
    root_uri = ensure_typed_document(parsed)
    basis = resolve_basis(load_closure(root_uri, schemas))
    catalog = build_catalog(parsed)
    facts = tuple(normalize_typed_fact(raw, basis) for raw in extract_ordinary_facts(parsed))
    facts = validate_typed_batch(facts, catalog, parsed, basis)
    return TypedPreparedDocument(parsed, catalog, facts, basis)


def typed_identity(document_id, digest, xml_bytes, schemas):
    """Bind identity from structure and the import closure only, before type evaluation."""
    from xcollect.documents.identity import make_typed_identity
    parsed = parse_xml(xml_bytes)
    root_uri = ensure_typed_document(parsed)
    closure = load_closure(root_uri, schemas)
    return make_typed_identity(document_id, digest, closure.fingerprint()), closure
