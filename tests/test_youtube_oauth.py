from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock

import pytest


def test_authorization_url_requests_offline_upload_access(monkeypatch) -> None:
    from services import youtube_oauth

    monkeypatch.setattr(
        youtube_oauth,
        "get_settings",
        lambda: type("S", (), {"youtube_oauth_client_id": "client-1"})(),
    )

    url = youtube_oauth.build_authorization_url(
        state="state-1",
        redirect_uri="https://x.test/api/youtube/oauth/callback",
    )
    query = parse_qs(urlparse(url).query)

    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert "https://www.googleapis.com/auth/youtube.upload" in query["scope"][0]


@pytest.mark.asyncio
async def test_complete_oauth_consumes_state_and_saves_authenticated_channel(monkeypatch) -> None:
    from services import youtube_oauth

    monkeypatch.setattr(
        youtube_oauth.youtube_channels,
        "consume_oauth_token",
        AsyncMock(return_value=111),
    )
    monkeypatch.setattr(
        youtube_oauth,
        "exchange_authorization_code",
        AsyncMock(
            return_value={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "scope": "scope-a scope-b",
            }
        ),
    )
    monkeypatch.setattr(
        youtube_oauth,
        "fetch_authenticated_channel",
        AsyncMock(return_value={"external_channel_id": "UC123", "title": "Alice"}),
    )
    save = AsyncMock(
        return_value={
            "youtube_channel_id": "channel-1",
            "external_channel_id": "UC123",
            "title": "Alice",
            "status": "active",
        }
    )
    monkeypatch.setattr(youtube_oauth.youtube_channels, "upsert_owned_channel", save)

    result = await youtube_oauth.complete_oauth(code="code-1", state="state-1")

    assert result["owner_telegram_user_id"] == 111
    assert result["external_channel_id"] == "UC123"
    assert "refresh_token" not in result
    assert save.await_args.kwargs["refresh_token"] == "refresh-1"


@pytest.mark.asyncio
async def test_complete_oauth_requires_refresh_token(monkeypatch) -> None:
    from services import youtube_oauth

    monkeypatch.setattr(
        youtube_oauth.youtube_channels,
        "consume_oauth_token",
        AsyncMock(return_value=111),
    )
    monkeypatch.setattr(
        youtube_oauth,
        "exchange_authorization_code",
        AsyncMock(return_value={"access_token": "access-1"}),
    )

    with pytest.raises(youtube_oauth.YouTubeOAuthError, match="refresh token"):
        await youtube_oauth.complete_oauth(code="code-1", state="state-1")
