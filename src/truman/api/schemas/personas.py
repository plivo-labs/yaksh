import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from truman.db.models import Persona
from truman.domain.languages import Language
from truman.domain.personas import PersonaConfig
from truman.domain.voices import VoiceGender, VoiceSettings
from truman.simulation.personas import config_of


class PersonaRead(BaseModel):
    id: uuid.UUID
    name: str
    builtin_key: str | None
    prompt: str
    language: Language
    voice: VoiceSettings
    voice_gender: VoiceGender | None
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
