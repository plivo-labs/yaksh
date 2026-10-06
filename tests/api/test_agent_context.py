import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import create_agent
from yaksha.domain.agents import MAX_BRIEF_CHARS, MAX_KNOWLEDGE_BASE_DOCUMENTS

FLOW = '{"nodes": [{"name": "Missed visit", "prompt": "Offer a new time."}]}'


async def pasted(client: AsyncClient, name: str, text: str) -> str:
    response = await client.post("/api/v1/documents", json={"name": name, "text": text})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_config_and_knowledge_base_are_versioned_with_the_agent(
    client: AsyncClient,
) -> None:
    hours = await pasted(client, "hours.txt", "Open 9 to 5.")
    insurance = await pasted(client, "insurance.md", "We accept Medi-Cal.")
    agent = await create_agent(
        client,
        config=FLOW,
        knowledge_base=[
            {"document_id": hours, "name": "Clinic hours"},
            {"document_id": insurance, "name": "Insurance FAQ"},
        ],
    )

    renamed = await client.patch(
        f"/api/v1/agents/{agent['id']}",
        json={"knowledge_base": [{"document_id": hours, "name": "Opening hours"}]},
    )
    first = (await client.get(f"/api/v1/agents/{agent['id']}/versions/1")).json()["config"]
    listed = (await client.get("/api/v1/agents")).json()["items"][0]

    assert agent["config"] == FLOW
    assert [(e["name"], e["characters"], e["media_type"]) for e in agent["knowledge_base"]] == [
        ("Clinic hours", 12, None),
        ("Insurance FAQ", 19, None),
    ]
    assert renamed.json()["current_version"] == 2
    assert [e["name"] for e in renamed.json()["knowledge_base"]] == ["Opening hours"]
    assert [e["name"] for e in first["knowledge_base"]] == ["Clinic hours", "Insurance FAQ"]
    assert "config" not in listed and "knowledge_base" not in listed


@pytest.mark.parametrize(
    ("knowledge_base", "message"),
    [
        ("missing", "knowledge_base: no document"),
        ("same name", "two knowledge base documents have the same name"),
        ("same document", "a document is in the knowledge base twice"),
        ("too many", f"at most {MAX_KNOWLEDGE_BASE_DOCUMENTS} items"),
    ],
)
async def test_a_knowledge_base_must_name_each_existing_document_once(
    client: AsyncClient, knowledge_base: str, message: str
) -> None:
    first = await pasted(client, "a.txt", "A.")
    second = await pasted(client, "b.txt", "B.")
    entries: dict[str, list[dict[str, Any]]] = {
        "missing": [{"document_id": str(uuid.uuid4()), "name": "Ghost"}],
        "same name": [
            {"document_id": first, "name": "FAQ"},
            {"document_id": second, "name": "faq"},
        ],
        "same document": [
            {"document_id": first, "name": "FAQ"},
            {"document_id": first, "name": "Policies"},
        ],
        "too many": [
            {"document_id": first, "name": f"Doc {n}"}
            for n in range(MAX_KNOWLEDGE_BASE_DOCUMENTS + 1)
        ],
    }
    agent = await create_agent(client)

    refused = await client.patch(
        f"/api/v1/agents/{agent['id']}", json={"knowledge_base": entries[knowledge_base]}
    )

    assert refused.status_code == 422
    assert message in refused.json()["error"]["message"]


async def test_text_fields_drop_nul_and_the_brief_has_a_limit(client: AsyncClient) -> None:
    agent = await create_agent(client, brief="Books\u0000 visits.", config="Prompt\u0000.")
    too_long = await client.post(
        "/api/v1/agents",
        json={
            "name": "Wordy",
            "agent_number": "+14155550101",
            "brief": "a" * (MAX_BRIEF_CHARS + 1),
        },
    )

    assert (agent["brief"], agent["config"]) == ("Books visits.", "Prompt.")
    assert too_long.status_code == 422


async def test_a_taken_external_id_is_a_conflict_even_with_a_knowledge_base_change(
    client: AsyncClient,
) -> None:
    await create_agent(client, external_id="front-desk")
    other = await create_agent(client, agent_number="+14155550102")
    document = await pasted(client, "hours.txt", "Open 9 to 5.")

    clash = await client.patch(
        f"/api/v1/agents/{other['id']}",
        json={
            "external_id": "front-desk",
            "knowledge_base": [{"document_id": document, "name": "Hours"}],
        },
    )

    assert clash.status_code == 409
