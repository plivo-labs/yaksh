class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class ValidationError(Exception):
    pass


class UnavailableError(Exception):
    """An outside service Yaksha depends on did not answer or refused the request."""


class UnrecognizedFileError(ValidationError):
    """Valid JSON that is not an agent file Yaksha reads; it can still be the agent's config."""
