"""Imports an agent from a Plivo CX account: lists the account's agent flows, and reads one into
a draft agent. The Auth ID and Auth token are used for these calls only."""

import base64
import json
import re
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from yaksha.domain.agent_import import (
    Pair,
    PlivoCxAccountApi,
    PlivoCxDraft,
    PlivoCxFlow,
    PlivoCxFlowPage,
    PlivoCxFlowSearch,
    StartRequestDraft,
)
from yaksha.domain.agents import Direction
from yaksha.domain.errors import (
    NotFoundError,
    ProviderCallError,
    UnavailableError,
    ValidationError,
)
from yaksha.domain.languages import Language
from yaksha.domain.triggers import TriggerMethod
from yaksha.simulation.agent_import import text
from yaksha.simulation.curl_import import FILL, NUMBER, NUMBER_NAME, check, scenario_body

RUNNER = "https://agentflow.plivo.com"
"""Where Plivo CX starts a flow that a request starts, as its "Copy cURL" shows."""
FLOW_IN_ANSWER_URL = re.compile(r"/phlo/([0-9a-f-]{36})")


CALL_FLOW_TYPES = frozenset({"incoming_call", "api_request", "omni"})
"""Flows that answer a call, place one on a request, or serve several channels that can include
calls. WhatsApp, SMS, chat and Slack flows are left out: Yaksha tests calls."""


async def list_flows(api: PlivoCxAccountApi, search: PlivoCxFlowSearch) -> PlivoCxFlowPage:
    """One page of Plivo's list, without the flows that do not take calls; a page can hold fewer
    than Plivo's 20, so `next_offset` says where the next one starts."""
    with plivo_errors():
        page = await api.list_agent_flows(name=search.name, offset=search.offset)
    rows = page.get("objects") or []
    after = search.offset + len(rows)
    return PlivoCxFlowPage(
        items=[
            PlivoCxFlow(
                id=str(flow.get("agent_uuid")),
                name=str(flow.get("name") or "Untitled flow"),
                state=flow.get("state"),
                type=flow.get("flow_type"),
                updated_at=moment(flow.get("updated_at")),
            )
            for flow in rows
            if flow.get("flow_type") in CALL_FLOW_TYPES
        ],
        next_offset=after
        if rows and after < int((page.get("meta") or {}).get("total_count") or 0)
        else None,
    )


async def import_flow(api: PlivoCxAccountApi, flow_id: uuid.UUID) -> PlivoCxDraft:
    with plivo_errors():
        flow = json.loads(await api.get_agent_flow(str(flow_id)))
    if flow.get("state") != "ACTIVE":
        raise ValidationError(
            f"the flow is {str(flow.get('state') or 'not active').lower()}, and only an active "
            "flow takes calls; publish it in Plivo CX first"
        )
    triggers = start_model(flow).get("triggers") or []
    draft = PlivoCxDraft(
        name=text(flow.get("name")),
        external_id=str(flow_id),
        # The public API has no language yet; the person sets it.
        language=Language.EN,
        config=json.dumps(behavior(flow), indent=2),
        direction=Direction.INBOUND,
        agent_numbers=[],
        start_request=None,
    )
    if "call" in triggers:
        with plivo_errors():
            numbers = await flow_numbers(api, flow_id)
        return draft.model_copy(update={"agent_numbers": numbers})
    if "http" in triggers:
        request = start_request(api, flow_id, start_model(flow))
        return draft.model_copy(update={"direction": Direction.OUTBOUND, "start_request": request})
    started_by = ", ".join(str(trigger) for trigger in triggers) or "nothing Yaksha knows"
    raise ValidationError(
        f"Yaksha tests calls, and this flow starts from {started_by}, not from a call or a request"
    )


def moment(value: Any) -> datetime | None:
    """Plivo writes times as "2026-10-07 13:07:56.000000+00:00"; an unreadable one is left out."""
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


FLOW_BOOKKEEPING = frozenset(
    {"api_id", "resource_uri", "agent_uuid", "state", "version", "created_at", "updated_at"}
)
"""The flow's ID is the agent's Agent ID already; the rest describes the API record."""
NODE_LAYOUT = frozenset({"left", "top"})
NOT_BEHAVIOR = frozenset({"code_body"})
"""The source code of a tool action; its description and parameters stay."""
CONTRACTS = frozenset(
    {"code_function_schema", "parameters", "properties", "payload_format", "schema"}
)
"""Schemas and payload shapes, kept exactly: an empty value or a field named code_body in one is
part of what a tool takes."""
REDACTED = "***REDACTED***"


