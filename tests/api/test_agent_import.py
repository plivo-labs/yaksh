import json
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import AGENT
from yaksha.domain.agents import MAX_CONFIG_CHARS


def plivo_cx_file(language: Any = "hi-IN,en-US") -> str:
    settings: dict[str, Any] = {"knowledge_base_ids": []}
    if language is not None:
        settings["voice_ai_config"] = {"language": language}
    return json.dumps(
        {
            "name": " Dental front desk ",
            "flowId": "3f9c1a72-6b4e-4d8a-9e21-5c7b0d3f8a16",
            "nodes": [{"type": "ai_agent_v29", "data": {"config": {"instructions": "Book."}}}],
            "edges": [],
            "agentSettings": settings,
        },
        indent=2,
    )


async def test_a_plivo_cx_download_becomes_a_draft_that_creates_an_agent(
    client: AsyncClient,
) -> None:
    content = plivo_cx_file()

    imported = await client.post("/api/v1/agents/import", json={"content": content})
    draft = imported.json()
    created = await client.post(
        "/api/v1/agents",
        json={
            **{key: draft[key] for key in ("name", "external_id", "language", "config")},
            "brief": AGENT["brief"],
            "agent_number": AGENT["agent_number"],
        },
    )

    assert imported.status_code == 200
    assert draft == {
        "provider": "plivo_cx",
        "name": "Dental front desk",
        "external_id": "3f9c1a72-6b4e-4d8a-9e21-5c7b0d3f8a16",
        "language": "hi",
        "config": content,
    }
    assert created.status_code == 201, created.text
    assert created.json()["config"] == content and created.json()["language"] == "hi"


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("hi", "hi"),
        ("hi_IN", "hi"),
        ("en-IN,hi", "en"),
        ("ta", "en"),
        ("", "en"),
        (None, "en"),
    ],
    ids=["hindi", "hindi with a region", "first of several", "not spoken yet", "empty", "missing"],
)
async def test_the_first_language_is_taken_and_one_yaksha_does_not_speak_becomes_english(
    client: AsyncClient, language: str | None, expected: str
) -> None:
    imported = await client.post("/api/v1/agents/import", json={"content": plivo_cx_file(language)})

    assert imported.json()["language"] == expected


@pytest.mark.parametrize(
    ("content", "code", "message"),
    [
        ('{"assistant": {"name": "Front desk"}}', "not_recognized", "does not know"),
        ('{\n  "name": "Front desk",\n}', "validation_error", "line 2, column 23"),
        (" " * (MAX_CONFIG_CHARS + 1), "validation_error", "larger than a config"),
        ('{"flowId": "f", "nodes": [], "agentSettings": {"x": NaN}}', "validation_error", "NaN"),
        (
            '{"flowId": "f", "nodes": [], "agentSettings": {}, "name": "\\ud800"}',
            "validation_error",
            "Unicode",
        ),
    ],
    ids=["other format", "not valid json", "too long", "not a json value", "half a character"],
)
async def test_a_file_that_cannot_be_imported_says_why(
    client: AsyncClient, content: str, code: str, message: str
) -> None:
    refused = await client.post("/api/v1/agents/import", json={"content": content})

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == code and message in refused.json()["error"]["message"]


async def test_a_number_too_long_for_python_is_still_valid_json(client: AsyncClient) -> None:
    content = plivo_cx_file().replace('"nodes"', '"version": ' + "9" * 5000 + ', "nodes"', 1)

    imported = await client.post("/api/v1/agents/import", json={"content": content})

    assert imported.status_code == 200 and imported.json()["config"] == content


async def test_a_curl_command_becomes_a_start_request(client: AsyncClient) -> None:
    command = 'curl https://agents.example.com/calls -d \'{"to": "+15550100", "lang": "en"}\''

    read = await client.post("/api/v1/agents/start-request-from-curl", json={"command": command})
    refused = await client.post("/api/v1/agents/start-request-from-curl", json={"command": "ls"})

    assert read.json() == {
        "method": "POST",
        "url": "https://agents.example.com/calls",
        "headers": [],
        "query": [],
        "body": {"to": "{{yaksha.number}}", "lang": "en"},
        "number_field": "to",
    }
    assert refused.status_code == 422 and "curl" in refused.json()["error"]["message"]
