from __future__ import annotations

import re
from typing import Any

import pycountry


class VideoContractError(ValueError):
    """Raised when Remotion video data is missing required fields."""


COUNTRY_LABEL_ALIASES = {
    "BB": "BARBADOS",
    "CA": "CANADA",
    "IE": "IRELAND",
    "GB": "UNITED KINGDOM",
    "US": "UNITED STATES",
}

CONTENT_FORMATS = {
    "ranking",
    "count_comparison",
    "timeline",
    "record_comparison",
    "before_after",
    "fact_collection",
    "binary_comparison",
}

RENDER_FPS = 30
RENDER_INTRO_DURATION_FRAMES = 90
RENDER_OUTRO_DURATION_FRAMES = 150
DEFAULT_HOLD_DURATION_FRAMES = 120
DEFAULT_TRANSITION_DURATION_FRAMES = 15
MIN_HOLD_DURATION_FRAMES = 30


def calculate_hold_duration_frames(
    *,
    duration_target: int,
    card_count: int,
    transition_duration_frames: int = DEFAULT_TRANSITION_DURATION_FRAMES,
) -> int:
    """Return per-card hold frames needed to approach the requested duration."""
    if card_count < 1:
        raise VideoContractError("card_count must be at least 1")
    available_frames = (
        duration_target * RENDER_FPS
        - RENDER_INTRO_DURATION_FRAMES
        - RENDER_OUTRO_DURATION_FRAMES
        - max(0, card_count - 1) * transition_duration_frames
    )
    return max(MIN_HOLD_DURATION_FRAMES, round(available_frames / card_count))


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
    cardLayout: str = "classic",
    contentFormat: str | None = None,
    metricScope: str = "",
    timeScope: str = "",
) -> dict[str, Any]:
    """Build the normalized content contract used before video rendering."""
    contract = {
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
        "cardLayout": cardLayout,
    }
    if contentFormat is not None:
        contract.update(
            {
                "contentFormat": contentFormat,
                "metricScope": metricScope,
                "timeScope": timeScope,
            }
        )
    return contract


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

    explicit_format = "contentFormat" in payload
    content_format = str(payload.get("contentFormat", "ranking"))
    if content_format not in CONTENT_FORMATS:
        raise VideoContractError("contentFormat is invalid")
    if explicit_format:
        for field_name in ("metricScope", "timeScope"):
            if not str(payload.get(field_name, "")).strip():
                raise VideoContractError(f"{field_name} is required")

    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise VideoContractError("scenes must contain at least one scene")

    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise VideoContractError(f"scenes[{index}] must be an object")
        for field_name in ("title", "voiceover", "caption", "image_prompt", "statusText"):
            if not str(scene.get(field_name, "")).strip():
                raise VideoContractError(f"scenes[{index}].{field_name} is required")
        if explicit_format:
            for field_name in (
                "factClaim",
                "factValue",
                "factUnit",
                "factAsOf",
                "factContext",
            ):
                if not str(scene.get(field_name, "")).strip():
                    raise VideoContractError(
                        f"scenes[{index}].{field_name} is required"
                    )
        if scene.get("countryCode") or scene.get("countryLabel"):
            validate_country_metadata(scene, index=index)

    tags = payload.get("youtube_tags")
    if not isinstance(tags, list) or not any(str(tag).strip() for tag in tags):
        raise VideoContractError("youtube_tags must contain at least one tag")

    duration_target = payload.get("duration_target")
    if not isinstance(duration_target, int) or duration_target <= 0:
        raise VideoContractError("duration_target must be a positive integer")


def build_image_verification_contract_v1(
    *,
    topic_id: int,
    items: list[dict[str, Any]],
    source_policy: str = "wikimedia_commons_strict",
) -> dict[str, Any]:
    verified_count = sum(1 for item in items if item.get("status") == "verified")
    status = "verified" if items and verified_count == len(items) else "pending_review"
    return {
        "schema_version": "image_verification_contract_v1",
        "topic_id": topic_id,
        "source_policy": source_policy,
        "required_count": len(items),
        "verified_count": verified_count,
        "status": status,
        "items": items,
    }


def validate_image_verification_contract_v1(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "image_verification_contract_v1":
        raise VideoContractError("schema_version must be image_verification_contract_v1")
    if payload.get("source_policy") != "wikimedia_commons_strict":
        raise VideoContractError("source_policy must be wikimedia_commons_strict")
    if not isinstance(payload.get("topic_id"), int) or payload["topic_id"] <= 0:
        raise VideoContractError("topic_id must be a positive integer")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise VideoContractError("items must contain at least one image verification item")

    verified_count = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise VideoContractError(f"items[{index}] must be an object")
        for field_name in ("scene_index", "person_name", "expected_title", "status", "confidence"):
            if field_name == "scene_index":
                if not isinstance(item.get(field_name), int) or item[field_name] < 0:
                    raise VideoContractError(
                        f"items[{index}].scene_index must be a non-negative integer"
                    )
            elif field_name == "confidence":
                confidence = item.get(field_name)
                if not isinstance(confidence, int | float) or confidence < 0 or confidence > 1:
                    raise VideoContractError(f"items[{index}].confidence must be between 0 and 1")
            elif not str(item.get(field_name, "")).strip():
                raise VideoContractError(f"items[{index}].{field_name} is required")

        status = item["status"]
        if status not in {"verified", "missing_image", "rejected"}:
            raise VideoContractError(f"items[{index}].status is invalid")

        if status == "verified":
            verified_count += 1
            for field_name in (
                "local_path",
                "render_image_path",
                "source_url",
                "image_url",
                "license",
                "attribution",
            ):
                if not str(item.get(field_name, "")).strip():
                    raise VideoContractError(f"items[{index}].{field_name} is required")
            if str(item.get("reject_reason", "")):
                raise VideoContractError(
                    f"items[{index}].reject_reason must be empty for verified images"
                )
        elif not str(item.get("reject_reason", "")).strip():
            raise VideoContractError(f"items[{index}].reject_reason is required")

    if payload.get("required_count") != len(items):
        raise VideoContractError("required_count must equal item count")
    if payload.get("verified_count") != verified_count:
        raise VideoContractError("verified_count must equal verified item count")

    expected_status = "verified" if verified_count == len(items) else "pending_review"
    if payload.get("status") != expected_status:
        raise VideoContractError(f"status must be {expected_status}")


def build_video_data_from_content_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert content contract v2 into Remotion-compatible video data."""
    validate_content_contract_v2(payload)

    content_format = str(payload.get("contentFormat", "ranking"))
    cards: list[dict[str, str]] = []
    for index, scene in enumerate(payload["scenes"]):
        cards.append(
            {
                "header": build_card_header(
                    scene=scene,
                    content_format=content_format,
                    index=index,
                ),
                "title": str(scene["title"]),
                "description": str(scene["voiceover"]),
                "imagePath": "images/local-placeholder.svg",
                "countryCode": normalize_country_code(str(scene.get("countryCode", ""))),
                "countryLabel": str(scene.get("countryLabel", "")),
                "metricLabel": str(scene.get("metricLabel", "")),
                "metricValue": str(scene.get("metricValue", scene["statusText"])),
                "statusText": str(scene["statusText"]),
            }
        )

    transition_duration_frames = DEFAULT_TRANSITION_DURATION_FRAMES
    hold_duration_frames = calculate_hold_duration_frames(
        duration_target=int(payload["duration_target"]),
        card_count=len(cards),
        transition_duration_frames=transition_duration_frames,
    )

    return {
        "template": "timeline",
        "cardLayout": str(payload.get("cardLayout", "classic") or "classic"),
        "contentFormat": content_format,
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
        "holdDurationFrames": hold_duration_frames,
        "transitionDurationFrames": transition_duration_frames,
        "content_contract": payload,
    }


def build_ranking_header(*, scene: dict[str, Any], fallback_rank: int) -> str:
    """Return a public-facing ranking label for a rendered card."""
    combined_text = f"{scene.get('title', '')} {scene.get('statusText', '')}"
    rank_match = re.search(r"#\s*(\d+)", combined_text)
    rank = rank_match.group(1) if rank_match else str(fallback_rank)
    return f"TOP {rank}"


def build_card_header(
    *,
    scene: dict[str, Any],
    content_format: str,
    index: int,
) -> str:
    """Return the concise card header for a factual content format."""
    if content_format == "ranking":
        return build_ranking_header(scene=scene, fallback_rank=index + 1)
    if content_format == "fact_collection":
        return f"FACT {index + 1}"
    if content_format == "timeline":
        return "MILESTONE"
    if content_format == "record_comparison":
        return "RECORD"
    if content_format == "before_after":
        return "THEN / NOW"
    if content_format == "count_comparison":
        return "COUNT"
    value = str(scene.get("factValue", scene.get("metricValue", ""))).strip().upper()
    return "YES" if value in {"YES", "TRUE", "1"} else "NO"


def normalize_country_code(value: str) -> str:
    return value.strip().upper()


def canonical_country_label(country_code: str) -> str:
    """Return the renderer-approved uppercase country label for an ISO alpha-2 code."""
    normalized_code = normalize_country_code(country_code)
    country = pycountry.countries.get(alpha_2=normalized_code)
    if country is None:
        return ""
    return COUNTRY_LABEL_ALIASES.get(normalized_code, country.name).upper()


def validate_country_metadata(scene: dict[str, Any], *, index: int) -> None:
    country_code = normalize_country_code(str(scene.get("countryCode", "")))
    if not country_code:
        raise VideoContractError(f"scenes[{index}].countryCode is required")
    country = pycountry.countries.get(alpha_2=country_code)
    if country is None:
        raise VideoContractError(f"scenes[{index}].countryCode is not supported")
    valid_labels = {
        normalize_country_label(country.name),
        normalize_country_label(getattr(country, "official_name", "")),
        normalize_country_label(getattr(country, "common_name", "")),
        normalize_country_label(COUNTRY_LABEL_ALIASES.get(country_code, "")),
    }
    valid_labels.discard("")
    country_label = str(scene.get("countryLabel", "")).strip().upper()
    if normalize_country_label(country_label) not in valid_labels:
        expected_label = canonical_country_label(country_code)
        raise VideoContractError(
            f"scenes[{index}].countryLabel must be {expected_label} for {country_code}"
        )


def normalize_country_label(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def apply_verified_images_to_video_data(
    video_data: dict[str, Any],
    image_contract: dict[str, Any],
) -> dict[str, Any]:
    validate_image_verification_contract_v1(image_contract)
    if image_contract["status"] != "verified":
        raise VideoContractError("image verification contract must be verified")

    cards = video_data.get("cards")
    if not isinstance(cards, list):
        raise VideoContractError("cards must contain at least one card")

    for item in image_contract["items"]:
        scene_index = item["scene_index"]
        if scene_index >= len(cards):
            raise VideoContractError(f"items[{scene_index}].scene_index is outside card range")
        cards[scene_index]["imagePath"] = item["render_image_path"]

    video_data["image_verification_contract"] = image_contract
    return video_data


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
