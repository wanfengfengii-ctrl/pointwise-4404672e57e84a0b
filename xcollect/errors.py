class BusinessValidationError(ValueError):
    """The submitted document is outside the supported ordinary XBRL subset."""


class DocumentConflictError(ValueError):
    """A successful document identifier already binds different source bytes."""


class NotFound(LookupError):
    """The requested fixed result does not exist."""


class IntegrityError(RuntimeError):
    """A persisted result cannot be reconciled."""
