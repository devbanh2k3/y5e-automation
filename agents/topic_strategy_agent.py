"""Autonomous topic selection for Celebrity data-comparison videos."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from uuid import uuid4

from agents.base_agent import BaseAgent
from core.config import get_settings
from core.topic_history import TopicHistoryRepository


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
    for score_name in ("viral_score", "data_score", "image_score", "safety_score"):
        try:
            score = max(0.0, min(100.0, float(raw.get(score_name, 0))))
            result[score_name] = score * 10 if score <= 10 else score
        except (TypeError, ValueError):
            result[score_name] = 0.0
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
    left_angle = str(left.get("angle", ""))
    right_angle = str(right.get("angle", ""))
    same_metric = float(left.get("metric_label") == right.get("metric_label"))
    if not left_angle or not right_angle:
        return 0.90 * title_ratio + 0.10 * same_metric
    same_angle = float(left_angle == right_angle)
    return 0.65 * title_ratio + 0.25 * same_angle + 0.10 * same_metric


class TopicSelectionError(RuntimeError):
    """Raised when a diverse topic slate cannot be selected durably."""


class TopicStrategyAgent(BaseAgent):
    """Generate, score, and reserve diverse Celebrity topics."""

    def __init__(self, repository: TopicHistoryRepository | None = None) -> None:
        super().__init__(name="topic_strategy_agent")
        history_path = get_settings().storage_dir / "celebrity_topic_history.json"
        self.repository = repository or TopicHistoryRepository(history_path)

    async def run(
        self,
        *,
        count: int,
        language: str,
        batch_id: str,
    ) -> list[dict[str, Any]]:
        if count < 1:
            raise ValueError("topic count must be at least 1")

        durable_history = self.repository.load()
        durable_titles = {
            str(item.get("normalized_title", "")) for item in durable_history
        }
        legacy_history = [
            item
            for item in self._load_legacy_history(self.repository.path.parent)
            if item["normalized_title"] not in durable_titles
        ]
        history = legacy_history + durable_history
        pool_size = max(count * 5, 10)
        candidates = await self._generate_candidates(
            count=pool_size,
            language=language,
            history=history,
            expanded=False,
        )
        selected = self._select_diverse(candidates, history=history, count=count)
        if len(selected) < count:
            candidates.extend(
                await self._generate_candidates(
                    count=pool_size,
                    language=language,
                    history=history + candidates,
                    expanded=True,
                )
            )
            selected = self._select_diverse(
                candidates,
                history=history,
                count=count,
            )
        if len(selected) != count:
            raise TopicSelectionError(
                f"could not select {count} diverse Celebrity topics"
            )

        reservations = self._prepare_reservations(selected, batch_id=batch_id)
        reserved = self.repository.reserve_many(reservations)
        if len(reserved) != count:
            raise TopicSelectionError("topic reservations changed concurrently")
        return reserved

    async def _generate_candidates(
        self,
        *,
        count: int,
        language: str,
        history: list[dict[str, Any]],
        expanded: bool,
    ) -> list[dict[str, Any]]:
        history_lines = [
            f"- {item.get('title', '')} | {item.get('angle', '')} | "
            f"{item.get('metric_label', '')}"
            for item in history[-30:]
        ]
        expansion_instruction = (
            "The first pool lacked diversity. Explore entirely new categories and metrics."
            if expanded
            else "Build a broad initial candidate pool."
        )
        prompt = f"""Generate {count} diverse topic candidates for autonomous Celebrity
data-comparison videos in language {language}.

Seed dimensions are examples, not an allowlist: wealth, earnings, social reach,
awards, film, music, age, height, career duration, country, generation, profession,
touring revenue, streaming records, and box-office salary.

{expansion_instruction}

Previously considered or produced topics:
{chr(10).join(history_lines) or "- none"}

