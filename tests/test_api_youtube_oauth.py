from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app


@pytest.mark.asyncio
async def test_oauth_start_consumes_ticket_and_redirects(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.main.start_youtube_oauth",
        AsyncMock(return_value="https://accounts.google.com/o/oauth2/v2/auth?state=state-1"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/youtube/oauth/start?ticket=ticket-1")

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://accounts.google.com/")


@pytest.mark.asyncio
async def test_oauth_callback_rejects_replayed_state(monkeypatch) -> None:
    from core.youtube_channels import OAuthStateError

    monkeypatch.setattr(
        "api.main.complete_youtube_oauth",
        AsyncMock(side_effect=OAuthStateError("already used")),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/youtube/oauth/callback?code=code-1&state=state-1"
        )

    assert response.status_code == 400
    assert "invalid" in response.text.lower()
