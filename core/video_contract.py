from __future__ import annotations

from typing import Any


class VideoContractError(ValueError):
    """Raised when Remotion video data is missing required fields."""


def build_content_contract_v2(
    *,
    niche: str,
    title: str,
    hook: str,
    target_audience: str,
    language: str,
    scenes: list[dict[str, Any]],
    thumbnail_prompt: str,
    youtube_title: str,
    youtube_description: str,
    youtube_tags: list[str],
    duration_target: int,
) -> dict[str, Any]:
    """Build the normalized content contract used before video rendering."""
    return {
        "schema_version": "content_contract_v2",
        "niche": niche,
        "title": title,
        "hook": hook,
        "target_audience": target_audience,
        "language": language,
        "scenes": scenes,
        "thumbnail_prompt": thumbnail_prompt,
        "youtube_title": youtube_title,
        "youtube_description": youtube_description,
        "youtube_tags": youtube_tags,
        "duration_target": duration_target,
    }


def validate_content_contract_v2(payload: dict[str, Any]) -> None:
    """Validate the fields needed to render and later review a content idea."""
    required_text_fields = (
        "schema_version",
        "niche",
        "title",
        "hook",
        "target_audience",
        "language",
        "thumbnail_prompt",
        "youtube_title",
        "youtube_description",
    )
    for field_name in required_text_fields:
        if not str(payload.get(field_name, "")).strip():
            raise VideoContractError(f"{field_name} is required")

    if payload["schema_version"] != "content_contract_v2":
        raise VideoContractError("schema_version must be content_contract_v2")

    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise VideoContractError("scenes must contain at least one scene")

    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise VideoContractError(f"scenes[{index}] must be an object")
        for field_name in ("title", "voiceover", "caption", "image_prompt", "statusText"):
            if not str(scene.get(field_name, "")).strip():
                raise VideoContractError(f"scenes[{index}].{field_name} is required")

    tags = payload.get("youtube_tags")
    if not isinstance(tags, list) or not any(str(tag).strip() for tag in tags):
        raise VideoContractError("youtube_tags must contain at least one tag")

    duration_target = payload.get("duration_target")
    if not isinstance(duration_target, int) or duration_target <= 0:
        raise VideoContractError("duration_target must be a positive integer")


def build_video_data_from_content_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert content contract v2 into Remotion-compatible video data."""
    validate_content_contract_v2(payload)

    cards: list[dict[str, str]] = []
    for index, scene in enumerate(payload["scenes"]):
        cards.append(
            {
                "header": f"SCENE {index + 1}",
                "title": str(scene["title"]),
                "description": str(scene["voiceover"]),
                "imagePath": "images/local-placeholder.svg",
                "statusText": str(scene["statusText"]),
            }
        )

    return {
        "template": "timeline",
        "title": payload["title"],
        "subtitle": payload["hook"],
        "category": payload["niche"],
        "language": payload["language"],
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
        "content_contract": payload,
    }


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
