"""Effective value domains for the supported offline XSD subset."""
from dataclasses import dataclass
from decimal import Decimal
import re
from xcollect.errors import BusinessValidationError
from xcollect.facts.numeric import parse_numeric_value

DECIMAL = "decimal"
STRING = "string"
_WS_RUN = re.compile("[ \t\r\n]+")


def collapse(text):
    return _WS_RUN.sub(" ", text).strip(" ")


def normalize_text(text, white_space):
    return collapse(text) if white_space == "collapse" else text


def canonical_decimal(value):
    """Fixed-point, no exponent, no superfluous trailing zeros, zero written 0."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise BusinessValidationError("expected finite decimal")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0", "+0") else text


@dataclass(frozen=True)
class Domain:
    primitive: str
    white_space: str
    minimum: object = None
    maximum: object = None
    enumeration: object = None


def _decimal_literal(value):
    if not isinstance(value, str):
        raise BusinessValidationError("facet value must be text")
    return parse_numeric_value(value)


def _apply_decimal(parent, facets):
    if any(kind == "whiteSpace" for kind, _ in facets):
        raise BusinessValidationError("xs:decimal does not support whiteSpace")
    minimum, maximum, explicit_min, explicit_max = parent.minimum, parent.maximum, None, None
    literals = []
    for kind, value in facets:
        if kind == "minInclusive":
            explicit_min = _decimal_literal(value)
        elif kind == "maxInclusive":
            explicit_max = _decimal_literal(value)
        elif kind == "enumeration":
            literals.append(_decimal_literal(value))
    if explicit_min is not None:
        if parent.minimum is not None and explicit_min < parent.minimum:
            raise BusinessValidationError("explicit lower bound is looser than its parent")
        minimum = explicit_min
    if explicit_max is not None:
        if parent.maximum is not None and explicit_max > parent.maximum:
            raise BusinessValidationError("explicit upper bound is looser than its parent")
        maximum = explicit_max
    if minimum is not None and maximum is not None and minimum > maximum:
        raise BusinessValidationError("inverted decimal bounds")
    if literals:
        chosen = sorted(set(literals))
        for value in chosen:
            if minimum is not None and value < minimum:
                raise BusinessValidationError("enumeration value below the new lower bound")
            if maximum is not None and value > maximum:
                raise BusinessValidationError("enumeration value above the new upper bound")
            if parent.enumeration is not None and value not in parent.enumeration:
                raise BusinessValidationError("enumeration value outside the parent domain")
        enumeration = tuple(chosen)
    elif parent.enumeration is not None:
        enumeration = tuple(value for value in parent.enumeration
                            if (minimum is None or value >= minimum)
                            and (maximum is None or value <= maximum))
        if not enumeration:
            raise BusinessValidationError("effective decimal enumeration is empty")
    else:
        enumeration = None
    return Domain(DECIMAL, "collapse", minimum, maximum, enumeration)


def _apply_string(parent, facets):
    white_space = parent.white_space
    literals = []
    for kind, value in facets:
        if kind in ("minInclusive", "maxInclusive"):
            raise BusinessValidationError("xs:string does not support numeric bounds")
        if kind == "whiteSpace":
            if value not in ("preserve", "collapse"):
                raise BusinessValidationError("unsupported whiteSpace facet")
            if parent.white_space == "collapse" and value == "preserve":
                raise BusinessValidationError("whiteSpace cannot relax to preserve")
            white_space = value
        elif kind == "enumeration":
            literals.append(value)
    if literals:
        normalized = sorted(set(normalize_text(value, white_space) for value in literals))
        for value in normalized:
            if parent.enumeration is not None and value not in parent.enumeration:
                raise BusinessValidationError("enumeration value outside the parent domain")
        enumeration = tuple(normalized)
    elif parent.enumeration is not None:
        enumeration = tuple(value for value in parent.enumeration
                            if white_space == "preserve" or collapse(value) == value)
        if not enumeration:
            raise BusinessValidationError("effective string enumeration is empty")
    else:
        enumeration = None
    return Domain(STRING, white_space, None, None, enumeration)


def apply_restriction(parent, facets):
    if parent.primitive == DECIMAL:
        return _apply_decimal(parent, facets)
    if parent.primitive == STRING:
        return _apply_string(parent, facets)
    raise BusinessValidationError("unsupported primitive type")


BASE_DECIMAL = Domain(DECIMAL, "collapse")
BASE_STRING = Domain(STRING, "preserve")
