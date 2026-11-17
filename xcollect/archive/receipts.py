from dataclasses import dataclass


@dataclass(frozen=True)
class Receipt:
    document_id: str
    result_id: str
    digest: str
    fact_count: int


def receipt_from_row(row):
    if row is None:
        return None
    return Receipt(row["document_id"], row["result_id"], row["digest"], row["fact_count"])


class ReceiptLookup:
    def __init__(self, repository):
        self.repository = repository

    def receipt(self, document_id):
        return receipt_from_row(self.repository.lookup_receipt(document_id))
