from httpx import ASGITransport, AsyncClient

from truman import __version__
from truman.api import create_app


async def test_health_reports_ok_and_version() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
