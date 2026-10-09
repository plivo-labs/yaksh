"""Imports an agent from a Retell workspace: lists its voice agents, and reads one into a draft
agent. The API key is used for these calls only, except in the start request of an agent that
calls out."""

import asyncio
import json
import re
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from yaksha.domain.agent_import import (
    Pair,
    ProviderDraft,
    RetellAccountApi,
    RetellAgent,
    RetellAgentPage,
    RetellAgentSearch,
    StartRequestDraft,
)
from yaksha.domain.agents import Direction
from yaksha.domain.errors import ValidationError
from yaksha.domain.triggers import TriggerMethod
from yaksha.simulation.agent_import import (
    language,
    provider_errors,
    pruned,
    scenario_variables,
    text,
    without,
)
from yaksha.simulation.curl_import import NUMBER, check

NUMBER_FIELD = "to_number"
CREDENTIALS = frozenset({"headers", "cal_api_key", "secret"})
"""Where a tool keeps what authenticates its requests."""
# ponytail: Retell cannot search by name, so a search reads up to 10 pages of 100 agents for
# each page it shows; use Retell's search if it adds one.
SEARCHED_PAGES = 10
FLOW = "conversation-flow"
LLM = "retell-llm"
VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][\w/]*)\s*\}\}")
SYSTEM = frozenset(
    {
        "current_agent_state",
        "previous_agent_state",
        "current_node",
        "previous_node",
        "current_time_ms",
        "current_time",
        "current_hour",
        "current_calendar",
        "system_timezone",
        "session_type",
        "session_duration",
        "session_duration_ms",
        "call_id",
        "call_type",
        "direction",
        "user_number",
        "agent_number",
        "call_summary",
        "call_successful",
        "call_status",
        "user_sentiment",
        "disconnection_reason",
    }
)
"""Retell's own variables, which it fills during or after the call."""
ZONED = re.compile(r"^current_(?:time|hour|calendar)_(?:[A-Z]{2,5}|[A-Za-z_]+/[\w/+-]+)$")
"""A time variable in a named zone, such as current_time_Australia/Sydney or current_hour_UTC."""
NOT_BEHAVIOR = frozenset(
    {
        "display_position",
        "begin_tag_display_position",
        "last_modification_timestamp",
        "is_published",
        "version",
        "conversation_flow_id",
        "llm_id",
    }
)


async def list_agents(api: RetellAccountApi, search: RetellAgentSearch) -> RetellAgentPage:
    name = (search.name or "").strip().lower()
    cursor, items = search.cursor, []
    with retell_errors():
        numbers = await api.phone_numbers()
        for _ in range(SEARCHED_PAGES):
            page = await api.list_agents(cursor=cursor)
            items += [
                agent
                for agent in page.get("items") or []
                if name in str(agent.get("agent_name") or "").lower()
            ]
            cursor = page.get("pagination_key") if page.get("has_more") else None
            if items or cursor is None or not name:
                break
    return RetellAgentPage(
        items=[
            RetellAgent(
                id=str(agent.get("agent_id")),
                name=str(agent.get("agent_name") or "Untitled agent"),
                updated_at=moment(agent.get("user_modified_timestamp")),
                numbers=[number for number, _ in own_numbers(numbers, str(agent.get("agent_id")))],
            )
            for agent in items
        ],
        next_cursor=cursor,
    )


async def import_agent(api: RetellAccountApi, agent_id: str) -> ProviderDraft:
    with retell_errors():
        versions, numbers = await asyncio.gather(api.agent_versions(agent_id), api.phone_numbers())
        routed = own_numbers(numbers, agent_id)
        version = resolve(routed[0][1] if routed else None, versions)
        agent = await api.get_agent(agent_id, version)
        engine = await response_engine(api, agent.get("response_engine") or {})
    own = [number for number, pinned in routed if resolve(pinned, versions) == version]
    draft = ProviderDraft(
        name=text(agent.get("agent_name")),
        external_id=agent_id,
        language=language(agent.get("language")),
        config=json.dumps(behavior(agent, engine), indent=2, ensure_ascii=False),
        direction=Direction.INBOUND,
        agent_numbers=own,
        start_request=None,
        agent_speaks_first=engine.get("start_speaker", "agent") == "agent",
    )
    if own:
        return draft
    callers = outbound_numbers(numbers, agent_id)
    if not callers:
        raise ValidationError(
            "the agent has no number, and the workspace has no number to call from; add a "
            "number in Retell first"
        )
    request = start_request(api, agent_id, version, callers[0], variables(engine))
    return draft.model_copy(update={"direction": Direction.OUTBOUND, "start_request": request})


def resolve(reference: Any, versions: list[dict[str, Any]]) -> int:
    """The version a number calls: a pinned number, the newest for latest, and the newest
    published otherwise."""
    # ponytail: a tag such as prod resolves as the newest published version; read the tag's
    # assignment if numbers pinned to tags need testing.
    if isinstance(reference, int):
        return reference
    if reference == "latest":
        return max(v["version"] for v in versions if isinstance(v.get("version"), int))
    return current(versions)


