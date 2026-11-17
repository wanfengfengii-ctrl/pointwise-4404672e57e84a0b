from decimal import Decimal
import re
from xcollect.errors import BusinessValidationError
from xcollect.resources.names import XML_WS

DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
INTEGER = re.compile(r"[+-]?[0-9]+")


def parse_nil(value):
    if value is None or value in ("false", "0"):
        return False
    if value in ("true", "1"):
        return True
    raise BusinessValidationError("invalid xsi:nil")


def parse_decimals(value):
    if value is None or value == "INF":
        return value
    if not isinstance(value, str) or not INTEGER.fullmatch(value):
        raise BusinessValidationError("invalid decimals")
    return int(value)


def parse_numeric_value(text):
    lexical = text.strip(XML_WS)
    if not DECIMAL.fullmatch(lexical):
        raise BusinessValidationError("invalid ordinary decimal")
    return Decimal(lexical)


def decimal_to_string(value):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise BusinessValidationError("expected finite Decimal")
    return format(value, "f")
