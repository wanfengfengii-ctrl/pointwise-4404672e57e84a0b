import base64
from hashlib import sha256
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


def type_basis_record(basis):
    from xcollect.typed.records import basis_record
    return {"root_uri": basis.root_uri,
            "schemas": [{"uri": file.uri,
                         "sha256": sha256(file.body).hexdigest(),
                         "body_base64": base64.b64encode(file.body).decode("ascii")}
                        for file in basis.files],
            "concepts": [basis_record(item) for item in basis.concepts]}


class EvidenceExporter:
    def __init__(self, repository):
        self.repository = repository

    def export_evidence(self, result_id):
        snapshot = self.repository.load_published(result_id)
        checked = reconcile_result(snapshot)
        record = {"document_id": snapshot["result"]["document_id"], "result_id": result_id,
                  "digest": snapshot["result"]["digest"], "fact_count": checked.fact_count,
                  "facts": [fact_to_record(f, checked.catalog, checked.evidence[f.ordinal])
                            for f in checked.facts]}
        if checked.mode == "typed":
            record["type_basis"] = type_basis_record(checked.basis)
        return record
