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
    attempt_type: str = "initial",
    duration_profile: str = "standard",
    target_duration: int = 60,
) -> dict[str, Any]:
    return {
        "batch_index": batch_index,
        "attempt_type": attempt_type,
        "status": result.get("status", ""),
        "review_id": result.get("review_id", ""),
        "topic_id": result.get("topic_id", ""),
        "video_path": result.get("video_path", ""),
        "card_layout": result.get("card_layout", ""),
        "duration_profile": result.get("duration_profile", duration_profile),
        "target_duration": result.get("target_duration", target_duration),
        "actual_duration_sec": result.get("actual_duration_sec", result.get("duration_sec", 0)),
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
    max_attempts: int | None = None,
    duration_profile: str = "standard",
    target_duration: int | None = None,
) -> dict[str, Any]:
    if count < 1:
        raise ValueError("--count must be at least 1")
    resolved_target_duration = resolve_duration_target(duration_profile, target_duration)
    attempt_budget = max_attempts if max_attempts is not None else count * 3
    if attempt_budget < count:
        raise ValueError("--max-attempts must be at least --count")

    items: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    stopped_on_error = False
    replacement_count = 0
    retry_count = 0
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
                "attempt_index": 0,
                "batch_index": 0,
                "batch_slot": 0,
                "reservation_id": "",
                "error": str(exc),
                "error_type": exc.__class__.__name__,
                "classification": classify_batch_failure(exc),
                "recovery_action": "no_replacement_available",
                "final_status": "failed",
            }
        )
        slate = []
    queue = [
        {
            "topic": selected_topic,
            "retry_available": True,
            "batch_slot": index + 1,
            "attempt_type": "initial",
        }
        for index, selected_topic in enumerate(slate)
    ]
    attempt_index = 0

    while len(items) < count and attempt_index < attempt_budget and queue:
        attempt = queue.pop(0)
        selected_topic = attempt["topic"]
        attempt_index += 1
        reservation_id = str(selected_topic["reservation_id"])
        try:
            result = await produce(
                language=language,
                card_layout=card_layout,
                write_files=write_files,
                selected_topic=selected_topic,
                duration_profile=duration_profile,
                target_duration=resolved_target_duration,
            )
        except Exception as exc:  # noqa: BLE001 - batch summaries must preserve per-item failures.
            classification = classify_batch_failure(exc)
            action = recovery_action_for(
                classification,
                retry_available=bool(attempt["retry_available"]),
                stop_on_error=stop_on_error,
            )
            if action == "request_replacement" and attempt_index >= attempt_budget:
                action = "attempt_budget_exhausted"
            topic_strategy.repository.mark_failed(
                reservation_id,
                reason=str(exc),
            )
            failures.append(
                {
                    "attempt_index": attempt_index,
                    "batch_index": attempt_index,
                    "batch_slot": attempt["batch_slot"],
                    "reservation_id": reservation_id,
                    "title": selected_topic.get("title", ""),
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                    "classification": classification,
                    "recovery_action": action,
                    "final_status": "failed",
                }
            )
            if action == "stop_on_error":
                stopped_on_error = True
                for pending in queue:
                    pending_topic = pending["topic"]
                    topic_strategy.repository.mark_failed(
                        str(pending_topic["reservation_id"]),
                        reason="batch stopped after production failure",
                    )
                break
            if action == "retry_same_topic":
                retry_count += 1
                queue.insert(
                    0,
                    {
                        "topic": selected_topic,
                        "retry_available": False,
                        "batch_slot": attempt["batch_slot"],
                        "attempt_type": "retry_same_topic",
                    },
                )
            elif action == "request_replacement":
                try:
                    replacement = await topic_strategy.run(
                        count=1,
                        language=language,
                        batch_id=f"{batch_id}-replacement-{attempt_index}",
                    )
                except Exception as replacement_exc:  # noqa: BLE001 - preserve selection failure.
                    failures.append(
                        {
                            "attempt_index": attempt_index,
                            "batch_index": attempt_index,
                            "batch_slot": attempt["batch_slot"],
                            "reservation_id": "",
                            "error": str(replacement_exc),
                            "error_type": replacement_exc.__class__.__name__,
                            "classification": classify_batch_failure(replacement_exc),
                            "recovery_action": "no_replacement_available",
                            "final_status": "failed",
                        }
                    )
                else:
                    replacement_count += 1
                    queue.append(
                        {
                            "topic": replacement[0],
                            "retry_available": True,
                            "batch_slot": attempt["batch_slot"],
                            "attempt_type": "replacement",
                        }
                    )
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
                attempt_type=str(attempt["attempt_type"]),
                duration_profile=duration_profile,
                target_duration=resolved_target_duration,
            )
        )

    unfilled_count = max(0, count - len(items))
    if stopped_on_error:
        status = "stopped_on_error"
    elif len(items) == count and not failures:
        status = "completed"
    elif len(items) == count:
        status = "completed_with_recoveries"
    else:
        status = "incomplete"

    return {
        "status": status,
        "requested_count": count,
        "attempted_count": attempt_index,
        "max_attempts": attempt_budget,
        "success_count": len(items),
        "failure_count": len(failures),
        "replacement_count": replacement_count,
        "retry_count": retry_count,
        "unfilled_count": unfilled_count,
        "stopped_on_error": stopped_on_error,
        "language": language,
        "card_layout": card_layout,
        "duration_profile": duration_profile,
        "target_duration": resolved_target_duration,
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
        "--max-attempts",
        type=int,
        default=None,
        help="Maximum production attempts before leaving the batch incomplete. Defaults to count * 3.",
    )
    parser.add_argument(
        "--duration-profile",
        choices=sorted(DURATION_PROFILE_TARGETS),
        default="standard",
        help="Target duration profile for generated videos.",
    )
    parser.add_argument(
        "--target-duration",
        type=int,
        default=None,
        help="Explicit target duration in seconds. Overrides --duration-profile target.",
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
                max_attempts=args.max_attempts,
                duration_profile=args.duration_profile,
                target_duration=args.target_duration,
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
