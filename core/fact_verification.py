"""Contracts and deterministic correction rules for AI-verified facts."""

from __future__ import annotations

import copy
import re
from typing import Any


MIN_FACT_CONFIDENCE = 0.80
FACT_STATUSES = {"verified", "corrected", "rejected"}


class FactVerificationError(ValueError):
    """Raised when factual evidence is not safe to render."""


def build_fact_verification_contract_v1(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    verified_count = sum(item.get("status") == "verified" for item in items)
    corrected_count = sum(item.get("status") == "corrected" for item in items)
    rejected_count = sum(item.get("status") == "rejected" for item in items)
    all_confident = all(
        isinstance(item.get("confidence"), int | float)
        and item["confidence"] >= MIN_FACT_CONFIDENCE
        for item in items
    )
    status = (
        "ai_verified"
        if items and rejected_count == 0 and all_confident
        else "rejected"
    )
    return {
        "schema_version": "fact_verification_contract_v1",
        "verification_policy": "ai_only_independent_pass",
        "status": status,
        "required_count": len(items),
        "verified_count": verified_count,
        "corrected_count": corrected_count,
        "rejected_count": rejected_count,
        "items": items,
    }


def validate_fact_verification_contract_v1(
    payload: dict[str, Any],
    *,
    require_ai_verified: bool = False,
) -> None:
    if payload.get("schema_version") != "fact_verification_contract_v1":
        raise FactVerificationError("schema_version must be fact_verification_contract_v1")
    if payload.get("verification_policy") != "ai_only_independent_pass":
        raise FactVerificationError("verification_policy must be ai_only_independent_pass")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise FactVerificationError("items must contain factual verification evidence")
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("scene_index") != index:
            raise FactVerificationError(f"items[{index}].scene_index must be {index}")
        if item.get("status") not in FACT_STATUSES:
            raise FactVerificationError(f"items[{index}].status is invalid")
        confidence = item.get("confidence")
        if not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
            raise FactVerificationError(f"items[{index}].confidence must be between 0 and 1")
        for field in (
            "person_name",
            "metric_label",
            "original_value",
            "verified_value",
            "unit",
            "as_of",
            "reason",
            "knowledge_cutoff_risk",
        ):
            if not str(item.get(field, "")).strip():
                raise FactVerificationError(f"items[{index}].{field} is required")
    if payload.get("required_count") != len(items):
        raise FactVerificationError("required_count must equal item count")
    expected = build_fact_verification_contract_v1(items)
    for field in ("verified_count", "corrected_count", "rejected_count", "status"):
        if payload.get(field) != expected[field]:
            raise FactVerificationError(f"{field} does not match items")
    if require_ai_verified and payload.get("status") != "ai_verified":
        raise FactVerificationError("all facts must be AI verified with confidence >= 0.80")


def apply_fact_corrections(
    content_contract: dict[str, Any],
    verification_contract: dict[str, Any],
) -> dict[str, Any]:
    """Apply confident corrections to a copy and preserve ranking order."""
    validate_fact_verification_contract_v1(
        verification_contract,
        require_ai_verified=True,
    )
    corrected = copy.deepcopy(content_contract)
    scenes = corrected.get("scenes", [])
    if len(scenes) != verification_contract["required_count"]:
        raise FactVerificationError("fact item count must match scenes")
    for item in verification_contract["items"]:
        scene = scenes[item["scene_index"]]
        if item["status"] == "corrected":
            value = str(item["verified_value"])
            scene["factValue"] = value
            scene["metricValue"] = value
            scene["caption"] = value
            scene["statusText"] = value
    if corrected.get("contentFormat") == "ranking":
        try:
            scenes.sort(key=lambda scene: _numeric_value(str(scene["factValue"])))
        except (KeyError, ValueError) as exc:
            raise FactVerificationError("corrected ranking values must be numeric") from exc
        total = len(scenes)
        for index, scene in enumerate(scenes):
            rank = total - index
            person = re.sub(r"^#\s*\d+\s*", "", str(scene["title"])).strip()
            scene["title"] = f"#{rank} {person}"
            scene["statusText"] = f"#{rank} | {scene['factValue']}"
    return corrected


def _numeric_value(value: str) -> float:
    match = re.search(r"-?\d+(?:[.,]\d+)?", value.replace(",", ""))
    if match is None:
        raise ValueError(value)
    number = float(match.group())
    upper = value.upper()
    if "B" in upper:
        number *= 1_000_000_000
    elif "M" in upper:
        number *= 1_000_000
    elif "K" in upper:
        number *= 1_000
    return number
