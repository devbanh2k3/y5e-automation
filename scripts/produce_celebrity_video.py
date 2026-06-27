#!/usr/bin/env python3
"""Produce one local Celebrity video candidate and place it in pending review."""

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

from agents.pipeline import Pipeline
from core.reviews import get_review


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def write_artifacts(*, result: dict[str, Any], review: dict[str, Any]) -> dict[str, str]:
    video_path = Path(str(result["file_path"])).resolve()
    artifact_dir = video_path.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)

    review_path = artifact_dir / "review.json"
    content_contract_path = artifact_dir / "content_contract.json"
    fact_verification_contract_path = artifact_dir / "fact_verification_contract.json"
    image_verification_contract_path = artifact_dir / "image_verification_contract.json"
    quality_gate_path = artifact_dir / "quality_gate.json"

    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2))
    content_contract_path.write_text(
        json.dumps(review.get("content_contract", {}), ensure_ascii=False, indent=2)
    )
    fact_verification_contract_path.write_text(
        json.dumps(
            review.get(
                "fact_verification_contract",
                result.get("fact_verification_contract", {}),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    image_verification_contract_path.write_text(
        json.dumps(review.get("image_verification_contract", {}), ensure_ascii=False, indent=2)
    )
    quality_gate_path.write_text(
        json.dumps(review.get("quality_gate", result.get("quality_gate", {})), ensure_ascii=False, indent=2)
    )

    return {
        "review_path": str(review_path),
        "content_contract_path": str(content_contract_path),
        "fact_verification_contract_path": str(fact_verification_contract_path),
        "image_verification_contract_path": str(image_verification_contract_path),
        "quality_gate_path": str(quality_gate_path),
    }


def build_next_commands(review_id: str) -> dict[str, str]:
    return {
        "show_review": f"python3 scripts/review_video.py show {review_id}",
        "approve": f'python3 scripts/review_video.py approve {review_id} --notes "ok"',
        "reject_wrong_image": (
            f'python3 scripts/review_video.py reject {review_id} '
            '--reason wrong_image --scene <scene_index> --notes "wrong image"'
        ),
        "regenerate_wrong_image": (
            f"python3 scripts/regenerate_scene.py {review_id} "
            "--scene <scene_index> --reason wrong_image"
        ),
    }


async def produce(
    *,
    language: str,
    card_layout: str = "flag_hero",
    write_files: bool = True,
    selected_topic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await Pipeline().run_local_render(
        category="Celebrity",
        language=language,
        card_layout=card_layout,
        selected_topic=selected_topic,
    )
    if result.get("review_status") != "pending_review":
        raise RuntimeError(f"expected pending_review, got {result.get('review_status')}")

    review_id = str(result.get("review_id", ""))
    if not review_id:
        raise RuntimeError("celebrity render completed without review_id")

    review = await get_review(review_id)
    artifacts = write_artifacts(result=result, review=review) if write_files else {}

    return {
        "status": "pending_review",
        "review_id": review_id,
        "topic_id": result["topic_id"],
        "video_path": str(Path(str(result["file_path"])).resolve()),
        "card_layout": card_layout,
        "fact_verification_contract": result.get("fact_verification_contract", {}),
        "quality_gate": result.get("quality_gate", {}),
        "youtube_title": result.get("youtube_title", ""),
        "artifacts": artifacts,
        "next_commands": build_next_commands(review_id),
        "selected_topic": result.get("selected_topic", selected_topic),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="vi")
    parser.add_argument(
        "--card-layout",
        choices=["split_data", "flag_hero", "classic"],
        default="flag_hero",
        help="Card layout inside the existing timeline template.",
    )
    parser.add_argument(
        "--no-write-artifacts",
        action="store_true",
        help="Skip writing review.json and contract snapshots next to the MP4.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = asyncio.run(
        produce(
            language=args.language,
            card_layout=args.card_layout,
            write_files=not args.no_write_artifacts,
        )
    )
    print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
