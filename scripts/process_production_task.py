#!/usr/bin/env python3
"""Process one fair-scheduled Telegram production task."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core import production_tasks
from agents.topic_strategy_agent import TopicSelectionError, TopicStrategyAgent
from core.fact_verification import FactVerificationError
from services.telegram_notifications import build_review_keyboard, send_telegram_message
from scripts.produce_celebrity_video import produce

logger = logging.getLogger(__name__)
PRODUCTION_TOPIC_ATTEMPT_BUDGET = 5


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
    selected_topic: dict[str, Any] | None = None
    topic_agent: TopicStrategyAgent | None = None
    result: dict[str, Any] | None = None
    last_error: Exception | None = None
    try:
        topic_agent = TopicStrategyAgent()
        for attempt_index in range(1, PRODUCTION_TOPIC_ATTEMPT_BUDGET + 1):
            try:
                selected_topic = (
                    await topic_agent.run(
                        count=1,
                        language=str(task.get("language") or "en"),
                        batch_id=f"{batch_id}-{task_id}-attempt-{attempt_index}",
                    )
                )[0]
            except TopicSelectionError as exc:
                if not _is_topic_reservation_race(exc) or attempt_index == PRODUCTION_TOPIC_ATTEMPT_BUDGET:
                    raise
                last_error = exc
                logger.info(
                    "Retrying topic reservation race for task %s after attempt %s: %s",
                    task_id,
                    attempt_index,
                    exc,
                )
                continue
            try:
                result = await produce(
                    language=str(task.get("language") or "en"),
                    card_layout=str(task.get("card_layout") or "flag_hero"),
                    write_files=True,
                    selected_topic=selected_topic,
                    duration_profile="standard",
                    target_duration=int(task.get("target_duration") or 60),
                )
                break
            except Exception as exc:
                if not _should_replace_topic(exc):
                    raise
                last_error = exc
                _mark_reserved_topic_failed(
                    topic_agent=topic_agent,
                    selected_topic=selected_topic,
                    reason=str(exc),
                )
                if attempt_index == PRODUCTION_TOPIC_ATTEMPT_BUDGET:
                    selected_topic = None
                    raise
                logger.info(
                    "Replacing fact-rejected topic for task %s after attempt %s: %s",
                    task_id,
                    attempt_index,
                    exc,
                )
                selected_topic = None
        if result is None:
            raise RuntimeError(str(last_error or "production did not return a result"))
    except Exception as exc:  # noqa: BLE001 - worker must preserve task failure.
        await production_tasks.mark_task_failed(
            task_id=task_id,
            batch_id=batch_id,
            error=str(exc),
        )
        _mark_reserved_topic_failed(topic_agent=topic_agent, selected_topic=selected_topic, reason=str(exc))
        await _notify_owner(
            owner_telegram_user_id=owner_telegram_user_id,
            text=(
                "Sản xuất video thất bại\n"
                f"Lý do: {str(exc)[:500]}\n"
                "Mở /status để kiểm tra queue hiện tại."
            ),
        )
        return {
            "status": "failed",
            "task_id": task_id,
            "batch_id": batch_id,
            "error": str(exc),
        }

    _mark_reserved_topic_produced(
        topic_agent=topic_agent,
        selected_topic=selected_topic,
        topic_id=str(result.get("topic_id", "")),
    )
    await production_tasks.mark_task_pending_review(
        task_id=task_id,
        batch_id=batch_id,
        review_id=str(result.get("review_id", "")),
        topic_id=str(result.get("topic_id", "")),
        video_path=str(result.get("video_path", "")),
    )
    await _notify_owner_with_keyboard(
        owner_telegram_user_id=owner_telegram_user_id,
        review_id=str(result.get("review_id", "")),
        text=(
            "Video đã sẵn sàng duyệt\n"
            f"Tiêu đề: {str(result.get('youtube_title') or 'Celebrity data video')}\n"
            f"Layout: {str(result.get('card_layout') or '')}\n"
            f"Thời lượng mục tiêu: {int(result.get('target_duration') or 0)} giây\n"
            "Xem preview trước, sau đó approve để chọn kênh upload."
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
    except Exception as exc:
        logger.warning("Telegram notification failed: %s", exc)
        return False


async def _notify_owner_with_keyboard(*, owner_telegram_user_id: int, review_id: str, text: str) -> bool:
    """Best-effort review notification with inline review buttons."""
    chat_id = await production_tasks.get_notification_chat_id(owner_telegram_user_id)
    keyboard = build_review_keyboard(review_id) if review_id else None
    try:
        return await send_telegram_message(chat_id=chat_id, text=text, reply_markup=keyboard)
    except Exception as exc:
        logger.warning("Telegram review notification failed: %s", exc)
        return False


def _mark_reserved_topic_produced(
    *,
    topic_agent: TopicStrategyAgent | None,
    selected_topic: dict[str, Any] | None,
    topic_id: str,
) -> None:
    if not topic_agent or not selected_topic:
        return
    try:
        topic_agent.repository.mark_produced(
            str(selected_topic.get("reservation_id", "")),
            topic_id=topic_id,
        )
    except Exception as exc:
        logger.warning("Could not mark topic as produced: %s", exc)


def _mark_reserved_topic_failed(
    *,
    topic_agent: TopicStrategyAgent | None,
    selected_topic: dict[str, Any] | None,
    reason: str,
) -> None:
    if not topic_agent or not selected_topic:
        return
    try:
        topic_agent.repository.mark_failed(
            str(selected_topic.get("reservation_id", "")),
            reason=reason[:1000],
        )
    except Exception as exc:
        logger.warning("Could not mark topic as failed: %s", exc)


def _should_replace_topic(exc: Exception) -> bool:
    """Return true for topic-specific data failures that a new topic can solve."""
    if isinstance(exc, FactVerificationError):
        return True
    message = str(exc).lower()
    return (
        "missing verified real images" in message
        or "image verification status must be verified" in message
        or "verified_count and required_count must match card count" in message
    )


def _is_topic_reservation_race(exc: Exception) -> bool:
    return "reservations changed concurrently" in str(exc).lower()


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
