#!/usr/bin/env python3
"""Process one fair-scheduled Telegram production task."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core import production_tasks
from agents.topic_strategy_agent import TopicSelectionError, TopicStrategyAgent
from core.ai_resilience import AIJsonFailure
from core.fact_verification import FactVerificationError
from services.telegram_notifications import build_review_keyboard, send_telegram_message
from scripts.produce_celebrity_video import produce

logger = logging.getLogger(__name__)
PRODUCTION_TOPIC_ATTEMPT_BUDGET = 5

FAILURE_LABELS = {
    "transport_exhausted": "Không thể kết nối dịch vụ AI sau nhiều lần thử.",
    "json_exhausted": "AI trả dữ liệu không hợp lệ sau nhiều lần tự sửa.",
    "insufficient_ready_cards": "Không đủ card có dữ liệu và hình ảnh đáng tin cậy để render.",
    "render_failed": "Hệ thống render video không hoàn tất.",
    "production_failed": "Hệ thống không thể hoàn tất video này.",
}


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_production_completion_message(
    *,
    title: str,
    layout: str,
    target_duration: int,
    summary: dict[str, Any] | None = None,
) -> str:
    """Build a review-ready message without exposing internal identifiers."""

    summary = summary or {}
    lines = [
        "Video đã sẵn sàng duyệt",
        f"Tiêu đề: {title or 'Celebrity data video'}",
        f"Bố cục: {layout or 'flag_hero'}",
        f"Thời lượng mục tiêu: {target_duration} giây",
    ]
    target_cards = int(summary.get("target_cards") or 0)
    final_cards = int(summary.get("final_cards") or 0)
    skipped_cards = int(summary.get("skipped_cards") or 0)
    if target_cards and final_cards:
        lines.append(f"Kết quả card: {final_cards}/{target_cards} card đạt chuẩn")
    if skipped_cards:
        lines.append(f"Đã loại an toàn: {skipped_cards} card không đủ độ tin cậy")
    lines.append("Xem preview trước, sau đó approve để chọn kênh upload.")
    return "\n".join(lines)


def build_production_failure_message(exc: Exception) -> str:
    """Map internal exceptions to stable, actionable Telegram text."""

    category = str(getattr(exc, "category", "")).strip()
    message = str(exc).lower()
    if not category and ("render failed" in message or "ffmpeg" in message):
        category = "render_failed"
    if not category:
        category = "production_failed"
    reason = FAILURE_LABELS.get(category, FAILURE_LABELS["production_failed"])
    return (
        "Sản xuất video thất bại\n"
        f"Lý do: {reason}\n"
        "Mở /status để kiểm tra queue hiện tại."
    )


def build_progress_callback(
    *,
    owner_telegram_user_id: int,
    minimum_interval: float = 15.0,
):
    """Return a best-effort, stage-aware Telegram progress callback."""

    last_sent_at = 0.0
    last_stage = ""

    async def report(event: dict[str, Any]) -> None:
        nonlocal last_sent_at, last_stage
        stage = str(event.get("stage") or "")
        now = time.monotonic()
        if stage == last_stage and now - last_sent_at < minimum_interval:
            return
        labels = {
            "entity_planning": "Đang lập danh sách nhân vật",
            "content_writing": "Đang chuẩn bị nội dung",
            "fact_verification": "Đang xác minh dữ liệu",
            "image_verification": "Đang xác minh hình ảnh",
            "finalizing": "Đang hoàn thiện video",
            "render_queued": "Đã xếp hàng render trên máy chủ",
            "rendering_chunks": "Đang render video theo từng phần",
            "final_encoding": "Đang ghép và mã hóa video Full HD",
        }
        label = labels.get(stage, "Đang xử lý video")
        ready = int(event.get("ready") or 0)
        target = int(event.get("target") or 0)
        text = f"{label}: {ready}/{target} card" if target else label
        repairing = int(event.get("repairing") or 0)
        if repairing:
            text += f"\nĐang sửa: {repairing}"
        try:
            await _notify_owner(
                owner_telegram_user_id=owner_telegram_user_id,
                text=text,
            )
        except Exception as exc:
            logger.warning("Telegram progress notification failed: %s", exc)
        last_sent_at = now
        last_stage = stage

    return report


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
                    progress_callback=build_progress_callback(
                        owner_telegram_user_id=owner_telegram_user_id
                    ),
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
            text=build_production_failure_message(exc),
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
        text=build_production_completion_message(
            title=str(result.get("youtube_title") or "Celebrity data video"),
            layout=str(result.get("card_layout") or "flag_hero"),
            target_duration=int(result.get("target_duration") or 0),
            summary=result.get("production_summary")
            if isinstance(result.get("production_summary"), dict)
            else {},
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
    if isinstance(exc, AIJsonFailure) and exc.category == "json_exhausted":
        return True
    message = str(exc).lower()
    return (
        _is_topic_reservation_race(exc)
        or "could not extract valid json from response" in message
        or ("scene " in message and " is not an individual person" in message)
        or "missing verified real images" in message
        or "duplicate celebrity scenes" in message
        or "image verification status must be verified" in message
        or "verified_count and required_count must match card count" in message
        or "ai response does not contain a valid json object" in message
        or ("requires at least" in message and "verified scenes" in message)
        or ("requires at least" in message and "verified facts" in message)
        or ("requires at least" in message and "ready cards" in message)
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
