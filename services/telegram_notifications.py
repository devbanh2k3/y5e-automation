"""Telegram message delivery helpers."""

from __future__ import annotations

import httpx

from ipaddress import ip_address
from urllib.parse import urlparse
from typing import Any

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


def build_review_keyboard(review_id: str) -> dict[str, Any]:
    """Return inline review buttons for one pending review."""
    base_url = str(get_settings().public_base_url).rstrip("/")
    rows: list[list[dict[str, str]]] = []
    if _is_public_http_url(base_url):
        rows.append(
            [
                {"text": "Open video", "url": f"{base_url}/api/reviews/{review_id}/video"},
                {"text": "Review UI", "url": f"{base_url}/review-ui"},
            ]
        )
    rows.extend(
        [
            [{"text": "Approve", "callback_data": f"rv:ok:{review_id}"}],
            [
                {"text": "Reject image", "callback_data": f"rv:rej:wrong_image:{review_id}"},
                {"text": "Reject fact", "callback_data": f"rv:rej:bad_fact:{review_id}"},
            ],
            [
                {"text": "Reject video", "callback_data": f"rv:rej:bad_video:{review_id}"},
                {"text": "Reject layout", "callback_data": f"rv:rej:bad_layout:{review_id}"},
            ],
            [{"text": "Reject other", "callback_data": f"rv:rej:other:{review_id}"}],
        ]
    )
    return {"inline_keyboard": rows}


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return True
    return not (address.is_loopback or address.is_private or address.is_link_local)


async def send_telegram_message(
    *,
    chat_id: int | None,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> bool:
    """Send a Telegram message when bot credentials and a chat id are available."""
    settings = get_settings()
    target_chat_id = chat_id if chat_id is not None else _fallback_chat_id()
    if not settings.telegram_bot_token or target_chat_id is None:
        return False

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        payload: dict[str, Any] = {
            "chat_id": target_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        response = await client.post(url, json=payload)
        response.raise_for_status()
    return True


async def answer_callback_query(*, callback_query_id: str, text: str) -> bool:
    """Acknowledge a Telegram inline button tap."""
    settings = get_settings()
    if not settings.telegram_bot_token or not callback_query_id:
        return False

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/answerCallbackQuery"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            url,
            json={
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": False,
            },
        )
        response.raise_for_status()
    return True
