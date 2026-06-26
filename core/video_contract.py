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
            "header": "LOCAL 1",
            "title": safe_title,
            "description": "This card proves the Python-to-Remotion contract is valid.",
            "imagePath": "images/local-placeholder.svg",
            "statusText": "FALLBACK",
        },
        {
            "header": "LOCAL 2",
            "title": f"{category} overview",
            "description": "The local render path can run without upstream AI content.",
            "imagePath": "images/local-placeholder.svg",
            "statusText": "CONTRACT",
        },
        {
            "header": "LOCAL 3",
            "title": "Ready for production content",
            "description": "Replace fallback content with generated research and script data later.",
            "imagePath": "images/local-placeholder.svg",
            "statusText": "RENDER",
        },
    ]

    return {
        "template": "timeline",
        "title": safe_title,
        "subtitle": category,
        "category": category,
        "language": language,
        "cards": cards,
        "introCards": [],
        "musicPath": "",
        "sfxPaths": {
            "transition": "",
            "alert": "",
            "reveal": "",
        },
        "logoPath": "images/local-logo.svg",
        "holdDurationFrames": 120,
        "transitionDurationFrames": 15,
    }


def validate_video_data(payload: dict[str, Any]) -> None:
    """Validate the minimal fields required by local render Remotion input."""
    if not str(payload.get("template", "")).strip():
        raise VideoContractError("template is required")
    if not str(payload.get("title", "")).strip():
        raise VideoContractError("title is required")
    if not str(payload.get("language", "")).strip():
        raise VideoContractError("language is required")
    if not str(payload.get("subtitle", "")).strip():
        payload["subtitle"] = payload.get("category", "")

    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise VideoContractError("cards must contain at least one card")

    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise VideoContractError(f"cards[{index}] must be an object")
        if not str(card.get("title", "")).strip():
            raise VideoContractError(f"cards[{index}].title is required")
        card.setdefault("header", f"CARD {index + 1}")
        card.setdefault("description", "")
        card.setdefault("imagePath", "images/local-placeholder.svg")
        card.setdefault("statusText", "")

    payload.setdefault("musicPath", "")
    payload.setdefault("sfxPaths", {"transition": "", "alert": "", "reveal": ""})
    payload.setdefault("logoPath", "images/local-logo.svg")
    payload.setdefault("holdDurationFrames", 120)
    payload.setdefault("transitionDurationFrames", 15)
