"""Telegram channel management messages and callback handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from core import youtube_channels
from core.config import get_settings
from services.youtube_oauth import revoke_refresh_token


@dataclass(frozen=True)
class TelegramResponse:
    """Message text with optional Telegram inline keyboard."""

    text: str
    reply_markup: dict[str, Any] | None = None


def build_channel_keyboard(channels: list[dict[str, Any]]) -> dict[str, Any]:
    """Build selection buttons for active owned channels."""
    rows = [
        [
            {
                "text": str(channel["title"]),
                "callback_data": f"yt:select:{channel['youtube_channel_id']}",
            },
            {
                "text": "Disconnect",
                "callback_data": f"yt:disconnect:{channel['youtube_channel_id']}",
            },
        ]
        for channel in channels
        if channel.get("status") == "active"
    ]
    rows.append([{"text": "Add channel", "callback_data": "yt:add"}])
    return {"inline_keyboard": rows}


async def channel_list_response(telegram_user_id: int, *, prompt: str = "Your YouTube channels:") -> TelegramResponse:
    """Return an owner-filtered channel list and selection keyboard."""
    channels = await youtube_channels.list_owned_channels(telegram_user_id)
    if not channels:
        prompt = f"{prompt}\nNo YouTube channel connected. Add one before creating videos."
    return TelegramResponse(prompt, build_channel_keyboard(channels))


async def handle_channel_callback(*, telegram_user_id: int, data: str) -> TelegramResponse:
    """Handle compact tenant-bound channel callbacks."""
    if data == "yt:add":
        base_url = get_settings().public_base_url.rstrip("/")
        if not base_url.startswith("https://"):
            return TelegramResponse("PUBLIC_BASE_URL must be a public HTTPS URL for Google OAuth.")
        ticket = await youtube_channels.issue_oauth_token(
            owner_telegram_user_id=telegram_user_id,
            purpose="connect_ticket",
        )
        url = f"{base_url}/api/youtube/oauth/start?ticket={quote(ticket)}"
        return TelegramResponse(
            "Open Google to connect a YouTube channel.",
            {"inline_keyboard": [[{"text": "Connect YouTube", "url": url}]]},
        )
    if data.startswith("yt:select:"):
        channel_id = data.removeprefix("yt:select:")
        try:
            channel = await youtube_channels.select_owned_channel(
                owner_telegram_user_id=telegram_user_id,
                channel_id=channel_id,
            )
        except youtube_channels.ChannelAccessError:
            return TelegramResponse("YouTube channel is unavailable.")
        return TelegramResponse(f"Selected channel: {channel['title']}")
    if data.startswith("yt:disconnect_confirm:"):
        channel_id = data.removeprefix("yt:disconnect_confirm:")
        try:
            channel = await youtube_channels.get_owned_channel(
                channel_id,
                owner_telegram_user_id=telegram_user_id,
            )
            await revoke_refresh_token(str(channel.get("encrypted_refresh_token") or ""))
            await youtube_channels.disconnect_owned_channel(
                owner_telegram_user_id=telegram_user_id,
                channel_id=channel_id,
            )
        except youtube_channels.ChannelAccessError:
            return TelegramResponse("YouTube channel is unavailable.")
        return TelegramResponse(f"Disconnected channel: {channel['title']}")
    if data.startswith("yt:disconnect:"):
        channel_id = data.removeprefix("yt:disconnect:")
        try:
            channel = await youtube_channels.get_owned_channel(
                channel_id,
                owner_telegram_user_id=telegram_user_id,
            )
        except youtube_channels.ChannelAccessError:
            return TelegramResponse("YouTube channel is unavailable.")
        return TelegramResponse(
            f"Disconnect {channel['title']}?",
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "Confirm disconnect",
                            "callback_data": f"yt:disconnect_confirm:{channel_id}",
                        }
                    ]
                ]
            },
        )
    return TelegramResponse("Unsupported YouTube channel action.")
