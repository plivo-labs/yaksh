import pytest
from pipecat.frames.frames import Frame, StartFrame, TranscriptionFrame, VADUserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.gladia.config import LanguageConfig
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.languages import AgentLanguage, Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.speech import SttProvider
from yaksh.integrations import provider_checks
from yaksh.integrations.provider_checks import ProviderCheckError
from yaksh.integrations.speech import deepgram_language, stt_service
from yaksh.settings.service import check_clip


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


@pytest.mark.parametrize(
    ("provider", "setting", "value"),
    [
        (SttProvider.SARVAM, "language", "hi-IN"),
        (SttProvider.ASSEMBLYAI, "language_codes", [PipecatLanguage.HI]),
        (SttProvider.SONIOX, "language_hints", [PipecatLanguage.HI]),
        (SttProvider.GLADIA, "language_config", LanguageConfig(languages=["hi"])),
    ],
)
def test_each_provider_hears_the_language_through_the_setting_it_sends(
    provider: SttProvider, setting: str, value: object
) -> None:
    service = stt_service(AppSettings(), provider, "key", "hi")

    assert getattr(service._settings, setting) == value


class FinalOnStop(FrameProcessor):
    """A provider that sends its final transcript only when the voice detector ends the turn,
    as Soniox does under Pipecat's turn detection."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            await self.push_frame(TranscriptionFrame("Thanks.", "", "now"))
        await self.push_frame(frame, direction)


class Refuses(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            await self.push_error(error_msg="401 Unauthorized")
        await self.push_frame(frame, direction)


async def test_the_check_passes_on_a_transcript_sent_after_the_turn_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_checks, "stt_service", lambda *_args: FinalOnStop())

    await provider_checks.check_stt(AppSettings(), SttProvider.SONIOX, "key", check_clip())


async def test_the_check_fails_when_the_provider_refuses_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_checks, "stt_service", lambda *_args: Refuses())

    with pytest.raises(ProviderCheckError, match="Soniox: 401 Unauthorized"):
        await provider_checks.check_stt(AppSettings(), SttProvider.SONIOX, "key", check_clip())
