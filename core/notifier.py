"""Telegram Bot notification helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"


def _configured() -> bool:
    """Return True if Telegram credentials are set."""
    settings = get_settings()
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


async def notify(message: str, parse_mode: str = "HTML") -> bool:
    """Send a Telegram message.

    Args:
        message: The message body (HTML or plain text).
        parse_mode: Telegram parse mode — ``HTML`` or ``MarkdownV2``.

    Returns:
        ``True`` if the message was delivered, ``False`` otherwise.
    """
    if not _configured():
        logger.debug("Telegram not configured; skipping notification.")
        return False

    settings = get_settings()
    url = f"{_TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"

    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("Telegram notification sent successfully.")
            return True
    except httpx.HTTPError as exc:
        logger.error("Failed to send Telegram notification: %s", exc)
        return False


async def notify_success(title: str, youtube_id: str) -> bool:
    """Send a success notification when a video is published.

    Args:
        title: The video title.
        youtube_id: The YouTube video ID.

    Returns:
        ``True`` if delivered.
    """
    link = f"https://youtu.be/{youtube_id}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = (
        "✅ <b>Video Published</b>\n"
        f"<b>Title:</b> {title}\n"
        f"<b>Link:</b> {link}\n"
        f"<b>Time:</b> {now}"
    )
    return await notify(message)


async def notify_error(agent: str, error: str) -> bool:
    """Send an error notification.

    Args:
        agent: The agent or pipeline step that failed.
        error: A short description of the error.

    Returns:
        ``True`` if delivered.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    message = (
        "🚨 <b>Pipeline Error</b>\n"
        f"<b>Agent:</b> {agent}\n"
        f"<b>Error:</b> <code>{error}</code>\n"
        f"<b>Time:</b> {now}"
    )
    return await notify(message)


async def notify_daily_report(stats: dict) -> bool:
    """Send a daily summary report.

    Args:
        stats: A dict with keys like ``videos_published``,
            ``total_views``, ``api_cost``, ``errors``.

    Returns:
        ``True`` if delivered.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    videos = stats.get("videos_published", 0)
    views = stats.get("total_views", 0)
    cost = stats.get("api_cost", 0.0)
    errors = stats.get("errors", 0)
    subs = stats.get("subs_gained", 0)

    message = (
        f"📊 <b>Daily Report — {now}</b>\n"
        f"🎬 Videos published: <b>{videos}</b>\n"
        f"👀 Total views: <b>{views:,}</b>\n"
        f"👥 Subscribers gained: <b>{subs:,}</b>\n"
        f"💰 API cost: <b>${cost:.2f}</b>\n"
        f"❌ Errors: <b>{errors}</b>"
    )
    return await notify(message)
