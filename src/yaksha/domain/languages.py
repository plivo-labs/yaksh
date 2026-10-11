from enum import StrEnum


class Language(StrEnum):
    """A language a caller speaks."""

    EN = "en"
    HI = "hi"


class AgentLanguage(StrEnum):
    """A language an agent serves. English carries its region, as the agent's own settings
    give it."""

    EN_US = "en-US"
    EN_IN = "en-IN"
    EN_GB = "en-GB"
    EN_AU = "en-AU"
    HI = "hi"

    @property
    def language(self) -> Language:
        return Language(self.value.split("-")[0])
