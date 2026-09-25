def describe_exception(error: BaseException) -> str:
    """The exception's type and str(), never its repr(): aiohttp's repr() carries the request
    headers, and with them the provider credentials. The text itself is not checked for
    secrets, so no caller may put one into an exception message."""
    text = str(error)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__
