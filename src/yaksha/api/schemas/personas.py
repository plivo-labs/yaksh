import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from yaksha.db.models import Persona
from yaksha.domain.languages import Language
from yaksha.domain.personas import PersonaConfig
from yaksha.domain.surroundings import Surroundings
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
    surroundings: Surroundings
    sample_line: str | None
    current_version: int
    forked_from_id: uuid.UUID | None
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
            forked_from_id=persona.forked_from_id,
            created_at=persona.created_at,
            updated_at=persona.updated_at,
        )


class PersonaScenario(BaseModel):
    """A live scenario that uses the persona."""

    id: uuid.UUID
    name: str
    agent_id: uuid.UUID
    agent_name: str


class PersonaVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    persona_id: uuid.UUID
    version: int
    config: PersonaConfig
    created_at: datetime
