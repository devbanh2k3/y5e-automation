#!/usr/bin/env python3
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

from core.reviews import approve_review, get_review, list_reviews, reject_review


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def summarize_review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": review.get("review_id", ""),
        "status": review.get("status", ""),
        "title": (review.get("youtube") or {}).get("title", ""),
        "topic_id": (review.get("video") or {}).get("topic_id", ""),
        "video_path": (review.get("video") or {}).get("file_path", ""),
        "created_at": review.get("created_at", ""),
    }


async def run(args: argparse.Namespace) -> int:
    if args.command == "list":
        reviews = await list_reviews(status=args.status, limit=args.limit)
        print_json({"reviews": [summarize_review(review) for review in reviews]})
        return 0
    if args.command == "show":
        print_json(await get_review(args.review_id))
        return 0
    if args.command == "approve":
        print_json(await approve_review(args.review_id, notes=args.notes))
        return 0
    if args.command == "reject":
        print_json(
            await reject_review(
                args.review_id,
                reason=args.reason,
                scenes=args.scene,
                notes=args.notes,
            )
        )
        return 0
    raise ValueError(f"unsupported command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review rendered video artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--status", default="pending_review")
    list_parser.add_argument("--limit", type=int, default=10)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("review_id")

    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("review_id")
    approve_parser.add_argument("--notes", default="")

    reject_parser = subparsers.add_parser("reject")
    reject_parser.add_argument("review_id")
    reject_parser.add_argument("--reason", required=True)
    reject_parser.add_argument("--scene", type=int, action="append", default=[])
    reject_parser.add_argument("--notes", default="")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyError as exc:
        print(f"Review {exc.args[0]} not found", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
