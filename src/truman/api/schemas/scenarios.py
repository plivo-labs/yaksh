import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from truman.db.models import Scenario
from truman.domain.scenarios import Category, Fact, ScenarioConfig
from truman.simulation.scenarios import config_of


class ScenarioRead(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    category: Category
    description: str | None
    goal: str
    known_facts: list[Fact]
    unknown_facts: list[str]
    criteria: list[str]
    agent_data: list[Fact]
    current_version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, scenario: Scenario) -> ScenarioRead:
        return cls(
            id=scenario.id,
            agent_id=scenario.agent_id,
            name=scenario.name,
            category=scenario.category,
            description=scenario.description,
            **config_of(scenario).model_dump(),
            current_version=scenario.current_version,
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
