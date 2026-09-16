from pathlib import Path

from httpx import ASGITransport, AsyncClient

from truman.api import create_app


def build_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.ico").write_bytes(b"icon")
    return dist


async def test_frontend_serves_assets_files_and_spa_fallback(tmp_path: Path) -> None:
    transport = ASGITransport(app=create_app(frontend_dist=build_dist(tmp_path)))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        asset = await client.get("/assets/app.js")
        public_file = await client.get("/favicon.ico")
        deep_link = await client.get("/runs/123")
        api = await client.get("/api/health")

    assert asset.status_code == 200 and asset.text == "console.log(1)"
    assert public_file.status_code == 200 and public_file.content == b"icon"
    assert deep_link.status_code == 200 and deep_link.text == "<html>app</html>"
    assert api.status_code == 200


async def test_without_a_build_only_the_api_is_served(tmp_path: Path) -> None:
    transport = ASGITransport(app=create_app(frontend_dist=tmp_path / "missing"))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/runs/123")

    assert response.status_code == 404


async def test_frontend_never_serves_files_outside_dist(tmp_path: Path) -> None:
    dist = build_dist(tmp_path)
    (tmp_path / "outside.txt").write_text("secret")
    (dist / "link").symlink_to(tmp_path / "outside.txt")
    transport = ASGITransport(app=create_app(frontend_dist=dist))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        traversal = await client.get("/%2e%2e/outside.txt")
        symlink = await client.get("/link")

    assert traversal.text == "<html>app</html>"
    assert symlink.text == "<html>app</html>"


async def test_unknown_api_route_is_404_even_with_a_frontend(tmp_path: Path) -> None:
    transport = ASGITransport(app=create_app(frontend_dist=build_dist(tmp_path)))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
