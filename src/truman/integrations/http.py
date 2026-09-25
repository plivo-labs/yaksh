"""What the clients for outside services share about failed requests."""


def describe(error: BaseException) -> str:
    """The error type and text, never its repr: aiohttp's repr carries the request headers,
    and with them the provider credentials."""
    text = str(error)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__
