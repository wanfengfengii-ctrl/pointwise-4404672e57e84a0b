from dataclasses import dataclass
from hashlib import sha256
from xcollect.errors import BusinessValidationError, DocumentConflictError, IntegrityError


@dataclass(frozen=True)
class SourceIdentity:
    document_id: str
    digest: str
    result_id: str


def validate_document_input(document_id, xml_bytes):
    if not isinstance(document_id, str) or not document_id.strip():
        raise BusinessValidationError("document_id must be a nonblank string")
    try:
        document_id.encode("utf-8")
    except UnicodeError as exc:
        raise BusinessValidationError("document_id must be valid Unicode") from exc
    if type(xml_bytes) is not bytes or not xml_bytes:
        raise BusinessValidationError("xml_bytes must be nonempty bytes")


def source_digest(body):
    return sha256(body).hexdigest()


def make_result_id(document_id, digest):
    name = document_id.encode("utf-8")
    payload = b"xcollect-result-v1\0" + len(name).to_bytes(8, "big") + name + bytes.fromhex(digest)
    return "xr1-" + sha256(payload).hexdigest()


def classify_submission(store, identity, body):
    existing = store.read(identity.document_id)
    if existing is None:
        return "new"
    if source_digest(existing.body) != existing.digest:
        raise IntegrityError("stored source digest mismatch")
    if existing.body != body:
        raise DocumentConflictError("document_id already binds different bytes")
    if existing.digest != identity.digest:
        raise IntegrityError("source identity mismatch")
    return "retry"
