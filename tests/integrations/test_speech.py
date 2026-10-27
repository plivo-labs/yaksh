import asyncio
from typing import cast

import pytest
from pipecat.frames.frames import (
    Frame,
    StartFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.gladia.config import LanguageConfig
from pipecat.services.tts_service import TTSService, WebsocketTTSService
from pipecat.tests.utils import run_test
from pipecat.transcriptions.language import Language as PipecatLanguage

from yaksh.domain.errors import UnavailableError
from yaksh.domain.languages import AgentLanguage, Language
from yaksh.domain.settings import AppSettings
from yaksh.domain.speech import SttProvider
from yaksh.domain.voices import VoiceProvider, VoiceSettings
from yaksh.integrations import provider_checks
from yaksh.integrations.provider_checks import ProviderCheckError
from yaksh.integrations.speech import audio
from yaksh.integrations.speech.audio import Resample8k, speak_once
from yaksh.integrations.speech.deepgram import deepgram_language
from yaksh.integrations.speech.stt import stt_service
from yaksh.integrations.speech.tts import VENDORS as TTS_VENDORS
from yaksh.integrations.speech.tts import tts_service
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


@pytest.mark.parametrize(
    ("language", "pin"), [(Language.HI, "hi"), (Language.MR, None), (Language.ES, "es")]
)
def test_elevenlabs_speaks_with_the_voice_settings_and_pins_only_a_language_its_model_takes(
    language: Language, pin: str | None
) -> None:
    voice = VoiceSettings(provider=VoiceProvider.ELEVENLABS, id="v1", speed=0.8, stability=0.3)

    service = tts_service(AppSettings(), voice, language, "key")

    settings = cast(ElevenLabsTTSService.Settings, service._settings)
    assert (settings.voice, settings.speed, settings.stability, settings.language) == (
        "v1",
        0.8,
        0.3,
        pin,
    )
    assert settings.model == "eleven_flash_v2_5"


async def test_speech_at_another_rate_reaches_the_call_at_8_khz() -> None:
    second_at_24k = TTSAudioRawFrame(bytes(24_000 * 2), 24_000, 1)

    received, _ = await run_test(Resample8k(), frames_to_send=[second_at_24k])

    audio = [frame for frame in received if isinstance(frame, TTSAudioRawFrame)]
    assert sum(len(frame.audio) for frame in audio) == pytest.approx(16_000, abs=800)
    assert {frame.sample_rate for frame in audio} == {8000}


class StopsThenFails(FrameProcessor):
    """A provider that closes its reply and then reports an error, as Cartesia does."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSSpeakFrame):
            await self.push_frame(TTSAudioRawFrame(bytes(320), 8000, 1))
            await self.push_frame(TTSStoppedFrame())
            await self.push_error(error_msg="voice not found")
            return
        await self.push_frame(frame, direction)


class Stalls(FrameProcessor):
    """A provider that sends one chunk of its reply and then nothing."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSSpeakFrame):
            await self.push_frame(TTSAudioRawFrame(bytes(320), 8000, 1))
            return
        await self.push_frame(frame, direction)


async def test_speech_that_ends_with_an_error_fails_even_after_its_stop_frame() -> None:
    with pytest.raises(UnavailableError, match="voice not found"):
        await speak_once(cast(TTSService, StopsThenFails()), "Hello")


async def test_speech_that_stalls_fails_at_the_deadline_and_leaves_no_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audio, "SPEAK_ONCE_S", 0.5)
    before = len(asyncio.all_tasks())

    with pytest.raises(UnavailableError, match="no speech"):
        await speak_once(cast(TTSService, Stalls()), "Hello")

    assert len(asyncio.all_tasks()) == before


@pytest.mark.parametrize("provider", [VoiceProvider.ELEVENLABS, VoiceProvider.CARTESIA])
def test_one_shot_speech_does_not_reconnect_a_dropped_socket(provider: VoiceProvider) -> None:
    voice = VoiceSettings(provider=provider, id="v1")

    one_shot = cast(
        WebsocketTTSService, tts_service(AppSettings(), voice, Language.EN, "k", one_shot=True)
    )
    on_a_call = cast(WebsocketTTSService, tts_service(AppSettings(), voice, Language.EN, "k"))

    assert (one_shot._reconnect_on_error, on_a_call._reconnect_on_error) == (False, True)


def test_every_voice_provider_has_a_vendor_and_looks_voices_up_as_its_traits_say() -> None:
    assert set(TTS_VENDORS) == set(VoiceProvider)
    assert {provider: TTS_VENDORS[provider].lookup is not None for provider in VoiceProvider} == {
        provider: provider.traits.lookup for provider in VoiceProvider
    }
