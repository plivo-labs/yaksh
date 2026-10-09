from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import FakeJsonModel, create_persona

URL = "/api/v1/personas/draft"


async def test_a_persona_is_written_from_a_short_line(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    drafted = await client.post(URL, json={"idea": " tired nurse on a busy street "})

    assert drafted.json() == {
        "name": "Asha Rao",
        "prompt": generation_model.persona["prompt"],
        "language": "hi",
        "voice_gender": "female",
        "speed": 1.15,
        "surroundings": {
            "sounds": [{"sound": "street", "db": -10}],
            "auto": None,
            "speaker": None,
        },
        "left_out": [],
    }
    assert generation_model.calls == [("persona", "Line: tired nurse on a busy street")]


async def test_the_names_of_existing_personas_are_not_given_again(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    await create_persona(client, name="Zoe Park")
    await create_persona(client, name="Asha Rao")

    await client.post(URL, json={"idea": "tired nurse"})

    assert generation_model.calls == [
        ("persona", "Line: tired nurse\nNames already used: Asha Rao, Zoe Park")
    ]


async def test_what_the_line_does_not_say_gets_the_defaults(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    generation_model.persona |= {"voice_gender": "neutral", "speed": "normal", "noise": None}

    drafted = (await client.post(URL, json={"idea": "tired nurse"})).json()

    assert (drafted["voice_gender"], drafted["speed"]) == ("neutral", 1.0)
    assert drafted["surroundings"] == {"sounds": [], "auto": None, "speaker": None}


async def test_a_noisy_place_with_people_talking_fills_the_surroundings(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    generation_model.persona |= {
        "noise": "mixed",
        "noise_level": "loud",
        "speaker": "talks_to_caller",
        "left_out": ["baby crying: no baby sound, used mixed noise", " "],
    }

    drafted = (await client.post(URL, json={"idea": "caller with friends talking"})).json()

    assert drafted["surroundings"] == {
        "sounds": [],
        "auto": {"db": -4, "seed": 1},
        "speaker": {"kind": "talks_to_caller", "db": -6, "start_s": 5},
    }
    assert drafted["left_out"] == ["baby crying: no baby sound, used mixed noise"]


async def test_a_tv_plays_once_as_the_second_speaker(
    client: AsyncClient, generation_model: FakeJsonModel
) -> None:
    generation_model.persona |= {"noise": "tv", "speaker": "tv"}

    drafted = (await client.post(URL, json={"idea": "caller with the TV on"})).json()

    assert drafted["surroundings"]["sounds"] == []
    assert drafted["surroundings"]["speaker"]["kind"] == "tv"


@pytest.mark.parametrize(
    ("idea", "change", "down", "status"),
    [
        ("  ", {}, False, 422),
        ("tired nurse", {"prompt": "You are tired."}, False, 503),
        ("tired nurse", {"name": " "}, False, 503),
        ("tired nurse", {"noise": "rain"}, False, 503),
        ("tired nurse", {"speaker": "dog"}, False, 503),
        ("tired nurse", {"voice_gender": None}, False, 503),
        ("tired nurse", {}, True, 503),
    ],
    ids=[
        "empty line",
        "behavior too short",
        "no name",
        "unknown noise",
        "unknown speaker",
        "no voice gender",
        "model down",
    ],
)
async def test_a_persona_that_cannot_be_written_says_so(
    client: AsyncClient,
    generation_model: FakeJsonModel,
    idea: str,
    change: dict[str, Any],
    down: bool,
    status: int,
) -> None:
    generation_model.persona |= change
    generation_model.down = down

    refused = await client.post(URL, json={"idea": idea})

    assert refused.status_code == status
