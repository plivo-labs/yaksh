from httpx import ASGITransport, AsyncClient

from truman import __version__
from truman.api import create_app
from truman.config import Settings


async def test_health_reports_ok_and_version_without_a_token(offline_settings: Settings) -> None:
    transport = ASGITransport(app=create_app(offline_settings))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
