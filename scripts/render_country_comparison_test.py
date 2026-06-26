"""Render a local country-comparison-comedy test video."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agents.content_agent import ContentAgent
from agents.pipeline import Pipeline
from core.config import get_settings
from core.video_contract import build_video_data_from_content_contract


def build_scene_svg(*, country_label: str, reaction: str, index: int) -> str:
    colors = ["#1d4ed8", "#be123c", "#047857", "#7c3aed", "#c2410c"]
    accent = colors[index % len(colors)]
    return "\n".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">',
            '<rect width="1200" height="800" fill="#101827"/>',
            f'<rect x="0" y="0" width="1200" height="210" fill="{accent}"/>',
            f'<text x="600" y="132" text-anchor="middle" fill="#ffffff" font-family="Arial, sans-serif" font-size="70" font-weight="900">{country_label}</text>',
            '<rect x="90" y="280" width="1020" height="360" rx="28" fill="#f8fafc"/>',
            '<circle cx="360" cy="455" r="92" fill="#fbbf24"/>',
            '<circle cx="840" cy="455" r="92" fill="#38bdf8"/>',
            '<path d="M322 470q38 42 76 0" stroke="#111827" stroke-width="16" fill="none" stroke-linecap="round"/>',
            '<path d="M802 470q38 42 76 0" stroke="#111827" stroke-width="16" fill="none" stroke-linecap="round"/>',
            f'<text x="600" y="700" text-anchor="middle" fill="#ffffff" font-family="Arial, sans-serif" font-size="54" font-weight="900">{reaction}</text>',
            "</svg>",
        ]
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", choices=["flag_hero", "split_data", "classic"], default="flag_hero")
    parser.add_argument("--topic-id", type=int, default=2)
    parser.add_argument("--out-name", default="")
    args = parser.parse_args()

    content_contract = await ContentAgent().run(
        niche="country_comparison_comedy",
        language="vi",
        subject="parents reward good grades",
    )
    video_data = build_video_data_from_content_contract(content_contract)
    video_data["template"] = "timeline"
    video_data["cardLayout"] = args.layout

    settings = get_settings()
    topic_dir = settings.storage_dir / "topics" / str(args.topic_id)
    images_dir = topic_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    for index, card in enumerate(video_data["cards"]):
        image_name = f"country_scene_{index}.svg"
        image_path = images_dir / image_name
        image_path.write_text(
            build_scene_svg(
                country_label=str(card.get("countryLabel", "")),
                reaction=str(card.get("metricValue", "")),
                index=index,
            )
        )
        card["imagePath"] = f"images/{image_name}"

    result = await Pipeline()._render_local_video(topic_id=args.topic_id, video_data=video_data)
    output_path = Path(result["file_path"])
    if args.out_name:
        target_path = output_path.with_name(args.out_name)
        target_path.write_bytes(output_path.read_bytes())
        output_path = target_path

    print(
        json.dumps(
            {
                "file_path": str(output_path),
                "template": video_data["template"],
                "cardLayout": video_data["cardLayout"],
                "cards": len(video_data["cards"]),
                "first_card": {
                    "countryCode": video_data["cards"][0].get("countryCode"),
                    "countryLabel": video_data["cards"][0].get("countryLabel"),
                    "metricValue": video_data["cards"][0].get("metricValue"),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
