"""Imports an assistant from a Vapi organization: lists its assistants, and reads one into a
draft agent. The API key is used for these calls only, except in the start request of an
assistant that calls out."""

import asyncio
import json
import re
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from yaksha.domain.agent_import import (
    VAPI_PAGE_SIZE,
    Pair,
    ProviderDraft,
    StartRequestDraft,
    VapiAccountApi,
    VapiAssistant,
    VapiAssistantPage,
    VapiAssistantSearch,
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

NUMBER_FIELD = "customer.number"
CREDENTIALS = frozenset({"headers", "secret"})
"""Where a tool or a server URL keeps what authenticates its requests."""
# ponytail: Vapi cannot search by name, so a search reads up to 10 pages of 100 assistants for
# each page it shows; use Vapi's search if it adds one.
SEARCHED_PAGES = 10
VARIABLE = re.compile(r"\{\{\s*((?:customer\.)?[A-Za-z_]\w*)\s*(?:\||\}\})")
"""A {{name}}, {{customer.name}} or {{name | filter}} in a prompt or message; other dotted
names, such as call.id, are Vapi's own."""
CUSTOMER = "customer."
CUSTOMER_FIELDS = frozenset({"name", "email", "externalId"})
"""The customer fields a call sets that a prompt can use; Vapi fills customer.number itself."""
BUILT_IN = frozenset({"now", "date", "time", "month", "day", "year"})
"""The variables Vapi fills from the time of the call."""
FIRST_MESSAGE_WAITS = "assistant-waits-for-user"
FIRST_MESSAGE_GENERATED = "assistant-speaks-first-with-model-generated-message"
FREE_NUMBER = "vapi"
"""Vapi's free numbers take calls but cannot place them."""


async def list_assistants(api: VapiAccountApi, search: VapiAssistantSearch) -> VapiAssistantPage:
    name = (search.name or "").strip().lower()
    cursor, items = search.cursor, []
    with vapi_errors():
        numbers = await api.phone_numbers()
        for _ in range(SEARCHED_PAGES):
            page = await api.list_assistants(created_before=cursor)
            items += [
                assistant for assistant in page if name in str(assistant.get("name") or "").lower()
            ]
            cursor = moment(page[-1].get("createdAt")) if len(page) == VAPI_PAGE_SIZE else None
            if items or cursor is None or not name:
                break
    return VapiAssistantPage(
        items=[
            VapiAssistant(
                id=str(assistant.get("id")),
                name=str(assistant.get("name") or "Untitled assistant"),
                updated_at=moment(assistant.get("updatedAt")),
                numbers=numbers_of(numbers, str(assistant.get("id"))),
            )
            for assistant in items
        ],
        next_cursor=cursor,
    )


async def import_assistant(api: VapiAccountApi, assistant_id: str) -> ProviderDraft:
    with vapi_errors():
        assistant, numbers = await asyncio.gather(
            api.get_assistant(assistant_id), api.phone_numbers()
        )
        ids = model(assistant).get("toolIds") or []
        found = await asyncio.gather(*(unless_missing(api.get_tool(str(id))) for id in ids))
    tools = [tool for tool in found if tool is not None]
    own = numbers_of(numbers, assistant_id)
    languages, language_note = agent_languages(
        [(assistant.get("transcriber") or {}).get("language")]
    )
    draft = ProviderDraft(
        name=text(assistant.get("name")),
        external_id=assistant_id,
        languages=languages,
        language_note=language_note,
        config=json.dumps(behavior(assistant, tools), indent=2, ensure_ascii=False),
        direction=Direction.INBOUND,
        agent_numbers=own,
        start_request=None,
        agent_speaks_first=speaks_first(assistant),
    )
    if own:
        return draft
    callers = [number for number in active(numbers) if number.get("provider") != FREE_NUMBER]
    if not callers:
        raise ValidationError(
            "the assistant has no number, and the organization has no number to call from; a "
            "free Vapi number cannot place calls, so import one in Vapi first"
        )
    request = start_request(api, assistant_id, callers[0], variables(assistant))
    return draft.model_copy(update={"direction": Direction.OUTBOUND, "start_request": request})


def numbers_of(numbers: list[dict[str, Any]], assistant_id: str) -> list[str]:
    """The assistant's numbers that take calls now; a blocked or activating one does not."""
    return [
        str(number["number"])
        for number in active(numbers)
        if number.get("assistantId") == assistant_id and number.get("number")
    ]


def active(numbers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [number for number in numbers if number.get("status", "active") == "active"]


def speaks_first(assistant: dict[str, Any]) -> bool:
    """Vapi waits for the caller unless the assistant has a first message or makes one."""
    mode = assistant.get("firstMessageMode")
    if mode == FIRST_MESSAGE_GENERATED:
        return True
    return mode != FIRST_MESSAGE_WAITS and bool(assistant.get("firstMessage"))


def model(assistant: dict[str, Any]) -> dict[str, Any]:
    return assistant.get("model") or {}


def behavior(assistant: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """The assistant as the judges read it: its prompt, messages and tools, and how Vapi grades
    its calls, without voice, transcriber and account settings."""
    used = model(assistant)
    return pruned(
        without(
            {
                "name": assistant.get("name"),
                "first_message": assistant.get("firstMessage"),
                "first_message_mode": assistant.get("firstMessageMode"),
                "messages": used.get("messages"),
                "tools": [*(used.get("tools") or []), *tools],
                "end_call_message": assistant.get("endCallMessage"),
                "end_call_phrases": assistant.get("endCallPhrases"),
                "voicemail_message": assistant.get("voicemailMessage"),
                "analysis_plan": assistant.get("analysisPlan"),
            },
            CREDENTIALS,
        )
    )


def variables(assistant: dict[str, Any]) -> list[str]:
    """The names of the variables the assistant's prompt and messages use, each once, without
    Vapi's own; a customer field keeps its customer. prefix."""
    texts = [
        assistant.get("firstMessage"),
        assistant.get("voicemailMessage"),
        assistant.get("endCallMessage"),
        *(message.get("content") for message in model(assistant).get("messages") or []),
    ]
    found = (VARIABLE.findall(item) for item in texts if isinstance(item, str))
    return [
        name
        for name in dict.fromkeys(name for names in found for name in names)
        if name not in BUILT_IN
        and (not name.startswith(CUSTOMER) or name.removeprefix(CUSTOMER) in CUSTOMER_FIELDS)
    ]


def start_request(
    api: VapiAccountApi, assistant_id: str, caller: dict[str, Any], names: list[str]
) -> StartRequestDraft:
    """Vapi's outbound call from the organization's first number to Yaksha, with the
    assistant's variables for each scenario to fill."""
    # customer.name becomes the fact customer_name, which a {{customer_name}} shares.
    facts = scenario_variables(dict.fromkeys(name.replace(".", "_") for name in names))
    customer = {
        name.removeprefix(CUSTOMER): facts[name.replace(".", "_")]
        for name in names
        if name.startswith(CUSTOMER)
    }
    values = {name: facts[name] for name in names if not name.startswith(CUSTOMER)}
    body: dict[str, Any] = {
        "assistantId": assistant_id,
        "phoneNumberId": caller.get("id"),
        "customer": {"number": NUMBER, **customer},
    }
    if values:
        body["assistantOverrides"] = {"variableValues": values}
    request = StartRequestDraft(
        method=TriggerMethod.POST,
        url=f"{api.base_url}/call",
        headers=[Pair(name="Authorization", value=f"Bearer {api.api_key}")],
        query=[],
        body=body,
        number_field=NUMBER_FIELD,
    )
    check(request)
    return request


def moment(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def vapi_errors() -> AbstractContextManager[None]:
    return provider_errors(
        "Vapi",
        refused="Vapi refused the API key; use the private key, and a key from an EU "
        "organization works only with EU chosen",
        forbidden="the API key may not read assistants; use the organization's private key",
    )
