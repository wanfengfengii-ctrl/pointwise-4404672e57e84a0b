from xcollect.errors import IntegrityError
from xcollect.documents.identity import classify_submission


def publish_document(repository, identity, body, prepared):
    with repository.transaction():
        classification = classify_submission(repository.sources, identity, body)
        if classification == "retry":
            receipt = repository.lookup_receipt(identity.document_id)
            if receipt is None or receipt["result_id"] != identity.result_id:
                raise IntegrityError("source has no matching publication")
            return receipt["result_id"]
        repository.sources.insert(identity, body)
        repository.insert_result(identity, len(prepared.facts))
        repository.insert_resources(identity.result_id, prepared.catalog)
        repository.insert_facts(identity.result_id, prepared.facts)
        repository.insert_single_sources(identity.result_id, prepared.facts)
        repository.insert_receipt(identity, len(prepared.facts))
    return identity.result_id
