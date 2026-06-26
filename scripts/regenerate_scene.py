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

from agents.pipeline import Pipeline
from agents.real_image_agent import RealImageAgent
from core.reviews import append_review_event, get_review, save_review, utc_now
from core.video_contract import (
    apply_verified_images_to_video_data,
    build_video_data_from_content_contract,
    validate_video_data,
)


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def regenerate_wrong_image_scene(
    review_id: str,
    *,
    scene_index: int,
    rerender: bool = True,
) -> dict[str, Any]:
    review = await get_review(review_id)
    content_contract = review.get("content_contract") or {}
    scenes = content_contract.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("review content_contract.scenes is required")
    if scene_index < 0 or scene_index >= len(scenes):
        raise ValueError("scene index is outside content contract")

    image_contract = review.get("image_verification_contract") or {}
    items = image_contract.get("items")
    if not isinstance(items, list) or scene_index >= len(items):
        raise ValueError("scene index is outside image verification contract")

    topic_id = int((review.get("video") or {}).get("topic_id") or image_contract.get("topic_id") or 0)
    if topic_id <= 0:
        raise ValueError("review topic_id is required")

    one_scene_contract = dict(content_contract)
    one_scene_contract["scenes"] = [scenes[scene_index]]
    regenerated = await RealImageAgent().run_for_content_contract(
        topic_id=topic_id,
        content_contract=one_scene_contract,
        strict=True,
    )
    regenerated_item = dict(regenerated["items"][0])
    regenerated_item["scene_index"] = scene_index

    updated_items = [dict(item) for item in items]
    updated_items[scene_index] = regenerated_item

    image_contract = dict(image_contract)
    image_contract["items"] = updated_items
    image_contract["verified_count"] = sum(1 for item in updated_items if item.get("status") == "verified")
    image_contract["required_count"] = len(updated_items)
    image_contract["status"] = (
        "verified"
        if image_contract["verified_count"] == image_contract["required_count"]
        else "pending_review"
    )

    review["image_verification_contract"] = image_contract
    append_review_event(
        review,
        event="scene_regenerated",
        reason="wrong_image",
        scenes=[scene_index],
        notes="regenerated wrong-image scene",
    )

    if rerender:
        video_data = build_video_data_from_content_contract(content_contract)
        video_data = apply_verified_images_to_video_data(video_data, image_contract)
        validate_video_data(video_data)
        rerender_count = sum(
            1 for event in review.get("review_events", []) if event.get("event") == "video_rerendered"
        )
        render_result = await Pipeline()._render_local_video(
            topic_id=topic_id,
            video_data=video_data,
            output_filename=f"final_video_r{rerender_count + 2}.mp4",
        )
        review["status"] = "pending_review"
        review["video"] = {
            **(review.get("video") or {}),
            "topic_id": topic_id,
            "video_id": render_result["video_id"],
            "file_path": render_result["file_path"],
            "duration_sec": render_result.get("duration_sec", 0),
            "status": render_result["status"],
        }
        append_review_event(
            review,
            event="video_rerendered",
            reason="wrong_image",
            scenes=[scene_index],
            notes=f"rerendered video after regenerating scene {scene_index}",
        )

    review["updated_at"] = utc_now()
    await save_review(review)
    return review


async def run(args: argparse.Namespace) -> int:
    if args.reason != "wrong_image":
        raise ValueError("only wrong_image regeneration is supported in this MVP")
    print_json(
        await regenerate_wrong_image_scene(
            args.review_id,
            scene_index=args.scene,
            rerender=not args.no_rerender,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenerate one scene in a review artifact.")
    parser.add_argument("review_id")
    parser.add_argument("--scene", type=int, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument(
        "--no-rerender",
        action="store_true",
        help="Regenerate image metadata only and skip MP4 rerender.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
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
