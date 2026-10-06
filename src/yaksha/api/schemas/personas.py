import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from yaksha.db.models import Persona
from yaksha.domain.background_noise import BackgroundNoise
from yaksha.domain.languages import Language
from yaksha.domain.personas import PersonaConfig
from yaksha.domain.voices import VoiceGender, VoiceSettings
from yaksha.simulation.personas import config_of


class PersonaRead(BaseModel):
    id: uuid.UUID
    name: str
    builtin_key: str | None
    prompt: str
    language: Language
    voice: VoiceSettings
    voice_gender: VoiceGender | None
    background_noise: BackgroundNoise
    current_version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, persona: Persona) -> PersonaRead:
        return cls(
            id=persona.id,
            name=persona.name,
            builtin_key=persona.builtin_key,
            **config_of(persona).model_dump(),
            current_version=persona.current_version,
            created_at=persona.created_at,
            updated_at=persona.updated_at,
        )


class PersonaVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    persona_id: uuid.UUID
    version: int
    config: PersonaConfig
    created_at: datetime
