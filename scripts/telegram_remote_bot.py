#!/usr/bin/env python3
"""Telegram polling bot for remote production control."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import get_settings
from services.telegram_remote import handle_telegram_command

TELEGRAM_API = "https://api.telegram.org"


async def send_message(*, chat_id: int, text: str) -> bool:
    """Send one Telegram message to the chat that issued a command."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        return False
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()
    return True


async def handle_update(update: dict[str, Any]) -> bool:
    """Handle one Telegram update. Returns True when a text message was handled."""
    message = update.get("message")
    if not isinstance(message, dict):
        return False
    text = str(message.get("text", "")).strip()
    if not text:
        return False
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    chat_id = int(chat.get("id", 0))
    telegram_user_id = int(sender.get("id", 0))
    username = str(sender.get("username", ""))
    if not chat_id or not telegram_user_id:
        return False

    response = await handle_telegram_command(
        telegram_user_id=telegram_user_id,
        username=username,
        text=text,
    )
    await send_message(chat_id=chat_id, text=response)
    return True


async def poll_forever(*, poll_interval: float = 1.0) -> None:
    """Poll Telegram updates forever."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    offset = 0
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/getUpdates"
    async with httpx.AsyncClient(timeout=35.0) as client:
        while True:
            response = await client.get(
                url,
                params={"timeout": 30, "offset": offset, "allowed_updates": ["message"]},
            )
            response.raise_for_status()
            payload = response.json()
            for update in payload.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                await handle_update(update)
            await asyncio.sleep(poll_interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    asyncio.run(poll_forever(poll_interval=args.poll_interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

