"""Data sets that a model writes for a scenario: each one a difference the instruction names,
with the scenario's own fact names and agent data names. Nothing is saved."""

from collections.abc import AsyncGenerator
from typing import Any

import pydantic

from yaksh.domain.errors import ValidationError
from yaksh.domain.forks import ForkRequest
from yaksh.domain.language_models import JsonModel
from yaksh.domain.names import free_name
from yaksh.domain.scenarios import MAX_DATA_SET_NAME_CHARS, DataSet, normalized
from yaksh.domain.settings import Limits
from yaksh.simulation.forks import Event, ScenarioSource, fork_drafts, renamed
from yaksh.simulation.generation_prompts import FACTS, TEXT, strict_object
from yaksh.simulation.templating import render

DATA_SET_SYSTEM = render("data_set_system.j2")
DATA_SET_SCHEMA = strict_object({"name": TEXT, "known_facts": FACTS, "agent_data": FACTS})


def check_room(limits: Limits, source: ScenarioSource, request: ForkRequest) -> None:
    """Refuse a request for more data sets than the scenario has room for."""
    room = limits.max_scenario_data_sets - len(source.config.data_sets)
    if request.count > room:
        raise ValidationError(
            f"the scenario has room for {max(room, 0)} more data sets; "
            f"a scenario holds at most {limits.max_scenario_data_sets}"
        )


def data_set_drafts(
    model: JsonModel, source: ScenarioSource, request: ForkRequest
) -> AsyncGenerator[Event[DataSet]]:
    """New data sets for the scenario, each under a name that no other data set has."""
    data_sets = source.config.data_sets
    original = source.text(data_sets)
    agent_text = render(
        "agent.j2",
        name=source.agent_name,
        agent=source.agent,
        agent_data=source.config.agent_data_names,
    )
    named = {normalized(data_set.name) for data_set in data_sets}
    first = data_sets[0]

    async def write(difference: str) -> DataSet:
        user = f"{agent_text}\n\n## Scenario\n{original}\n\n## This data set\n{difference}"
        answer = await model.complete_json(
            system=DATA_SET_SYSTEM, user=user, name="data_set", schema=DATA_SET_SCHEMA
        )
        written: dict[str, Any] = answer.data
        written_name = " ".join(str(written.get("name") or "").split()) or "Data set"
        name = free_name(written_name, named, MAX_DATA_SET_NAME_CHARS, key=normalized)
        try:
            draft = DataSet.model_validate(
                {
                    "name": name,
                    "known_facts": renamed(written.get("known_facts") or [], first.known_facts),
                    "agent_data": renamed(written.get("agent_data") or [], first.agent_data),
                }
            )
        except pydantic.ValidationError as error:
            message = error.errors()[0]["msg"]
            raise ValidationError(f"the written data set is not valid: {message}") from error
        named.add(normalized(draft.name))
        return draft

    return fork_drafts(model, "scenario", original, request, write)
