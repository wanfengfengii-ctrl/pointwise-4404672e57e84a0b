from dataclasses import dataclass
from xcollect.errors import BusinessValidationError
from xcollect.documents.xml import parse_xml, container, leaf_text
from xcollect.resources.names import XBRLI_NS, LINK_NS
from xcollect.resources.catalog import build_catalog
from xcollect.facts.extract import extract_ordinary_facts
from xcollect.facts.candidates import normalize_candidates
from xcollect.facts.validation import validate_batch


@dataclass(frozen=True)
class PreparedDocument:
    parsed: object
    catalog: object
    facts: tuple


def ensure_ordinary_document(parsed):
    root = parsed.root
    if root.tag != "{" + XBRLI_NS + "}xbrl":
        raise BusinessValidationError("expected ordinary xbrl root")
    container(root)
    for element in root.iter():
        if isinstance(element.tag, str) and element.tag.startswith(
                ("{http://www.xbrl.org/2013/inlineXBRL}", "{http://www.xbrl.org/2008/inlineXBRL}")):
            raise BusinessValidationError("inline XBRL is unsupported")
    for element in root:
        if element.tag in ("{" + XBRLI_NS + "}context", "{" + XBRLI_NS + "}unit"):
            if "contextRef" in element.attrib:
                raise BusinessValidationError("resource cannot be a fact")
        elif element.tag == "{" + LINK_NS + "}schemaRef":
            prefix = "{http://www.w3.org/1999/xlink}"
            if leaf_text(element, (prefix + "type", prefix + "href")).strip():
                raise BusinessValidationError("schemaRef must be empty")
            if not element.get(prefix + "href") or element.get(prefix + "type") != "simple":
                raise BusinessValidationError("invalid schemaRef declaration")
        elif "contextRef" not in element.attrib:
            raise BusinessValidationError("unsupported root child")


def prepare_ordinary_document(xml_bytes):
    parsed = parse_xml(xml_bytes)
    ensure_ordinary_document(parsed)
    catalog = build_catalog(parsed)
    facts = normalize_candidates(extract_ordinary_facts(parsed))
    return PreparedDocument(parsed, catalog, validate_batch(facts, catalog, parsed))
