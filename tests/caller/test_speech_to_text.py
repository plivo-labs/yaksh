import pytest

from yaksh.caller.speech_to_text import deepgram_language
from yaksh.domain.languages import AgentLanguage, Language


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
        ([AgentLanguage.EN_IN, AgentLanguage.HI, AgentLanguage.MR], Language.EN, "hi"),
        ([AgentLanguage.EN_IN, AgentLanguage.HI, AgentLanguage.MR], Language.MR, "mr"),
        ([AgentLanguage.EN_US], Language.MR, "en-US"),
        ([AgentLanguage.HI], Language.MR, "mr"),
        ([AgentLanguage.TA], Language.TA, "ta"),
        ([AgentLanguage.TA], Language.EN, "ta"),
        ([AgentLanguage.EN_IN], Language.TA, "en-IN"),
        ([AgentLanguage.EN_IN, AgentLanguage.HI, AgentLanguage.TA], Language.TA, "ta"),
        ([AgentLanguage.EN_IN, AgentLanguage.HI, AgentLanguage.TA], Language.EN, "hi"),
        ([AgentLanguage.TA], Language.MR, "ta"),
        ([AgentLanguage.ES], Language.ES, "es"),
        ([AgentLanguage.EN_US, AgentLanguage.ES], Language.EN, "multi"),
        ([AgentLanguage.EN_US, AgentLanguage.ES], Language.ES, "multi"),
        ([AgentLanguage.EN_US], Language.ES, "multi"),
        ([AgentLanguage.HI], Language.ES, "multi"),
    ],
)
def test_the_setting_hears_the_answer_language_and_most_of_the_others(
    agent: list[AgentLanguage], caller: Language, setting: str
) -> None:
    assert deepgram_language(agent, caller) == setting
