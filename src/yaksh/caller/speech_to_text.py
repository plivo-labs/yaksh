"""The Deepgram language setting that hears the agent on a call. An agent can answer in any
language it serves, so the setting hears the language the agent should answer in, and as many of
the call's other languages as it can."""

from collections.abc import Sequence

from yaksh.domain.languages import AgentLanguage, Language

WIDE_SETTINGS: tuple[tuple[str, frozenset[Language]], ...] = (
    # The Hindi model also writes the English words that Hindi speakers mix in.
    ("hi", frozenset({Language.HI, Language.EN})),
    # The Hindi model writes Marathi as Hindi. The Marathi model hears both, which share a
    # script, but not English: on a real call it wrote an English agent as "Bubeet Herastaurant".
    ("mr", frozenset({Language.MR, Language.HI})),
    ("multi", frozenset({Language.EN, Language.HI, Language.ES})),
)
"""Settings that hear more than one language, with the languages of Yaksh's that each hears, in
the order a tie takes them. `multi` switches between ten languages; only these are Yaksh's."""


def deepgram_language(agent: Sequence[AgentLanguage], caller: Language) -> str:
    """The language the agent should answer in is the caller's when the agent serves it, else the
    agent's first. Of the settings that hear it, the one that hears the most of the call's
    languages wins, and on a tie the one-language model. English is the agent's own variant."""
    served = [language.language for language in agent]
    answer = caller if caller in served else served[0]
    own = next(language for language in agent if language.language is answer)
    call = {*served, caller}
    options = [(own.value, frozenset({answer})), *WIDE_SETTINGS]
    code, _ = max(
        (option for option in options if answer in option[1]),
        key=lambda option: len(option[1] & call),
    )
    return code
