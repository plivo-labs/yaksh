from collections.abc import Sequence
from enum import StrEnum


class Language(StrEnum):
    """A language a caller speaks."""

    EN = "en"
    HI = "hi"
    BN = "bn"
    GU = "gu"
    KN = "kn"
    MR = "mr"
    TA = "ta"
    TE = "te"
    ES = "es"

    @property
    def label(self) -> str:
        return LANGUAGE_LABELS[self]


LANGUAGE_LABELS = {
    Language.EN: "English",
    Language.HI: "Hindi",
    Language.BN: "Bengali",
    Language.GU: "Gujarati",
    Language.KN: "Kannada",
    Language.MR: "Marathi",
    Language.TA: "Tamil",
    Language.TE: "Telugu",
    Language.ES: "Spanish",
}
INDIAN_AND_ENGLISH = frozenset(
    {
        Language.EN,
        Language.HI,
        Language.BN,
        Language.GU,
        Language.KN,
        Language.MR,
        Language.TA,
        Language.TE,
    }
)
"""Provider language lists are built from explicit sets like this one, never from every
Language, so a language added to Yaksh counts for a provider only after its documentation is
checked."""
INDIAN_ENGLISH_AND_SPANISH = INDIAN_AND_ENGLISH | {Language.ES}


class AgentLanguage(StrEnum):
    """A language an agent serves. English carries its region, as the agent's own settings
    give it."""

    EN_US = "en-US"
    EN_IN = "en-IN"
    EN_GB = "en-GB"
    EN_AU = "en-AU"
    HI = "hi"
    BN = "bn"
    GU = "gu"
    KN = "kn"
    MR = "mr"
    TA = "ta"
    TE = "te"
    ES = "es"

    @property
    def language(self) -> Language:
        return Language(self.value.split("-")[0])


def answer_language(agent: Sequence[AgentLanguage], caller: Language) -> AgentLanguage:
    """The language the agent should answer in: the caller's when the agent serves it, else
    the agent's first. English is the agent's own variant."""
    served = [language.language for language in agent]
    answer = caller if caller in served else served[0]
    return next(language for language in agent if language.language is answer)
