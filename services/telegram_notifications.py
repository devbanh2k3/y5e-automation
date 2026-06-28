"""Telegram message delivery helpers."""

from __future__ import annotations

import httpx

from core.config import get_settings

TELEGRAM_API = "https://api.telegram.org"


def _fallback_chat_id() -> int | None:
    settings = get_settings()
    raw = str(settings.telegram_chat_id or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


async def send_telegram_message(*, chat_id: int | None, text: str) -> bool:
    """Send a Telegram message when bot credentials and a chat id are available."""
    settings = get_settings()
    target_chat_id = chat_id if chat_id is not None else _fallback_chat_id()
    if not settings.telegram_bot_token or target_chat_id is None:
        return False

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            url,
            json={
                "chat_id": target_chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()
    return True