def current(versions: list[dict[str, Any]]) -> int:
    """The newest published version, which numbers and calls use; the newest draft when none is
    published."""
    published = [v["version"] for v in versions if v.get("is_published") and "version" in v]
    every = [v["version"] for v in versions if isinstance(v.get("version"), int)]
    if not every:
        raise ValidationError("Retell lists no version of this agent")
    return max(published or every)


async def response_engine(api: RetellAccountApi, engine: dict[str, Any]) -> dict[str, Any]:
    """The prompt and tools of the agent's LLM or conversation flow. A custom LLM runs on the
    customer's own server, so Retell has nothing to read."""
    version = engine.get("version")
    if engine.get("type") == FLOW and engine.get("conversation_flow_id"):
        return await api.get_conversation_flow(str(engine["conversation_flow_id"]), version)
    if engine.get("type") == LLM and engine.get("llm_id"):
        return await api.get_retell_llm(str(engine["llm_id"]), version)
    return {}


def own_numbers(numbers: list[dict[str, Any]], agent_id: str) -> list[tuple[str, Any]]:
    """The numbers whose calls all reach the agent, with the version each calls. A number that
    splits its calls among agents is left out: a test through it could reach another agent."""
    found = []
    for number in numbers:
        weighted = number.get("inbound_agents") or []
        if weighted:
            only = len(weighted) == 1 and weighted[0].get("agent_id") == agent_id
            pinned = weighted[0].get("agent_version") if only else None
        else:
            only = number.get("inbound_agent_id") == agent_id
            pinned = number.get("inbound_agent_version")
        if only and number.get("phone_number"):
            found.append((str(number["phone_number"]), pinned))
    return found


def outbound_numbers(numbers: list[dict[str, Any]], agent_id: str) -> list[dict[str, Any]]:
    """The numbers bound to the agent for calling out first, then the others: a call names its
    agent, so any number of the workspace can place it."""
    own = [n for n in numbers if agent_id in bound(n, "outbound_agents", "outbound_agent_id")]
    return [*own, *(number for number in numbers if number not in own)]


def bound(number: dict[str, Any], weighted: str, single: str) -> set[str]:
    agents = {str(agent.get("agent_id")) for agent in number.get(weighted) or []}
    return agents | ({str(number[single])} if number.get(single) else set())


def behavior(agent: dict[str, Any], engine: dict[str, Any]) -> dict[str, Any]:
    """The agent as the judges read it: its prompts, nodes and tools, and how Retell grades its
    calls, without voice, audio and account settings."""
    return pruned(
        without(
            {
                "name": agent.get("agent_name"),
                "language": agent.get("language"),
                "engine": without(engine, NOT_BEHAVIOR),
                "post_call_analysis": agent.get("post_call_analysis_data"),
            },
            CREDENTIALS,
        )
    )


def variables(engine: dict[str, Any]) -> list[str]:
    """The variables the prompts and tools use that a call must give, each once: without
    Retell's own, and without those the agent extracts or a tool sets during the call."""
    found = dict.fromkeys(VARIABLE.findall(json.dumps(engine)))
    made = set_during_call(engine)
    return [
        name for name in found if name not in SYSTEM and not ZONED.match(name) and name not in made
    ]


def set_during_call(value: Any) -> set[str]:
    """The names an extraction tool or node fills, and the names a tool's response sets."""
    if isinstance(value, list):
        return set().union(*(set_during_call(item) for item in value))
    if not isinstance(value, dict):
        return set()
    names = {
        str(item["name"])
        for item in value.get("variables") or []
        if isinstance(item, dict) and item.get("name")
    }
    names |= set(value.get("response_variables") or {})
    return names.union(*(set_during_call(item) for item in value.values()))


def start_request(
    api: RetellAccountApi, agent_id: str, version: int, caller: dict[str, Any], names: list[str]
) -> StartRequestDraft:
    """Retell's outbound call from the workspace's number to Yaksha with the imported version of
    this agent, and the agent's variables for each scenario to fill."""
    body: dict[str, Any] = {
        "from_number": caller.get("phone_number"),
        NUMBER_FIELD: NUMBER,
        "override_agent_id": agent_id,
        "override_agent_version": version,
    }
    values = scenario_variables(names)
    if values:
        body["retell_llm_dynamic_variables"] = values
    request = StartRequestDraft(
        method=TriggerMethod.POST,
        url=f"{api.base_url}/v2/create-phone-call",
        headers=[Pair(name="Authorization", value=f"Bearer {api.api_key}")],
        query=[],
        body=body,
        number_field=NUMBER_FIELD,
    )
    check(request)
    return request


def moment(value: Any) -> datetime | None:
    """Retell's times are Unix milliseconds."""
    return datetime.fromtimestamp(value / 1000, UTC) if isinstance(value, int | float) else None


def retell_errors() -> AbstractContextManager[None]:
    return provider_errors(
        "Retell",
        refused="Retell refused the API key; copy it again from the API keys page of Retell",
        forbidden="the API key may not read agents; use a key of the workspace",
    )
