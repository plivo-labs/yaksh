import pytest

from yaksha.caller.speech_to_text import deepgram_language
from yaksha.domain.languages import AgentLanguage, Language


@pytest.mark.parametrize(
    ("agent", "caller", "setting"),
    [
        ([AgentLanguage.EN_US], Language.EN, "en-US"),
        ([AgentLanguage.EN_IN], Language.EN, "en-IN"),
        ([AgentLanguage.EN_GB, AgentLanguage.EN_US], Language.EN, "en-GB"),
        ([AgentLanguage.EN_IN], Language.HI, "hi"),
        ([AgentLanguage.HI], Language.EN, "hi"),
        ([AgentLanguage.HI], Language.HI, "hi"),
        ([AgentLanguage.EN_IN, AgentLanguage.HI], Language.EN, "hi"),
        ([AgentLanguage.HI, AgentLanguage.EN_IN], Language.HI, "hi"),
    ],
)
def test_the_setting_hears_the_answer_language_and_most_of_the_others(
    agent: list[AgentLanguage], caller: Language, setting: str
) -> None:
    assert deepgram_language(agent, caller) == setting
