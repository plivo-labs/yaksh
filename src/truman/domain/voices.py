from typing import Protocol

from pydantic import BaseModel, ConfigDict

from truman.domain.personas import Language


class VoiceInfo(BaseModel):
    """A voice as its provider describes it. `languages` holds the provider's language codes
    the voice is verified for; the provider's model may speak more."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: str | None = None
    gender: str | None = None
    accent: str | None = None
    preview_url: str | None = None
    languages: frozenset[str] = frozenset()


class VoiceCatalog(Protocol):
    async def list_voices(self, language: Language | None = None) -> list[VoiceInfo]: ...

    async def get_voice(self, voice_id: str) -> VoiceInfo | None: ...
