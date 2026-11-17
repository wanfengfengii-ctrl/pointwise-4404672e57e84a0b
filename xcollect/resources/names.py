import re
from xcollect.errors import BusinessValidationError

XBRLI_NS = "http://www.xbrl.org/2003/instance"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
LINK_NS = "http://www.xbrl.org/2003/linkbase"
IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
XML_WS = " \t\r\n"


def _ncname(value):
    if not isinstance(value, str) or not value:
        return False
    def start(c):
        n = ord(c)
        return (c == "_" or "A" <= c <= "Z" or "a" <= c <= "z" or
                0xC0 <= n <= 0xD6 or 0xD8 <= n <= 0xF6 or 0xF8 <= n <= 0x2FF or
                0x370 <= n <= 0x37D or 0x37F <= n <= 0x1FFF or 0x200C <= n <= 0x200D or
                0x2070 <= n <= 0x218F or 0x2C00 <= n <= 0x2FEF or 0x3001 <= n <= 0xD7FF or
                0xF900 <= n <= 0xFDCF or 0xFDF0 <= n <= 0xFFFD or 0x10000 <= n <= 0xEFFFF)
    if not start(value[0]):
        return False
    return all(start(c) or c in ".-" or "0" <= c <= "9" or ord(c) == 0xB7 or
               0x300 <= ord(c) <= 0x36F or 0x203F <= ord(c) <= 0x2040 for c in value[1:])


def expanded_name(namespace, local):
    if not isinstance(namespace, str) or not namespace or "}" in namespace or not _ncname(local):
        raise BusinessValidationError("invalid expanded QName")
    return "{" + namespace + "}" + local


def validate_expanded_name(value):
    if not isinstance(value, str):
        raise BusinessValidationError("concept must be an expanded QName")
    match = re.fullmatch(r"\{([^{}]+)\}([^{}]+)", value)
    if not match:
        raise BusinessValidationError("concept must be an expanded QName")
    return expanded_name(*match.groups())


def expand_qname(value, scope):
    value = value.strip(XML_WS)
    parts = value.split(":")
    if len(parts) == 1:
        prefix, local = "", parts[0]
    elif len(parts) == 2 and _ncname(parts[0]):
        prefix, local = parts
    else:
        raise BusinessValidationError("invalid measure QName")
    uri = scope.get(prefix)
    if not uri:
        raise BusinessValidationError("unbound measure QName prefix")
    return expanded_name(uri, local)
