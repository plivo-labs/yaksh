import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from truman.domain.languages import Language
from truman.domain.voices import VoiceGender, VoiceProvider


class VoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: VoiceProvider
    provider_voice_id: str
    name: str
    gender: VoiceGender | None
    accent: str | None
    languages: list[Language]
    listed_languages: list[Language]
    builtin: bool
    created_at: datetime
    updated_at: datetime
