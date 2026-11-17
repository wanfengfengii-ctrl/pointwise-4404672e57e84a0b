from dataclasses import dataclass
from hashlib import sha256
from xcollect.errors import BusinessValidationError, DocumentConflictError, IntegrityError


@dataclass(frozen=True)
class SourceIdentity:
    document_id: str
    digest: str
    result_id: str
    mode: str = "v1"


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


def make_typed_result_id(document_id, digest, schema_digests):
    """Deterministically bind document_id, instance digest and reachable file digests."""
    name = document_id.encode("utf-8")
    pairs = sorted((uri, value) for uri, value in schema_digests)
    payload = (b"xcollect-result-typed-v1\0" + len(name).to_bytes(8, "big") + name +
               bytes.fromhex(digest) + len(pairs).to_bytes(8, "big"))
    for uri, schema_digest in pairs:
        encoded = uri.encode("utf-8")
        payload += len(encoded).to_bytes(8, "big") + encoded + bytes.fromhex(schema_digest)
    return "xt1-" + sha256(payload).hexdigest()


def make_typed_identity(document_id, digest, schema_digests):
    return SourceIdentity(document_id, digest,
                          make_typed_result_id(document_id, digest, schema_digests), "typed")


def read_source_mode(connection, document_id):
    row = connection.execute("SELECT mode FROM source_modes WHERE document_id=?",
                             (document_id,)).fetchone()
    if row is None:
        return None
    return row["mode"] if hasattr(row, "keys") else row[0]


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
    if read_source_mode(store.connection, identity.document_id) == "typed":
        raise DocumentConflictError("document_id already binds a typed result")
    return "retry"


def classify_typed_submission(connection, store, document_id, body, files):
    """Classify a typed submission whose file structure and import closure resolved.

    files maps each reachable URI to its original bytes; the stored reachable
    set must match it byte for byte, independent of mapping order.
    """
    existing = store.read(document_id)
    if existing is None:
        return "new"
    if source_digest(existing.body) != existing.digest:
        raise IntegrityError("stored source digest mismatch")
    if existing.body != body:
        raise DocumentConflictError("document_id already binds different bytes")
    mode = read_source_mode(connection, document_id)
    if mode != "typed":
        raise DocumentConflictError("document_id already binds a V1 result")
    row = connection.execute("SELECT result_id FROM receipts WHERE document_id=?",
                             (document_id,)).fetchone()
    if row is None:
        raise IntegrityError("typed source has no publication")
    result_id = row["result_id"] if hasattr(row, "keys") else row[0]
    stored = [(item["uri"], bytes(item["body"])) for item in connection.execute(
        "SELECT uri, body FROM typed_schemas WHERE result_id=? ORDER BY uri", (result_id,))]
    submitted = sorted((uri, bytes(value)) for uri, value in files.items())
    if stored != submitted:
        raise DocumentConflictError("document_id already binds different reachable files")
    expected = make_typed_result_id(document_id, source_digest(body),
                                    [(uri, source_digest(value)) for uri, value in submitted])
    if result_id != expected:
        raise IntegrityError("typed source has no matching publication")
    return "retry"
