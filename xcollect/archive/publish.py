from xcollect.errors import IntegrityError
from xcollect.documents.identity import classify_submission
from xcollect.typed.validate import validate_typed_batch


def _retry(repository, identity):
    receipt = repository.lookup_receipt(identity.document_id)
    if receipt is None or receipt["result_id"] != identity.result_id:
        raise IntegrityError("source has no matching publication")
    return receipt["result_id"]


def publish_document(repository, identity, body, prepared):
    with repository.transaction():
        classification = classify_submission(repository.sources, identity, body)
        if classification == "retry":
            return _retry(repository, identity)
        repository.sources.insert(identity, body)
        repository.insert_mode(identity)
        repository.insert_result(identity, len(prepared.facts))
        repository.insert_resources(identity.result_id, prepared.catalog)
        repository.insert_facts(identity.result_id, prepared.facts)
        repository.insert_single_sources(identity.result_id, prepared.facts)
        repository.insert_receipt(identity, len(prepared.facts))
    return identity.result_id


def publish_typed_document(repository, identity, body, prepared):
    """Atomically publish the instance, its type basis, resources, facts and receipt."""
    from xcollect.documents.identity import classify_typed_submission
    with repository.transaction():
        classification = classify_typed_submission(
            repository.connection, repository.sources, identity.document_id, body,
            prepared.file_bodies())
        if classification == "retry":
            if _retry(repository, identity) != identity.result_id:
                raise IntegrityError("publication identity mismatch")
            return identity.result_id
        # Validate the complete batch against the very basis that will be persisted.
        validate_typed_batch(prepared.facts, prepared.catalog, prepared.parsed, prepared.basis)
        repository.sources.insert(identity, body)
        repository.insert_mode(identity)
        repository.insert_result(identity, len(prepared.facts))
        repository.insert_type_basis(identity.result_id, prepared.basis)
        repository.insert_resources(identity.result_id, prepared.catalog)
        repository.insert_facts(identity.result_id, prepared.facts)
        repository.insert_single_sources(identity.result_id, prepared.facts)
        repository.insert_receipt(identity, len(prepared.facts))
    return identity.result_id
