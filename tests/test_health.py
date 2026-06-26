import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from core.health import ComponentCheck, ReadinessResult


@pytest.mark.asyncio
async def test_ready_returns_200_when_all_checks_pass(monkeypatch):
    async def fake_readiness():
        return ReadinessResult(
            ok=True,
            checks={
                "database": ComponentCheck(status="ok"),
                "redis": ComponentCheck(status="ok"),
                "storage": ComponentCheck(status="ok"),
                "config": ComponentCheck(status="ok"),
            },
        )

    monkeypatch.setattr("api.main.check_readiness", fake_readiness)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_ready_returns_503_when_any_check_fails(monkeypatch):
    async def fake_readiness():
        return ReadinessResult(
            ok=False,
            checks={
                "database": ComponentCheck(status="error", message="connection failed"),
                "redis": ComponentCheck(status="ok"),
                "storage": ComponentCheck(status="ok"),
                "config": ComponentCheck(status="ok"),
            },
        )

    monkeypatch.setattr("api.main.check_readiness", fake_readiness)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"]["status"] == "error"
