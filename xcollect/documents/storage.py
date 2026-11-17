from dataclasses import dataclass


@dataclass(frozen=True)
class StoredSource:
    document_id: str
    digest: str
    body: bytes


class SourceStore:
    def __init__(self, connection):
        self.connection = connection

    def read(self, document_id):
        row = self.connection.execute(
            "SELECT document_id, digest, body FROM sources WHERE document_id=?", (document_id,)).fetchone()
        if row is None:
            return None
        return StoredSource(row["document_id"], row["digest"], bytes(row["body"]))

    def insert(self, identity, body):
        self.connection.execute("INSERT INTO sources(document_id,digest,body) VALUES(?,?,?)",
                                (identity.document_id, identity.digest, body))