Every candidate must compare individual public people, have measurable public data,
support real editorial photos, avoid gossip/private or medical claims, and differ in
both angle and metric from other candidates. Every score must be an integer on a
0-100 scale. Return JSON only:
{{
  "candidates": [
    {{
      "title": "Top 10 ...",
      "category": "open taxonomy category",
      "angle": "specific_snake_case_angle",
      "metric_label": "SHORT METRIC",
      "entity_type": "individual_people",
      "data_availability_reason": "public sources likely available",
      "image_availability_reason": "real editorial photos likely available",
      "viral_reason": "specific audience appeal",
      "time_scope": "2026 or all_time",
      "viral_score": 85,
      "data_score": 90,
      "image_score": 90,
      "safety_score": 95
    }}
  ]
}}"""
        payload = await self.ai_json(
            prompt,
            system=(
                "You are a rigorous YouTube portfolio strategist. Return valid JSON only. "
                "Favor editorial diversity, verifiable public data, and real-image availability."
            ),
        )
        raw_candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
        if not isinstance(raw_candidates, list):
            raise TopicSelectionError("AI topic candidates must be a list")
        return [
            normalize_candidate(item)
            for item in raw_candidates
            if isinstance(item, dict)
        ]

    def _select_diverse(
        self,
        candidates: list[dict[str, Any]],
        *,
        history: list[dict[str, Any]],
        count: int,
    ) -> list[dict[str, Any]]:
        normalized_history = [
            self._history_candidate(item)
            for item in history
            if item.get("normalized_title") or item.get("title")
        ]
        cooldown_angles = {
            str(item.get("angle", "")) for item in normalized_history[-10:]
        }
        eligible: list[dict[str, Any]] = []

        for raw_candidate in candidates:
            item = normalize_candidate(raw_candidate)
            if validate_candidate(item) or item["angle"] in cooldown_angles:
                continue
            max_similarity = max(
                (topic_similarity(item, old) for old in normalized_history),
                default=0.0,
            )
            if max_similarity >= 0.72:
                continue
            novelty_score = max(0.0, 100.0 * (1.0 - max_similarity))
            score_breakdown = {
                "viral": item["viral_score"],
                "data": item["data_score"],
                "novelty": round(novelty_score, 2),
                "image": item["image_score"],
                "safety": item["safety_score"],
            }
            item["score_breakdown"] = score_breakdown
            item["score_total"] = round(
                score_breakdown["viral"] * 0.30
                + score_breakdown["data"] * 0.25
                + score_breakdown["novelty"] * 0.25
                + score_breakdown["image"] * 0.15
                + score_breakdown["safety"] * 0.05,
                2,
            )
            eligible.append(item)

        selected: list[dict[str, Any]] = []
        used_angles: set[str] = set()
        used_metrics: set[str] = set()
        for item in sorted(eligible, key=lambda value: value["score_total"], reverse=True):
            if item["angle"] in used_angles or item["metric_label"] in used_metrics:
                continue
            if any(topic_similarity(item, chosen) >= 0.72 for chosen in selected):
                continue
            selected.append(item)
            used_angles.add(item["angle"])
            used_metrics.add(item["metric_label"])
            if len(selected) == count:
                break
        return selected

    @staticmethod
    def _history_candidate(item: dict[str, Any]) -> dict[str, Any]:
        if item.get("normalized_title"):
            return dict(item)
        return normalize_candidate(item)

    @staticmethod
    def _load_legacy_history(storage_dir: Path) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for contract_path in sorted(
            (storage_dir / "topics").glob("*/content_contract.json")
        ):
            try:
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(contract, dict):
                continue
            title = str(
                contract.get("youtube_title") or contract.get("title") or ""
            ).strip()
            if not title:
                continue
            scenes = contract.get("scenes", [])
            first_scene = scenes[0] if isinstance(scenes, list) and scenes else {}
            metric_label = (
                str(first_scene.get("metricLabel", "")).strip().upper()
                if isinstance(first_scene, dict)
                else ""
            )
            history.append(
                {
                    "title": title,
                    "normalized_title": _normalized_text(title),
                    "category": "legacy_content",
                    "angle": "",
                    "metric_label": metric_label,
                    "time_scope": "legacy",
                    "status": "produced",
                    "source": str(contract_path),
                }
            )
        return history

    @staticmethod
    def _prepare_reservations(
        selected: list[dict[str, Any]],
        *,
        batch_id: str,
    ) -> list[dict[str, Any]]:
        reservations = []
        for item in selected:
            reservation = dict(item)
            reservation.update(
                {
                    "reservation_id": str(uuid4()),
                    "batch_id": batch_id,
                    "status": "reserved",
                    "selection_reason": (
                        "Highest-scoring valid candidate that preserves batch diversity."
                    ),
                }
            )
            reservations.append(reservation)
        return reservations
