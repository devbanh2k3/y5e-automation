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
    return {
        "status": "pending_review",
        "task_id": task_id,
        "batch_id": batch_id,
        "review_id": str(result.get("review_id", "")),
        "video_path": str(result.get("video_path", "")),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one task and exit. This is the only mode in v1.",
    )
    return parser


def main() -> int:
    build_parser().parse_args()
    print_json(asyncio.run(process_one_task()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
