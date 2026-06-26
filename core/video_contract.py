from __future__ import annotations

from typing import Any


class VideoContractError(ValueError):
    """Raised when Remotion video data is missing required fields."""


def build_local_render_video_data(
    *,
    title: str,
    category: str,
    language: str,
) -> dict[str, Any]:
    """Build a minimal Remotion-compatible payload for local render validation."""
    safe_title = title.strip() or f"{category} local render"
    cards = [
        {
            "title": safe_title,
            "subtitle": "Local render validation",
            "description": "This card proves the Python-to-Remotion contract is valid.",
            "imagePath": "",
        },
        {
            "title": f"{category} overview",
            "subtitle": "Fallback section",
            "description": "The local render path can run without upstream AI content.",
            "imagePath": "",
        },
        {
            "title": "Ready for production content",
            "subtitle": language,
            "description": "Replace fallback content with generated research and script data later.",
            "imagePath": "",
        },
    ]

    return {
        "template": "timeline",
        "title": safe_title,
        "category": category,
        "language": language,
        "cards": cards,
        "introCards": [],
        "musicPath": "",
        "logoPath": "",
    }


def validate_video_data(payload: dict[str, Any]) -> None:
    """Validate the minimal fields required by local render Remotion input."""
    if not str(payload.get("template", "")).strip():
        raise VideoContractError("template is required")
    if not str(payload.get("title", "")).strip():
        raise VideoContractError("title is required")
    if not str(payload.get("language", "")).strip():
        raise VideoContractError("language is required")

    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise VideoContractError("cards must contain at least one card")

    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise VideoContractError(f"cards[{index}] must be an object")
        if not str(card.get("title", "")).strip():
            raise VideoContractError(f"cards[{index}].title is required")
        card.setdefault("subtitle", "")
        card.setdefault("description", "")
        card.setdefault("imagePath", "")

    payload.setdefault("musicPath", "")
    payload.setdefault("logoPath", "")
