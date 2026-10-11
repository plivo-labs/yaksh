"""Imports an agent from an ElevenLabs workspace: lists the workspace's agents, and reads one into
a draft agent. The API key is used for these calls only, except in the start request of an agent
that calls out."""

import asyncio
import json
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from yaksha.domain.agent_import import (
    ElevenLabsAccountApi,
    ElevenLabsAgent,
    ElevenLabsAgentPage,
    ElevenLabsAgentSearch,
    Pair,
    ProviderDraft,
    StartRequestDraft,
)
from yaksha.domain.agents import Direction
from yaksha.domain.errors import ValidationError
from yaksha.domain.triggers import TriggerMethod
from yaksha.simulation.agent_import import (
    agent_languages,
    provider_errors,
    pruned,
    scenario_variables,
    text,
    unless_missing,
    without,
)
from yaksha.simulation.curl_import import NUMBER, check

OUTBOUND_ROUTES = {"twilio": "twilio", "sip_trunk": "sip-trunk", "exotel": "exotel"}
"""The outbound call endpoint of each kind of number, by the number's provider."""
NUMBER_FIELD = "to_number"
CREDENTIALS = frozenset({"request_headers", "auth_connection"})
SYSTEM_VARIABLE = "system__"
"""ElevenLabs fills the dynamic variables with this prefix itself."""


async def list_agents(
    api: ElevenLabsAccountApi, search: ElevenLabsAgentSearch
) -> ElevenLabsAgentPage:
    with elevenlabs_errors():
        page = await api.list_agents(name=search.name, cursor=search.cursor)
    return ElevenLabsAgentPage(
        items=[
            ElevenLabsAgent(
                id=str(agent.get("agent_id")),
                name=str(agent.get("name") or "Untitled agent"),
                last_call_at=moment(agent.get("last_call_time_unix_secs")),
            )
            for agent in page.get("agents") or []
        ],
        next_cursor=page.get("next_cursor") if page.get("has_more") else None,
    )


async def import_agent(api: ElevenLabsAccountApi, agent_id: str) -> ProviderDraft:
    with elevenlabs_errors():
        agent = await api.get_agent(agent_id)
        found = await asyncio.gather(*(unless_missing(api.get_tool(id)) for id in tool_ids(agent)))
    tools = [tool for tool in found if tool is not None]
    numbers = [
        str(number.get("phone_number"))
        for number in agent.get("phone_numbers") or []
        if number.get("supports_inbound", True) and number.get("phone_number")
    ]
    languages, language_note = agent_languages(
        [settings(agent).get("language"), *language_presets(agent)]
    )
    draft = ProviderDraft(
        name=text(agent.get("name")),
        external_id=agent_id,
        languages=languages,
        language_note=language_note,
        config=json.dumps(behavior(agent, tools), indent=2, ensure_ascii=False),
        direction=Direction.INBOUND,
        agent_numbers=numbers,
        start_request=None,
        agent_speaks_first=bool(settings(agent).get("first_message")),
    )
    if numbers:
        return draft
    with elevenlabs_errors():
        callers = [
            number
            for number in await api.outbound_numbers()
            if number.get("provider") in OUTBOUND_ROUTES
        ]
    if not callers:
        raise ValidationError(
            "the agent has no number, and the workspace has no number that places calls; give "
            "the agent a number in ElevenLabs first"
        )
    request = start_request(api, agent_id, callers[0], settings(agent))
    return draft.model_copy(update={"direction": Direction.OUTBOUND, "start_request": request})


def settings(agent: dict[str, Any]) -> dict[str, Any]:
    return (agent.get("conversation_config") or {}).get("agent") or {}


def language_presets(agent: dict[str, Any]) -> dict[str, Any]:
    """The agent's other languages, by code, each with what it changes for that language."""
    presets = (agent.get("conversation_config") or {}).get("language_presets")
    return presets if isinstance(presets, dict) else {}


def tool_ids(agent: dict[str, Any]) -> list[str]:
    """The agent's own tools, then the tools its workflow nodes add or override, each once."""
    nodes = list(((agent.get("workflow") or {}).get("nodes") or {}).values())
    ids = [
        *(id for owner in (agent, *nodes) for id in prompt_of(owner).get("tool_ids") or []),
        *(id for node in nodes for id in node.get("additional_tool_ids") or []),
        *(tool.get("tool_id") for node in nodes for tool in node.get("tools") or []),
    ]
    return list(dict.fromkeys(str(id) for id in ids if id))


def prompt_of(owner: dict[str, Any]) -> dict[str, Any]:
    """The prompt of an agent, or the prompt a workflow node overrides."""
    return settings(owner).get("prompt") or {}


def behavior(agent: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """The agent as the judges read it: its prompt, first message, what each other language
    changes in them, workflow and tools, and how ElevenLabs grades its calls, without voice,
    widget and account settings."""
    platform = agent.get("platform_settings") or {}
    workflow = agent.get("workflow") or {}
    nodes = {
        name: {key: value for key, value in node.items() if key != "position"}
        for name, node in (workflow.get("nodes") or {}).items()
    }
    return pruned(
        without(
            {
                "name": agent.get("name"),
                "agent": settings(agent),
                "language_presets": {
                    code: (preset.get("overrides") or {}).get("agent")
                    for code, preset in language_presets(agent).items()
                    if isinstance(preset, dict)
                },
                "workflow": {**workflow, "nodes": nodes},
                "tools": [tool.get("tool_config") or tool for tool in tools],
                "evaluation": platform.get("evaluation"),
                "data_collection": platform.get("data_collection"),
            },
            CREDENTIALS,
        )
    )


def start_request(
    api: ElevenLabsAccountApi, agent_id: str, caller: dict[str, Any], agent: dict[str, Any]
) -> StartRequestDraft:
    """ElevenLabs' outbound call from the agent's caller number to Yaksha, with the agent's
    dynamic variables for each scenario to fill."""
    placeholders = (agent.get("dynamic_variables") or {}).get("dynamic_variable_placeholders") or {}
    headers = [Pair(name="xi-api-key", value=api.api_key)]
    variables = scenario_variables(
        name for name in placeholders if not name.startswith(SYSTEM_VARIABLE)
    )
    body: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_phone_number_id": caller.get("phone_number_id"),
        NUMBER_FIELD: NUMBER,
    }
    if variables:
        body["conversation_initiation_client_data"] = {"dynamic_variables": variables}
    request = StartRequestDraft(
        method=TriggerMethod.POST,
        url=f"{api.base_url}/v1/convai/{OUTBOUND_ROUTES[caller['provider']]}/outbound-call",
        headers=headers,
        query=[],
        body=body,
        number_field=NUMBER_FIELD,
    )
    check(request)
    return request


def moment(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int | float) else None


def elevenlabs_errors() -> AbstractContextManager[None]:
    return provider_errors(
        "ElevenLabs",
        refused="ElevenLabs refused the API key; a key from an EU, India or Singapore workspace "
        "works only with that workspace chosen",
        forbidden="the API key may not read agents; give it ElevenAgents access",
    )
