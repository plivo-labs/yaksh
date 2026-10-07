import pytest
from httpx import AsyncClient

from tests.conftest import FakeJsonModel
from yaksha.domain.errors import UnavailableError
from yaksha.simulation.briefs import draft_brief


async def test_a_brief_is_drafted_from_the_config(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    drafted = await client.post("/api/v1/agents/draft-brief", json={"config": "You book teeth."})

    assert drafted.json() == {"brief": generation_model.brief}
    assert generation_model.calls == [("brief", "You book teeth.")]


@pytest.mark.parametrize(
    ("config", "brief", "down", "status"),
    [
        ("  ", "Books dental appointments for callers.", False, 422),
        ("You book teeth.", "Books.", False, 503),
        ("You book teeth.", "Books dental appointments for callers.", True, 503),
    ],
    ids=["empty config", "too short", "model down"],
)
async def test_a_draft_that_cannot_be_made_says_so(
    client: AsyncClient,
    generation_model: FakeJsonModel,
    config: str,
    brief: str,
    down: bool,
    status: int,
) -> None:
    generation_model.brief, generation_model.down = brief, down

    refused = await client.post("/api/v1/agents/draft-brief", json={"config": config})

    assert refused.status_code == status


async def test_no_draft_without_a_model() -> None:
    with pytest.raises(UnavailableError, match="LLM provider key"):
        await draft_brief(None, "You book teeth.")
