import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from yaksh.db.models import Scenario, ScenarioGeneration
from yaksh.domain.generation import GenerationMode, GenerationStatus
from yaksh.domain.scenarios import Category, DataSet, Interruption, ScenarioConfig
from yaksh.domain.settings import CallerModel
from yaksh.simulation.scenarios import config_of


class ScenarioRead(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    persona_id: uuid.UUID
    name: str
    category: Category
    description: str | None
    generation_id: uuid.UUID | None
    instructions: str
    unknown_facts: list[str]
    criteria: list[str]
    data_sets: list[DataSet]
    first_words: str | None
    caller: CallerModel | None
    interruptions: list[Interruption]
    current_version: int
    forked_from_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, scenario: Scenario) -> ScenarioRead:
        return cls(
            id=scenario.id,
            agent_id=scenario.agent_id,
            persona_id=scenario.persona_id,
            name=scenario.name,
            category=scenario.category,
            description=scenario.description,
            generation_id=scenario.generation_id,
            **config_of(scenario).model_dump(),
            current_version=scenario.current_version,
            forked_from_id=scenario.forked_from_id,
            created_at=scenario.created_at,
            updated_at=scenario.updated_at,
        )


class ScenarioVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scenario_id: uuid.UUID
    version: int
    config: ScenarioConfig
    created_at: datetime


class GenerationRead(BaseModel):
    id: uuid.UUID
    mode: GenerationMode
    status: GenerationStatus
    created_at: datetime
    count: int
    """How many scenarios it was asked to write."""
    scenarios: int
    """How many of its scenarios are not deleted."""
    error: str | None

    @classmethod
    def of(cls, generation: ScenarioGeneration, scenarios: int) -> GenerationRead:
        return cls(
            id=generation.id,
            mode=generation.mode,
            status=generation.status,
            created_at=generation.created_at,
            count=generation.count,
            scenarios=scenarios,
            error=generation.error,
        )
