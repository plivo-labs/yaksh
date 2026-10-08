import json
import uuid
from typing import Any

import pytest

from yaksha.domain.errors import ProviderCallError, UnavailableError, ValidationError
from yaksha.domain.numbers import AccountNumber
from yaksha.simulation.plivo_cx_import import behavior, import_flow

FLOW = uuid.UUID("0b9e0c4a-0000-4000-8000-000000000001")


class FailingNumbers:
    """An account whose flow a call starts, and whose number list fails as `failure` says."""

    auth_id = "MAXXXXXXXXXXXXXXXXXX"
    auth_token = "secret-token"

    def __init__(self, failure: ProviderCallError) -> None:
        self.failure = failure

    async def list_agent_flows(self, *, name: str | None, offset: int) -> dict[str, Any]:
        return {}

    async def get_agent_flow(self, flow_id: str) -> str:
        start = {"type": "start", "config": {"model": {"triggers": ["call"]}}}
        return json.dumps({"name": "Front desk", "state": "ACTIVE", "nodes": [start]})

    async def agent_flow_applications(self) -> dict[str, str]:
        return {}

    async def list_numbers(self) -> list[AccountNumber]:
        raise self.failure


async def test_every_plivo_call_maps_its_status() -> None:
    with pytest.raises(ValidationError, match="subaccount"):
        await import_flow(
            FailingNumbers(ProviderCallError("listing numbers failed", status=403)), FLOW
        )


async def test_plivo_s_reply_never_reaches_the_client() -> None:
    failure = ProviderCallError('failed with 500: {"debug": "token=abc"}', status=500)

    with pytest.raises(UnavailableError) as raised:
        await import_flow(FailingNumbers(failure), FLOW)

    assert str(raised.value) == "Plivo answered with status 500; try again later"


def test_the_config_keeps_behavior_and_drops_the_noise() -> None:
    flow = {
        "api_id": "a1",
        "agent_uuid": str(FLOW),
        "resource_uri": "/v1/Account/MA/AgentFlow/x/",
        "updated_at": "2026-10-08",
        "name": "Front desk",
        "description": "",
        "nodes": [
            {
                "id": "agent-1",
                "left": 120,
                "top": 80,
                "type": "ai_agent_v2",
                "config": {
                    "model": {
                        "instructions": "Book appointments.",
                        "allow_greeting_interruption": False,
                        "initial_wait_time": 0,
                        "routing_teams": [],
                        "end_message": None,
                        "actions": [
                            {
                                "name": "find_slot",
                                "code_body": "def run(): ...",
                                "auth_token": "***REDACTED***",
                                "code_function_schema": {
                                    "properties": {
                                        "status": {"enum": [None, "", "booked"]},
                                        "code_body": {"type": "string"},
                                        "metadata": {},
                                    },
                                    "required": ["code_body"],
                                },
                            }
                        ],
                    }
                },
            }
        ],
        "connections": [{"source": "start-1.call", "target": "agent-1"}],
    }

    assert behavior(flow) == {
        "name": "Front desk",
        "nodes": [
            {
                "id": "agent-1",
                "type": "ai_agent_v2",
                "config": {
                    "model": {
                        "instructions": "Book appointments.",
                        "allow_greeting_interruption": False,
                        "initial_wait_time": 0,
                        "actions": [
                            {
                                "name": "find_slot",
                                "code_function_schema": {
                                    "properties": {
                                        "status": {"enum": [None, "", "booked"]},
                                        "code_body": {"type": "string"},
                                        "metadata": {},
                                    },
                                    "required": ["code_body"],
                                },
                            }
                        ],
                    }
                },
            }
        ],
        "connections": [{"source": "start-1.call", "target": "agent-1"}],
    }
