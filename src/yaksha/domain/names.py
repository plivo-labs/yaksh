from collections.abc import Callable

MAX_NAME_CHARS = 80
"""The longest name of a scenario or a persona."""

FORK_SUFFIX = " (fork)"


def free_name(
    name: str,
    taken: set[str],
    limit: int = MAX_NAME_CHARS,
    key: Callable[[str], str] = str.lower,
) -> str:
    """The name, or the name with " (2)", " (3)"… when it is taken, within the limit.
    `taken` holds names as `key` compares them: lower case unless told otherwise."""
    candidate, n = name[:limit], 2
    while key(candidate) in taken:
        suffix = f" ({n})"
        candidate = f"{name[: limit - len(suffix)]}{suffix}"
        n += 1
    return candidate


def fork_name(name: str, taken: set[str]) -> str:
    """The name of a copy: the original's with " (fork)", made free as free_name does."""
    return free_name(f"{name[: MAX_NAME_CHARS - len(FORK_SUFFIX)]}{FORK_SUFFIX}", taken)
