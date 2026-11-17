from xcollect.consumption.reconcile import reconcile_result
from xcollect.facts.numeric import decimal_to_string
from xcollect.resources.periods import period_key


def fact_to_record(fact, catalog, evidence):
    context = catalog.context(fact.context_ref)
    unit = catalog.unit(fact.unit_ref) if fact.unit_ref is not None else None
    value = decimal_to_string(fact.value) if fact.kind == "numeric" and not fact.nil else fact.value
    return {
        "ordinal": fact.ordinal, "concept": fact.concept, "kind": fact.kind,
        "value": value, "nil": fact.nil, "decimals": fact.decimals,
        "context_ref": fact.context_ref, "unit_ref": fact.unit_ref,
        "entity": {"identifier": context.identifier, "scheme": context.scheme},
        "period": list(period_key(context.period)),
        "unit": None if unit is None else {"numerator": list(unit.numerator), "denominator": list(unit.denominator)},
        "source": {"path": list(evidence.source.path), "concept": evidence.source.concept,
                   "raw_text": evidence.source.raw_text},
    }


class EvidenceExporter:
    def __init__(self, repository):
        self.repository = repository

    def export_evidence(self, result_id):
        snapshot = self.repository.load_published(result_id)
        checked = reconcile_result(snapshot)
        return {"document_id": snapshot["result"]["document_id"], "result_id": result_id,
                "digest": snapshot["result"]["digest"], "fact_count": checked.fact_count,
                "facts": [fact_to_record(f, checked.catalog, checked.evidence[f.ordinal]) for f in checked.facts]}
