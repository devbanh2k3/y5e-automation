#!/usr/bin/env python3
"""Process one fair-scheduled Telegram production task."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core import production_tasks
from services.telegram_notifications import send_telegram_message
from scripts.produce_celebrity_video import produce


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def process_one_task() -> dict[str, Any]:
    """Claim and process one queued production task."""
    task = await production_tasks.claim_next_fair_task()
    if not task:
        return {"status": "idle"}

    task_id = str(task["task_id"])
    batch_id = str(task["batch_id"])
    owner_telegram_user_id = int(task["owner_telegram_user_id"])
    try:
        result = await produce(
            language=str(task.get("language") or "en"),
            card_layout=str(task.get("card_layout") or "flag_hero"),
            write_files=True,
            selected_topic=None,
            duration_profile="standard",
            target_duration=60,
        )
    except Exception as exc:  # noqa: BLE001 - worker must preserve task failure.
        await production_tasks.mark_task_failed(
            task_id=task_id,
            batch_id=batch_id,
            error=str(exc),
        )
        await _notify_owner(
            owner_telegram_user_id=owner_telegram_user_id,
            text=(
                "Production task failed.\n"
                f"Batch: {batch_id}\n"
                f"Task: {task_id}\n"
                f"Error: {str(exc)[:500]}"
            ),
        )
        return {
            "status": "failed",
            "task_id": task_id,
            "batch_id": batch_id,
            "error": str(exc),
        }

    await production_tasks.mark_task_pending_review(
        task_id=task_id,
        batch_id=batch_id,
        review_id=str(result.get("review_id", "")),
        topic_id=str(result.get("topic_id", "")),
        video_path=str(result.get("video_path", "")),
    )
    await _notify_owner(
        owner_telegram_user_id=owner_telegram_user_id,
        text=(
            "Video ready for review.\n"
            f"Batch: {batch_id}\n"
            f"Task: {task_id}\n"
            f"Review: {str(result.get('review_id', ''))}\n"
            f"Video: {str(result.get('video_path', ''))}"
        ),
    )
    return {
        "status": "pending_review",
        "task_id": task_id,
        "batch_id": batch_id,
        "review_id": str(result.get("review_id", "")),
        "video_path": str(result.get("video_path", "")),
    }


async def _notify_owner(*, owner_telegram_user_id: int, text: str) -> bool:
    """Best-effort notification; render status must not depend on Telegram."""
    chat_id = await production_tasks.get_notification_chat_id(owner_telegram_user_id)
    try:
        return await send_telegram_message(chat_id=chat_id, text=text)
    except Exception:
        return False


async def process_forever(*, idle_sleep: float) -> None:
    """Continuously process fair-scheduled production tasks."""
    while True:
        result = await process_one_task()
        print_json(result)
        if result.get("status") == "idle":
            await asyncio.sleep(idle_sleep)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one task and exit.",
    )
    parser.add_argument("--loop", action="store_true", help="Keep processing tasks forever.")
    parser.add_argument("--idle-sleep", type=float, default=10.0, help="Seconds to wait when queue is idle.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.loop:
        asyncio.run(process_forever(idle_sleep=args.idle_sleep))
        return 0
    print_json(asyncio.run(process_one_task()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
