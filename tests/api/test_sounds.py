from httpx import AsyncClient

from yaksh.simulation.surroundings import SOUNDS


async def test_a_preview_plan_names_each_sound_and_the_files_are_served(
    client: AsyncClient,
) -> None:
    surroundings = {
        "sounds": [{"sound": "cafe", "db": 0}],
        "speaker": {"kind": "tv", "db": -6, "start_s": 2},
    }

    plan = await client.post(
        "/api/v1/sounds/plan", json={"surroundings": surroundings, "language": "en"}
    )
    layers = plan.json()["layers"]
    files = [await client.get(f"/api/v1/sounds/{layer['file']}") for layer in layers]

    assert plan.status_code == 200
    assert (layers[0]["file"], layers[0]["sound"], layers[0]["end_s"]) == ("cafe.wav", "cafe", None)
    assert {layer["speaker"] for layer in layers[1:]} == {"tv"}
    assert layers[1]["start_s"] == 2
    assert all(f.status_code == 200 and f.headers["content-type"] == "audio/wav" for f in files)
    assert files[0].content == (SOUNDS / "cafe.wav").read_bytes()


async def test_only_sound_files_are_served(client: AsyncClient) -> None:
    for path in ("../config.py", "..%2F..%2Fconfig.py", "README.md", "speakers.yaml"):
        response = await client.get(f"/api/v1/sounds/{path}")
        assert response.status_code in (404, 422), path
    assert (await client.get("/api/v1/sounds/nothing.wav")).status_code == 404
