#!/usr/bin/env python3
"""Produce multiple local Celebrity video candidates into pending review."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agents.topic_strategy_agent import TopicSelectionError, TopicStrategyAgent
from core.fact_verification import FactVerificationError
from core.video_contract import VideoContractError
from scripts.produce_celebrity_video import produce

DURATION_PROFILE_TARGETS = {
    "short": 40,
    "standard": 60,
    "long": 90,
}


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def resolve_duration_target(duration_profile: str, target_duration: int | None) -> int:
    if target_duration is not None:
        if target_duration < 15:
            raise ValueError("--target-duration must be at least 15 seconds")
        return target_duration
    return DURATION_PROFILE_TARGETS[duration_profile]


def classify_batch_failure(exc: Exception) -> str:
    message = str(exc).lower()
    if isinstance(exc, TopicSelectionError):
        return "topic_selection_failed"
    if isinstance(exc, FactVerificationError):
        return "fact_rejected"
    if isinstance(exc, VideoContractError):
        if any(
            marker in message
            for marker in (
                "factclaim",
                "factvalue",
                "factunit",
                "factasof",
                "factcontext",
                "countrycode",
                "is required",
            )
        ):
            return "repairable_contract"
        return "unknown"
    if "image" in message or "photo" in message or "wikimedia" in message:
        return "image_failed"
    if "render" in message or "remotion" in message or "ffmpeg" in message:
        return "render_failed"
    return "unknown"


def recovery_action_for(
    classification: str,
    *,
    retry_available: bool,
    stop_on_error: bool,
) -> str:
    if stop_on_error:
        return "stop_on_error"
    if classification in {"repairable_contract", "render_failed"} and retry_available:
        return "retry_same_topic"
    if classification == "topic_selection_failed":
        return "no_replacement_available"
    return "request_replacement"


def summarize_success(
    *,
    batch_index: int,
    result: dict[str, Any],
    selected_topic: dict[str, Any],
) -> dict[str, Any]:
    return {
        "batch_index": batch_index,
        "status": result.get("status", ""),
        "review_id": result.get("review_id", ""),
        "topic_id": result.get("topic_id", ""),
        "video_path": result.get("video_path", ""),
        "card_layout": result.get("card_layout", ""),
        "youtube_title": result.get("youtube_title", ""),
        "quality_gate": result.get("quality_gate", {}),
        "artifacts": result.get("artifacts", {}),
        "next_commands": result.get("next_commands", {}),
        "topic_strategy": {
            "reservation_id": selected_topic.get("reservation_id", ""),
            "title": selected_topic.get("title", ""),
            "category": selected_topic.get("category", ""),
            "angle": selected_topic.get("angle", ""),
            "metric_label": selected_topic.get("metric_label", ""),
            "score_total": selected_topic.get("score_total", 0),
            "score_breakdown": selected_topic.get("score_breakdown", {}),
            "selection_reason": selected_topic.get("selection_reason", ""),
        },
    }


async def produce_batch(
    *,
    count: int,
    language: str,
    card_layout: str,
    write_files: bool,
    stop_on_error: bool,
    strategy: TopicStrategyAgent | None = None,
) -> dict[str, Any]:
    if count < 1:
        raise ValueError("--count must be at least 1")

    items: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    stopped_on_error = False
    batch_id = str(uuid4())
    topic_strategy = strategy or TopicStrategyAgent()
    try:
        slate = await topic_strategy.run(
            count=count,
            language=language,
            batch_id=batch_id,
        )
    except Exception as exc:  # noqa: BLE001 - return structured selection failures.
        failures.append(
            {
                "batch_index": 0,
                "reservation_id": "",
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            }
        )
        slate = []
    queue = [(selected_topic, True) for selected_topic in slate]
    attempt_index = 0

    while queue:
        selected_topic, can_replace = queue.pop(0)
        attempt_index += 1
        reservation_id = str(selected_topic["reservation_id"])
        try:
            result = await produce(
                language=language,
                card_layout=card_layout,
                write_files=write_files,
                selected_topic=selected_topic,
            )
        except Exception as exc:  # noqa: BLE001 - batch summaries must preserve per-item failures.
            topic_strategy.repository.mark_failed(
                reservation_id,
                reason=str(exc),
            )
            failures.append(
                {
                    "batch_index": attempt_index,
                    "reservation_id": reservation_id,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                }
            )
            if stop_on_error:
                stopped_on_error = True
                for pending_topic, _ in queue:
                    topic_strategy.repository.mark_failed(
                        str(pending_topic["reservation_id"]),
                        reason="batch stopped after production failure",
                    )
                break
            if can_replace:
                try:
                    replacement = await topic_strategy.run(
                        count=1,
                        language=language,
                        batch_id=f"{batch_id}-replacement-{attempt_index}",
                    )
                except Exception as replacement_exc:  # noqa: BLE001 - preserve selection failure.
                    failures.append(
                        {
                            "batch_index": attempt_index,
                            "reservation_id": "",
                            "error": str(replacement_exc),
                            "error_type": replacement_exc.__class__.__name__,
                        }
                    )
                else:
                    queue.append((replacement[0], False))
            continue

        topic_strategy.repository.mark_produced(
            reservation_id,
            topic_id=str(result["topic_id"]),
        )
        items.append(
            summarize_success(
                batch_index=attempt_index,
                result=result,
                selected_topic=selected_topic,
            )
        )

    return {
        "status": "completed_with_errors" if failures else "completed",
        "requested_count": count,
        "attempted_count": attempt_index,
        "success_count": len(items),
        "failure_count": len(failures),
        "stopped_on_error": stopped_on_error,
        "language": language,
        "card_layout": card_layout,
        "batch_id": batch_id,
        "items": items,
        "failures": failures,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of Celebrity video candidates to produce.",
    )
    parser.add_argument("--language", default="en")
    parser.add_argument(
        "--card-layout",
        choices=["split_data", "flag_hero", "classic"],
        default="flag_hero",
        help="Card layout inside the existing timeline template.",
    )
    parser.add_argument(
        "--no-write-artifacts",
        action="store_true",
        help="Skip writing review.json and contract snapshots next to each MP4.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop the batch at the first failed video candidate.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(
            produce_batch(
                count=args.count,
                language=args.language,
                card_layout=args.card_layout,
                write_files=not args.no_write_artifacts,
                stop_on_error=args.stop_on_error,
            )
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print_json(summary)
    if args.stop_on_error and summary["failure_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