def behavior(flow: dict[str, Any]) -> dict[str, Any]:
    """The flow as the judges read it: what the agent says and does, without the API record, the
    canvas layout, tool source code, redacted secrets and empty fields."""
    nodes = [
        {key: value for key, value in node.items() if key not in NODE_LAYOUT}
        for node in flow.get("nodes") or []
    ]
    kept = {key: value for key, value in flow.items() if key not in FLOW_BOOKKEEPING}
    return pruned({**kept, "nodes": nodes})


def pruned(value: Any) -> Any:
    """`value` without empty values, redacted secrets or tool source, at any depth except inside a
    schema; False and 0 stay, because they mean something."""
    if isinstance(value, dict):
        kept = {
            key: item if key in CONTRACTS else pruned(item)
            for key, item in value.items()
            if key not in NOT_BEHAVIOR
        }
        return {key: item for key, item in kept.items() if key in CONTRACTS or not empty(item)}
    if isinstance(value, list):
        return [item for item in (pruned(item) for item in value) if not empty(item)]
    return value


def empty(value: Any) -> bool:
    return value is None or value in ("", REDACTED) or value == [] or value == {}


def start_model(flow: dict[str, Any]) -> dict[str, Any]:
    start = next((node for node in flow.get("nodes") or [] if node.get("type") == "start"), {})
    return (start.get("config") or {}).get("model") or {}


async def flow_numbers(api: PlivoCxAccountApi, flow_id: uuid.UUID) -> list[str]:
    """The voice numbers whose calls go to the flow. Plivo CX gives each such number an
    application whose answer URL names the flow; an application can outlive a number that moved
    to another flow, so each number's own application decides."""
    applications = await api.agent_flow_applications()
    reaching = {
        app_id
        for app_id, answer_url in applications.items()
        if (found := FLOW_IN_ANSWER_URL.search(answer_url)) and found.group(1) == str(flow_id)
    }
    return [
        number.number
        for number in await api.list_numbers()
        if number.voice and number.application_id in reaching
    ]


def start_request(
    api: PlivoCxAccountApi, flow_id: uuid.UUID, start: dict[str, Any]
) -> StartRequestDraft:
    """The request Plivo CX's "Copy cURL" shows: the flow's run URL, Basic auth when the flow asks
    for it, and a body with the flow's payload fields."""
    body = filled(start.get("payload_format") or {})
    field = next((name for name in body if NUMBER_NAME.search(name)), None)
    if field is not None:
        body[field] = NUMBER
    headers = []
    if start.get("require_http_auth", True):
        token = base64.b64encode(f"{api.auth_id}:{api.auth_token}".encode()).decode()
        headers.append(Pair(name="Authorization", value=f"Basic {token}"))
    request = StartRequestDraft(
        method=TriggerMethod.POST,
        url=f"{RUNNER}/v1/account/{api.auth_id}/flow/{flow_id}",
        headers=headers,
        query=[],
        body=scenario_body(body, headers),
        number_field=field,
    )
    check(request)
    return request


def filled(payload_format: dict[str, Any]) -> dict[str, Any]:
    """The payload's fields, each to be filled in, keeping its nesting."""
    return {
        name: filled(kind) if isinstance(kind, dict) else FILL
        for name, kind in payload_format.items()
    }


@contextmanager
def plivo_errors() -> Generator[None]:
    try:
        yield
    except ProviderCallError as error:
        match error.status:
            case 401:
                raise ValidationError("Plivo refused the Auth ID and Auth token") from None
            case 403:
                raise ValidationError(
                    "Plivo refused this account: use the main account's Auth ID and Auth token, "
                    "not a subaccount's"
                ) from None
            case 404:
                raise NotFoundError("Plivo has no agent flow with this ID in the account") from None
            case 429:
                raise UnavailableError(
                    "Plivo allows 60 requests a minute; wait a minute, then try again"
                ) from None
            case None:
                raise UnavailableError("Yaksha could not reach Plivo; try again later") from None
            case status:
                # Plivo's reply stays out of the message: the client sees only its status.
                raise UnavailableError(
                    f"Plivo answered with status {status}; try again later"
                ) from None
    except ValueError:
        raise UnavailableError("Plivo answered with something that is not JSON") from None
