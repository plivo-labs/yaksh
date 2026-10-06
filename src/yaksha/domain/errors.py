class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class ValidationError(Exception):
    pass


class UnavailableError(Exception):
    """An outside service Yaksha depends on did not answer or refused the request."""
