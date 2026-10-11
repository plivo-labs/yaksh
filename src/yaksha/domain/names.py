MAX_NAME_CHARS = 80
"""The longest name of a scenario or a persona."""

FORK_SUFFIX = " (fork)"


def free_name(name: str, taken: set[str]) -> str:
    """The name, or the name with " (2)", " (3)"… when it is taken, within the name limit.
    `taken` holds lower-case names."""
    candidate, n = name, 2
    while candidate.lower() in taken:
        suffix = f" ({n})"
        candidate = f"{name[: MAX_NAME_CHARS - len(suffix)]}{suffix}"
        n += 1
    return candidate


def fork_name(name: str, taken: set[str]) -> str:
    """The name of a copy: the original's with " (fork)", made free as free_name does."""
    return free_name(f"{name[: MAX_NAME_CHARS - len(FORK_SUFFIX)]}{FORK_SUFFIX}", taken)
