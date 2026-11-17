from dataclasses import dataclass
from xcollect.errors import BusinessValidationError
from xcollect.resources.names import validate_expanded_name
from xcollect.resources.periods import Period, period_key


@dataclass(frozen=True)
class FactSelection:
    concept: str | None
    period: tuple | None


def compile_selection(concept=None, period=None):
    try:
        if concept is not None:
            validate_expanded_name(concept)
        if period is not None:
            if type(period) is not tuple or len(period) not in (2, 3):
                raise ValueError("period must be a typed tuple")
            parsed = Period(*period)
            if period_key(parsed) != period:
                raise ValueError("noncanonical period")
    except (BusinessValidationError, TypeError) as exc:
        raise ValueError("invalid fact selection") from exc
    return FactSelection(concept, period)


def select_facts(facts, catalog, selection):
    return tuple(fact for fact in facts
                 if (selection.concept is None or fact.concept == selection.concept)
                 and (selection.period is None or
                      period_key(catalog.context(fact.context_ref).period) == selection.period))
