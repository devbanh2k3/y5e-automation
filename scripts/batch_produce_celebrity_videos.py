#!/usr/bin/env python3
"""Produce multiple local Celebrity video candidates into pending review."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.produce_celebrity_video import produce


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def summarize_success(*, batch_index: int, result: dict[str, Any]) -> dict[str, Any]:
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
    }


async def produce_batch(
    *,
    count: int,
    language: str,
    card_layout: str,
    write_files: bool,
    stop_on_error: bool,
) -> dict[str, Any]:
    if count < 1:
        raise ValueError("--count must be at least 1")

    items: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    stopped_on_error = False

    for batch_index in range(1, count + 1):
        try:
            result = await produce(
                language=language,
                card_layout=card_layout,
                write_files=write_files,
            )
        except Exception as exc:  # noqa: BLE001 - batch summaries must preserve per-item failures.
            failures.append(
                {
                    "batch_index": batch_index,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                }
            )
            if stop_on_error:
                stopped_on_error = True
                break
            continue

        items.append(summarize_success(batch_index=batch_index, result=result))

    return {
        "status": "completed_with_errors" if failures else "completed",
        "requested_count": count,
        "attempted_count": len(items) + len(failures),
        "success_count": len(items),
        "failure_count": len(failures),
        "stopped_on_error": stopped_on_error,
        "language": language,
        "card_layout": card_layout,
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
