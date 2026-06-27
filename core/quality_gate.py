"""Production quality checks before a rendered video enters human review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config import get_settings
from core.video_contract import validate_image_verification_contract_v1, validate_video_data

MIN_IMAGE_QUALITY_SCORE = 0.72


class ProductionQualityGateError(ValueError):
    """Raised when a rendered artifact is not ready for pending review."""


def run_production_quality_gate(
    *,
    topic_id: int,
    video_path: str,
    video_data: dict[str, Any],
    content_contract: dict[str, Any],
    image_verification_contract: dict[str, Any] | None,
    expected_card_layout: str,
) -> dict[str, Any]:
    """Validate production-critical render artifacts before review creation."""
    checks: list[dict[str, str]] = []
    errors: list[str] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "status": "passed" if passed else "failed", "detail": detail})
        if not passed:
            errors.append(f"{name}: {detail}")

    video_file = Path(video_path)
    record(
        "mp4_file",
        video_file.is_file() and video_file.stat().st_size > 0,
        f"{video_path} must exist and be non-empty",
    )

    try:
        validate_video_data(video_data)
        record("video_contract", True, "video_data is valid")
    except Exception as exc:
        record("video_contract", False, str(exc))

    record(
        "content_layout",
        content_contract.get("cardLayout") == expected_card_layout,
        f"content_contract.cardLayout must be {expected_card_layout}",
    )
    record(
        "video_layout",
        video_data.get("cardLayout") == expected_card_layout,
        f"video_data.cardLayout must be {expected_card_layout}",
    )

    cards = video_data.get("cards") if isinstance(video_data.get("cards"), list) else []
    scenes = content_contract.get("scenes") if isinstance(content_contract.get("scenes"), list) else []
    record("scene_count", len(cards) == len(scenes) and len(cards) > 0, "cards must match scenes")

    if image_verification_contract is None:
        record("image_contract", False, "image verification contract is required")
        image_items: list[dict[str, Any]] = []
    else:
        try:
            validate_image_verification_contract_v1(image_verification_contract)
            record("image_contract", True, "image verification contract is valid")
        except Exception as exc:
            record("image_contract", False, str(exc))
        record(
            "image_verified",
            image_verification_contract.get("status") == "verified",
            "image verification status must be verified",
        )
        record(
            "image_count",
            image_verification_contract.get("required_count") == len(cards)
            and image_verification_contract.get("verified_count") == len(cards),
            "verified_count and required_count must match card count",
        )
        image_items = image_verification_contract.get("items", [])
        if not isinstance(image_items, list):
            image_items = []

    topic_dir = get_settings().storage_dir / "topics" / str(topic_id)
    for index, card in enumerate(cards):
        image_path = str(card.get("imagePath", ""))
        expected_image_path = f"images/real_{index}.webp"
        record(
            f"card_{index}_image_path",
            image_path == expected_image_path,
            f"card imagePath must be {expected_image_path}",
        )
        record(
            f"card_{index}_no_placeholder",
            bool(image_path) and "placeholder" not in image_path.lower(),
            "card imagePath must not use placeholder assets",
        )
        record(
            f"card_{index}_country",
            bool(str(card.get("countryCode", "")).strip()),
            "countryCode is required for flag layouts",
        )
        record(
            f"card_{index}_render_image_exists",
            (topic_dir / expected_image_path).is_file(),
            f"{expected_image_path} must exist in topic storage",
        )

    for index, item in enumerate(image_items):
        expected_image_path = f"images/real_{index}.webp"
        record(
            f"image_{index}_scene_index",
            item.get("scene_index") == index,
            f"scene_index must be {index}",
        )
        record(
            f"image_{index}_render_path",
            item.get("render_image_path") == expected_image_path,
            f"render_image_path must be {expected_image_path}",
        )
        quality_score = item.get("quality_score")
        record(
            f"image_{index}_quality_score",
            isinstance(quality_score, int | float) and quality_score >= MIN_IMAGE_QUALITY_SCORE,
            f"quality_score must be at least {MIN_IMAGE_QUALITY_SCORE}",
        )
        record(
            f"image_{index}_content_match",
            item.get("content_match_status") == "passed",
            "content_match_status must be passed",
        )
        record(
            f"image_{index}_human_review",
            item.get("needs_human_review") is False,
            "needs_human_review must be false",
        )

    if errors:
        raise ProductionQualityGateError("; ".join(errors))

    return {
        "schema_version": "quality_gate_v1",
        "status": "passed",
        "required_checks": len(checks),
        "checks": checks,
    }
