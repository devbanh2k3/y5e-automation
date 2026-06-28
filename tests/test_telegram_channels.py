from unittest.mock import AsyncMock

import pytest


def test_channel_keyboard_contains_only_active_channels() -> None:
    from services.telegram_channels import build_channel_keyboard

    keyboard = build_channel_keyboard(
        [
            {"youtube_channel_id": "one", "title": "One", "status": "active"},
            {"youtube_channel_id": "two", "title": "Two", "status": "disconnected"},
        ]
    )

    payload = str(keyboard)
    assert "One" in payload
    assert "Two" not in payload
    assert "Add channel" in payload


@pytest.mark.asyncio
async def test_select_callback_verifies_owner(monkeypatch) -> None:
    from services import telegram_channels

    select = AsyncMock(return_value={"title": "Alice Channel"})
    monkeypatch.setattr(telegram_channels.youtube_channels, "select_owned_channel", select)

    response = await telegram_channels.handle_channel_callback(
        telegram_user_id=111,
        data="yt:select:channel-1",
    )

    assert response.text == "Selected channel: Alice Channel"
    assert select.await_args.kwargs["owner_telegram_user_id"] == 111


@pytest.mark.asyncio
async def test_add_callback_returns_oauth_button(monkeypatch) -> None:
    from services import telegram_channels

    monkeypatch.setattr(
        telegram_channels.youtube_channels,
        "issue_oauth_token",
        AsyncMock(return_value="ticket-1"),
    )
    monkeypatch.setattr(
        telegram_channels,
        "get_settings",
        lambda: type("S", (), {"public_base_url": "https://quick.example"})(),
    )

    response = await telegram_channels.handle_channel_callback(
        telegram_user_id=111,
        data="yt:add",
    )

    button = response.reply_markup["inline_keyboard"][0][0]
    assert button["url"].endswith("/api/youtube/oauth/start?ticket=ticket-1")
