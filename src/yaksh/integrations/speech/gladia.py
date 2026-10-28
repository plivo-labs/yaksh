"""Gladia speech-to-text: live v2 with solaria-1. The language goes in `language_config`;
Pipecat's `language` setting is not sent. Gladia's own voice detection stays off, so Yaksh's
decides the turns. Gladia keeps its own endpointing, so it sends a final at each short pause
while the agent speaks: `SttTraits.words_while_speaking` follows from that."""

from pipecat.services.gladia.config import LanguageConfig
from pipecat.services.gladia.stt import GladiaSTTService

from yaksh.domain.settings import AppSettings
from yaksh.integrations.speech.audio import SAMPLE_RATE
from yaksh.integrations.speech.vendor import SttVendor


def stt(settings: AppSettings, key: str, language: str) -> GladiaSTTService:
    return GladiaSTTService(
        api_key=key,
        url=settings.gladia.url,
        sample_rate=SAMPLE_RATE,
        settings=GladiaSTTService.Settings(
            model=settings.gladia.model, language_config=LanguageConfig(languages=[language])
        ),
    )


STT = SttVendor(model=lambda settings: settings.gladia.model, service=stt)
