from dataclasses import dataclass
from decimal import Decimal
from xcollect.errors import BusinessValidationError
from xcollect.resources.names import XML_WS
from xcollect.facts.numeric import parse_nil, parse_decimals, parse_numeric_value


@dataclass(frozen=True)
class SingleElementSource:
    path: tuple
    concept: str
    raw_text: str


@dataclass(frozen=True)
class RawOrdinaryFact:
    ordinal: int
    concept: str
    context_ref: str
    unit_ref: str | None
    raw_text: str
    nil_lexical: str | None
    decimals_lexical: str | None
    source: SingleElementSource


@dataclass(frozen=True)
class OrdinaryFactCandidate:
    ordinal: int
    concept: str
    context_ref: str
    unit_ref: str | None
    kind: str
    value: str | Decimal | None
    nil: bool
    decimals: str | int | None
    source: SingleElementSource


def normalize_candidate(raw):
    nil = parse_nil(raw.nil_lexical)
    decimals = parse_decimals(raw.decimals_lexical)
    kind = "numeric" if raw.unit_ref is not None else "text"
    if kind == "text" and decimals is not None:
        raise BusinessValidationError("text cannot declare decimals")
    if nil:
        if raw.raw_text.strip(XML_WS):
            raise BusinessValidationError("nil fact contains content")
        value = None
    elif kind == "numeric":
        value = parse_numeric_value(raw.raw_text)
    else:
        value = raw.raw_text
    return OrdinaryFactCandidate(raw.ordinal, raw.concept, raw.context_ref, raw.unit_ref,
                                 kind, value, nil, decimals, raw.source)


def normalize_candidates(raw_facts):
    return tuple(normalize_candidate(raw) for raw in raw_facts)
