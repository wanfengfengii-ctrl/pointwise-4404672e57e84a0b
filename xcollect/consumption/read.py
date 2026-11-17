from dataclasses import dataclass
from xcollect.consumption.reconcile import reconcile_result
from xcollect.consumption.select import compile_selection, select_facts


@dataclass(frozen=True)
class FactView:
    result_id: str
    ordinal: int
    concept: str
    context_ref: str
    unit_ref: str | None
    kind: str
    value: object
    nil: bool
    decimals: object
    context: object
    unit: object


def view_for(result_id, fact, catalog):
    return FactView(result_id, fact.ordinal, fact.concept, fact.context_ref, fact.unit_ref,
                    fact.kind, fact.value, fact.nil, fact.decimals, catalog.context(fact.context_ref),
                    catalog.unit(fact.unit_ref) if fact.unit_ref is not None else None)


class FactReader:
    def __init__(self, repository):
        self.repository = repository

    def read_facts(self, result_id, concept=None, period=None):
        selection = compile_selection(concept, period)
        checked = reconcile_result(self.repository.load_published(result_id))
        return tuple(view_for(result_id, fact, checked.catalog)
                     for fact in select_facts(checked.facts, checked.catalog, selection))
