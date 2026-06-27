"""Autonomous topic selection for Celebrity data-comparison videos."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


REQUIRED_FIELDS = (
    "title",
    "category",
    "angle",
    "metric_label",
    "entity_type",
    "data_availability_reason",
    "image_availability_reason",
    "viral_reason",
)
UNSAFE_TERMS = {
    "addiction",
    "affair",
    "criminal",
    "diagnosis",
    "medical",
    "rumor",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _normalized_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()


def normalize_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    """Return stable fields used by validation, scoring, and deduplication."""
    result = {key: str(raw.get(key, "")).strip() for key in REQUIRED_FIELDS}
    result["normalized_title"] = _normalized_text(result["title"])
    result["category"] = _slug(result["category"])
    result["angle"] = _slug(result["angle"])
    result["metric_label"] = result["metric_label"].upper()
    result["entity_type"] = _slug(result["entity_type"])
    result["time_scope"] = _slug(str(raw.get("time_scope", "current")))
    return result


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    """Return deterministic publication errors for a normalized candidate."""
    errors = [
        f"{field} is required"
        for field in REQUIRED_FIELDS
        if not candidate.get(field)
    ]
    if candidate.get("entity_type") != "individual_people":
        errors.append("entity_type must contain individual people")
    title_tokens = set(str(candidate.get("normalized_title", "")).split())
    if title_tokens & UNSAFE_TERMS:
        errors.append("unsafe or sensitive topic")
    return errors


def topic_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Score editorial equivalence using title, angle, and metric."""
    title_ratio = SequenceMatcher(
        None,
        str(left["normalized_title"]),
        str(right["normalized_title"]),
    ).ratio()
    same_angle = float(left.get("angle") == right.get("angle"))
    same_metric = float(left.get("metric_label") == right.get("metric_label"))
    return 0.65 * title_ratio + 0.25 * same_angle + 0.10 * same_metric
