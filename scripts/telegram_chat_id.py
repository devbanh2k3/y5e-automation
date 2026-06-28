#!/usr/bin/env python3
"""Print recent Telegram chat ids visible to the configured bot."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import get_settings
from services.telegram_notifications import TELEGRAM_API


async def list_chat_ids(*, timeout: int) -> list[dict[str, str | int]]:
    """Return recent chat ids from Telegram updates."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/getUpdates"
    async with httpx.AsyncClient(timeout=timeout + 5.0) as client:
        response = await client.get(url, params={"timeout": timeout, "allowed_updates": ["message"]})
        response.raise_for_status()
        payload = response.json()

    chats: dict[int, dict[str, str | int]] = {}
    for update in payload.get("result", []):
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict):
            continue
        chat_id = int(chat.get("id", 0))
        if not chat_id:
            continue
        chats[chat_id] = {
            "chat_id": chat_id,
            "chat_type": str(chat.get("type", "")),
            "chat_title": str(chat.get("title") or chat.get("username") or ""),
            "from_user_id": int(sender.get("id", 0)) if isinstance(sender, dict) else 0,
            "from_username": str(sender.get("username", "")) if isinstance(sender, dict) else "",
        }
    return list(chats.values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=10)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    chats = asyncio.run(list_chat_ids(timeout=args.timeout))
    if not chats:
        print("No chats found. Send /start to the bot in Telegram, then run this again.")
        return 1
    for chat in chats:
        print(
            f"chat_id={chat['chat_id']} "
            f"type={chat['chat_type']} "
            f"title={chat['chat_title']} "
            f"from_user_id={chat['from_user_id']} "
            f"from_username={chat['from_username']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
