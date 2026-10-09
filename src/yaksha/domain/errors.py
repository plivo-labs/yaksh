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


class ProviderCallError(Exception):
    """A call to an outside provider that failed. `status` is the provider's HTTP status when it
    answered; the message may hold the provider's reply, so it is for logs, not for clients.
    `reason` is the provider's own short explanation, which a client may see."""

    def __init__(
        self, message: str, *, status: int | None = None, reason: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason
