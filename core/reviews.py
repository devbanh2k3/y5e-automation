"""JSON-backed review gate store for rendered videos."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from core.config import get_settings


class ReviewStatus(str, Enum):
    """Review lifecycle states before upload is allowed."""

    PENDING = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


ALLOWED_REJECT_REASONS = {
    "wrong_image",
    "bad_fact",
    "bad_text",
    "bad_video",
    "bad_layout",
    "bad_topic",
    "bad_metric",
    "other",
}


def utc_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def reviews_dir() -> Path:
    """Return the review artifact directory."""
    path = get_settings().storage_dir / "reviews"
    path.mkdir(parents=True, exist_ok=True)
    return path


def review_path(review_id: str) -> Path:
    """Return the JSON path for a review ID."""
    return reviews_dir() / f"{review_id}.json"


async def create_review(
    *,
    job_id: str,
    topic_id: int,
    video_id: int,
    file_path: str,
    content_contract: dict[str, Any] | None,
    fact_verification_contract: dict[str, Any] | None = None,
    image_verification_contract: dict[str, Any] | None = None,
    quality_gate: dict[str, Any] | None = None,
    metadata_variants: dict[str, Any] | None = None,
    selected_metadata: dict[str, Any] | None = None,
    youtube_title: str,
    youtube_description: str,
    youtube_tags: list[str],
    thumbnail_prompt: str,
) -> dict[str, Any]:
    """Create a pending review artifact for a rendered video."""
    timestamp = utc_now()
    review_id = str(uuid.uuid4())
    review = {
        "review_id": review_id,
        "status": ReviewStatus.PENDING.value,
        "job_id": job_id,
        "video": {
            "topic_id": topic_id,
            "video_id": video_id,
            "file_path": file_path,
        },
        "content_contract": content_contract or {},
        "fact_verification_contract": fact_verification_contract or {},
        "image_verification_contract": image_verification_contract or {},
        "quality_gate": quality_gate or {},
        "metadata_variants": metadata_variants or {},
        "selected_metadata": selected_metadata
        or {
            "title": youtube_title,
            "description": youtube_description,
            "tags": youtube_tags,
            "thumbnail_text": "",
        },
        "youtube": {
            "title": youtube_title,
            "description": youtube_description,
            "tags": youtube_tags,
        },
        "thumbnail_prompt": thumbnail_prompt,
        "review_notes": "",
        "reject_reason": "",
        "rejected_scenes": [],
        "review_events": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    await _write_review(review)
    return review


async def get_review(review_id: str) -> dict[str, Any]:
    """Load a review artifact by ID."""
    path = review_path(review_id)
    if not path.is_file():
        raise KeyError(review_id)
    return json.loads(path.read_text())


async def list_reviews(
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List review artifacts newest first with optional status filtering."""
    reviews: list[dict[str, Any]] = []
    for path in sorted(reviews_dir().glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        review = json.loads(path.read_text())
        if status and review.get("status") != status:
            continue
        reviews.append(review)
        if len(reviews) >= max(1, limit):
            break
    return reviews


async def approve_review(review_id: str, notes: str = "") -> dict[str, Any]:
    """Mark a pending review as approved."""
    return await _transition_review(
        review_id,
        status=ReviewStatus.APPROVED,
        notes=notes,
        event="approved",
    )


async def reject_review(
    review_id: str,
    reason: str = "",
    *,
    scenes: list[int] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Mark a pending review as rejected."""
    if reason not in ALLOWED_REJECT_REASONS:
        allowed = ", ".join(sorted(ALLOWED_REJECT_REASONS))
        raise ValueError(f"reject reason must be one of: {allowed}")
    return await _transition_review(
        review_id,
        status=ReviewStatus.REJECTED,
        notes=notes or reason,
        event="rejected",
        reason=reason,
        scenes=scenes or [],
    )


async def select_review_metadata(
    review_id: str,
    *,
    title_index: int | None = None,
    description_index: int | None = None,
    thumbnail_text_index: int | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Select metadata variants and keep the review youtube fields in sync."""
    review = await get_review(review_id)
    variants = review.get("metadata_variants") or {}
    selected = dict(review.get("selected_metadata") or {})

    if title_index is not None:
        selected["title"] = _variant_title_at(variants, title_index)
    if description_index is not None:
        selected["description"] = _variant_text_at(
            variants,
            "description_variants",
            description_index,
        )
    if thumbnail_text_index is not None:
        selected["thumbnail_text"] = _variant_text_at(
            variants,
            "thumbnail_text_suggestions",
            thumbnail_text_index,
        )

    if tags is not None:
        selected["tags"] = _clean_tags(tags)
    else:
        selected["tags"] = _clean_tags(
            variants.get("tags") or selected.get("tags") or review.get("youtube", {}).get("tags") or []
        )

    youtube = dict(review.get("youtube") or {})
    youtube["title"] = str(selected.get("title") or youtube.get("title") or "")
    youtube["description"] = str(selected.get("description") or youtube.get("description") or "")
    youtube["tags"] = _clean_tags(selected.get("tags") or youtube.get("tags") or [])

    review["selected_metadata"] = selected
    review["youtube"] = youtube
    review["updated_at"] = utc_now()
    append_review_event(
        review,
        event="metadata_selected",
        notes=f"title={title_index}, description={description_index}, thumbnail={thumbnail_text_index}",
    )
    await _write_review(review)
    return review


async def _transition_review(
    review_id: str,
    *,
    status: ReviewStatus,
    notes: str,
    event: str,
    reason: str = "",
    scenes: list[int] | None = None,
) -> dict[str, Any]:
    review = await get_review(review_id)
    if review.get("status") != ReviewStatus.PENDING.value:
        raise ValueError("review is not pending")
    review["status"] = status.value
    review["review_notes"] = notes
    if status == ReviewStatus.REJECTED:
        review["reject_reason"] = reason
        review["rejected_scenes"] = scenes or []
    append_review_event(review, event=event, reason=reason, scenes=scenes, notes=notes)
    review["updated_at"] = utc_now()
    await _write_review(review)
    return review


def append_review_event(
    review: dict[str, Any],
    *,
    event: str,
    reason: str = "",
    scenes: list[int] | None = None,
    notes: str = "",
) -> None:
    """Append a timestamped review event in-place."""
    review.setdefault("review_events", []).append(
        {
            "event": event,
            "reason": reason,
            "scenes": scenes or [],
            "notes": notes,
            "created_at": utc_now(),
        }
    )


def _variant_title_at(variants: dict[str, Any], index: int) -> str:
    items = variants.get("title_variants")
    if not isinstance(items, list) or index >= len(items):
        raise ValueError("title variant index is invalid")
    item = items[index]
    title = str(item.get("title", "") if isinstance(item, dict) else item).strip()
    if not title:
        raise ValueError("title variant is empty")
    return title


def _variant_text_at(variants: dict[str, Any], key: str, index: int) -> str:
    items = variants.get(key)
    if not isinstance(items, list) or index >= len(items):
        raise ValueError(f"{key} index is invalid")
    text = str(items[index]).strip()
    if not text:
        raise ValueError(f"{key} value is empty")
    return text


def _clean_tags(tags: list[Any]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        text = str(tag).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:20]


async def save_review(review: dict[str, Any]) -> None:
    """Persist an updated review artifact."""
    await _write_review(review)


async def _write_review(review: dict[str, Any]) -> None:
    path = review_path(str(review["review_id"]))
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(review, ensure_ascii=False, indent=2))
    tmp_path.replace(path)
