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


async def save_review(review: dict[str, Any]) -> None:
    """Persist an updated review artifact."""
    await _write_review(review)


async def _write_review(review: dict[str, Any]) -> None:
    path = review_path(str(review["review_id"]))
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(review, ensure_ascii=False, indent=2))
    tmp_path.replace(path)
