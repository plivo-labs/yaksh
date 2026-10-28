import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from yaksh.domain.languages import Language
from yaksh.domain.voices import CatalogQuery, TtsModel, VoiceGender, VoiceProvider


class VoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: VoiceProvider
    provider_voice_id: str
    model: str | None
    name: str
    gender: VoiceGender | None
    accent: str | None
    languages: list[Language]
    listed_languages: list[Language]
    builtin: bool
    created_at: datetime
    updated_at: datetime


class CatalogParams(CatalogQuery):
    """The catalog's query parameters: FastAPI reads a model's fields as query parameters only
    when it is a route's one query model, so the provider is one of them."""

    provider: VoiceProvider

    def query(self) -> CatalogQuery:
        return CatalogQuery.model_validate(self.model_dump(exclude={"provider"}))


class TtsModelRead(BaseModel):
    id: str | None
    """None for a provider without a model choice."""
    label: str
    speed_min: float
    speed_max: float
    languages: list[Language]

    @classmethod
    def of(cls, model: TtsModel) -> TtsModelRead:
        low, high = model.speed
        languages = [language for language in Language if language in model.languages]
        return cls(
            id=model.id, label=model.label, speed_min=low, speed_max=high, languages=languages
        )


class TtsProviderRead(BaseModel):
    provider: VoiceProvider
    label: str
    word_timestamps: bool
    """False: a reply cut off by the agent is exact to a sentence, not to a word."""
    lookup: bool
    """The provider describes a voice by its ID."""
    models: list[TtsModelRead]
    """The first is the one a new voice gets."""

    @classmethod
    def of(cls, provider: VoiceProvider) -> TtsProviderRead:
        traits = provider.traits
        return cls(
            provider=provider,
            label=traits.label,
            word_timestamps=traits.word_timestamps,
            lookup=traits.lookup,
            models=[TtsModelRead.of(model) for model in traits.models],
        )
