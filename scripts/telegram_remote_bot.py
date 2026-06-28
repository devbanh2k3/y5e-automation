#!/usr/bin/env python3
"""Telegram polling bot for remote production control."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core import production_tasks
from core.config import get_settings
from services.telegram_notifications import TELEGRAM_API, answer_callback_query, send_telegram_message
from services.telegram_remote import handle_telegram_command
from services.telegram_channels import TelegramResponse, handle_channel_callback
from services.telegram_review_actions import handle_review_callback


async def send_message(
    *, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
) -> bool:
    """Send one Telegram message to the chat that issued a command."""
    return await send_telegram_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
    )


async def handle_update(update: dict[str, Any]) -> bool:
    """Handle one Telegram update. Returns True when a text message was handled."""
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        return await handle_callback_query(callback_query)

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

    await production_tasks.update_user_chat_id(
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
    )
    response = await handle_telegram_command(
        telegram_user_id=telegram_user_id,
        username=username,
        text=text,
    )
    if isinstance(response, TelegramResponse):
        await send_message(
            chat_id=chat_id,
            text=response.text,
            reply_markup=response.reply_markup,
        )
    else:
        await send_message(chat_id=chat_id, text=response)
    return True


async def handle_callback_query(callback_query: dict[str, Any]) -> bool:
    """Handle one inline button tap from Telegram."""
    callback_query_id = str(callback_query.get("id", ""))
    data = str(callback_query.get("data", ""))
    message = callback_query.get("message") if isinstance(callback_query.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = callback_query.get("from") if isinstance(callback_query.get("from"), dict) else {}
    chat_id = int(chat.get("id", 0))
    telegram_user_id = int(sender.get("id", 0))
    if not chat_id or not telegram_user_id or not data:
        return False

    if data.startswith("yt:"):
        channel_response = await handle_channel_callback(
            telegram_user_id=telegram_user_id,
            data=data,
        )
        response_text = channel_response.text
        reply_markup = channel_response.reply_markup
    else:
        response_text = await handle_review_callback(
            telegram_user_id=telegram_user_id,
            data=data,
        )
        reply_markup = None
    await answer_callback_query(callback_query_id=callback_query_id, text=response_text[:180])
    if reply_markup:
        await send_message(chat_id=chat_id, text=response_text, reply_markup=reply_markup)
    else:
        await send_message(chat_id=chat_id, text=response_text)
    return True


async def poll_forever(*, poll_interval: float = 1.0) -> None:
    """Poll Telegram updates forever."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    offset = 0
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/getUpdates"
    import httpx

    async with httpx.AsyncClient(timeout=35.0) as client:
        while True:
            response = await client.get(
                url,
                params={"timeout": 30, "offset": offset, "allowed_updates": ["message", "callback_query"]},
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
