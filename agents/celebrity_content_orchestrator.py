"""Plan globally unique celebrity subjects before writing card scenes."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from typing import Any

from agents.base_agent import BaseAgent
from core.ai_resilience import safe_generate_json
from core.card_production import (
    Candidate,
    CardState,
    ProductionInventory,
    normalize_person_key,
)
from core.video_contract import canonical_country_label, normalize_country_code

_GROUP_WORDS = {
    "band",
    "brothers",
    "couple",
    "family",
    "group",
    "sisters",
    "team",
}


def extract_scene_person_name(scene: dict[str, Any]) -> str:
    """Extract the person identity from a ranking or non-ranking title."""

    return re.sub(r"^#\s*\d+\s*", "", str(scene.get("title", ""))).strip()


def validate_scene_shape(scene: dict[str, Any]) -> bool:
    """Return whether the writer supplied the fields needed by later gates."""

    required = (
        "title",
        "voiceover",
        "caption",
        "image_prompt",
        "statusText",
        "countryCode",
        "metricLabel",
        "metricValue",
        "factClaim",
    )
    return all(str(scene.get(field, "")).strip() for field in required)


def batched(values: list[Candidate], size: int) -> Iterable[list[Candidate]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


class CelebrityContentOrchestrator(BaseAgent):
    """Create one locked candidate inventory and write only those subjects."""

    def __init__(
        self,
        *,
        reserve_ratio: float = 0.25,
        minimum_reserve: int = 10,
        planner_attempts: int = 4,
        content_attempts: int = 3,
        chunk_size: int = 12,
        minimum_ratio: float = 0.90,
    ) -> None:
        super().__init__(name="celebrity_content_orchestrator")
        self.reserve_ratio = max(0.0, reserve_ratio)
        self.minimum_reserve = max(0, minimum_reserve)
        self.planner_attempts = max(1, planner_attempts)
        self.content_attempts = max(1, content_attempts)
        self.chunk_size = max(1, chunk_size)
        self.minimum_ratio = min(1.0, max(0.0, minimum_ratio))

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        return await self.build(**kwargs)

    async def build(
        self,
        *,
        topic: dict[str, Any],
        target_cards: int,
        metadata_contract: dict[str, Any],
        language: str,
        subject: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        del run_id
        requested = target_cards + max(
            self.minimum_reserve,
            math.ceil(target_cards * self.reserve_ratio),
        )
        candidates = await self._plan_candidates(
            requested_count=requested,
            topic=topic,
            language=language,
            subject=subject,
        )
        if len(candidates) < target_cards:
            raise ValueError(
                f"entity planner requires {target_cards} unique people, got {len(candidates)}"
            )

        inventory = ProductionInventory(
            target_cards=target_cards,
            format_minimum_cards=min(6, target_cards),
            minimum_ratio=self.minimum_ratio,
        )
        inventory.add_candidates(candidates)
        inventory.lock_candidates(inventory.candidates)
        scene_map = await self._write_locked_scenes(
            candidates=[card.candidate for card in inventory.cards.values()],
            topic=topic,
            metadata_contract=metadata_contract,
            language=language,
        )
        for card in inventory.cards.values():
            key = normalize_person_key(card.candidate.name)
            card.scene = scene_map.get(key)
            if card.scene:
                card.state = CardState.CONTENT_READY

        result = dict(metadata_contract)
        result["scenes"] = [
            card.scene for card in inventory.cards.values() if card.scene is not None
        ]
        result["inventory"] = inventory
        return result

    async def _plan_candidates(
        self,
        *,
        requested_count: int,
        topic: dict[str, Any],
        language: str,
        subject: str,
    ) -> list[Candidate]:
        inventory = ProductionInventory(
            target_cards=requested_count,
            format_minimum_cards=1,
        )
        rejected: set[str] = set()
        for _attempt in range(self.planner_attempts):
            missing = requested_count - len(inventory.candidates)
            if missing <= 0:
                break
            payload = await self._call_json(
                operation="entity_plan",
                topic=topic,
                language=language,
                subject=subject,
                requested_count=missing,
                blacklist=sorted(
                    rejected
                    | {
                        normalize_person_key(candidate.name)
                        for candidate in inventory.candidates
                    }
                ),
            )
            raw_candidates = payload.get("candidates")
            if not isinstance(raw_candidates, list):
                continue
            accepted: list[Candidate] = []
            for raw in raw_candidates:
                if not isinstance(raw, dict):
                    continue
                candidate = Candidate.from_dict(raw)
                key = normalize_person_key(candidate.name)
                if not self._candidate_is_valid(candidate):
                    if key:
                        rejected.add(key)
                    continue
                accepted.append(candidate)
            inventory.add_candidates(accepted)
        return inventory.candidates[:requested_count]

    async def _write_locked_scenes(
        self,
        *,
        candidates: list[Candidate],
        topic: dict[str, Any],
        metadata_contract: dict[str, Any],
        language: str,
    ) -> dict[str, dict[str, Any]]:
        pending = {normalize_person_key(item.name): item for item in candidates}
        scenes: dict[str, dict[str, Any]] = {}
        for _attempt in range(self.content_attempts):
            if not pending:
                break
            current_pending = list(pending.values())
            for candidate_chunk in batched(current_pending, self.chunk_size):
                locked_names = [candidate.name for candidate in candidate_chunk]
                payload = await self._call_json(
                    operation="scene_write",
                    topic=topic,
                    language=language,
                    metadata_contract=metadata_contract,
                    locked_names=locked_names,
                )
                raw_scenes = payload.get("scenes")
                if not isinstance(raw_scenes, list):
                    continue
                for scene in raw_scenes:
                    if not isinstance(scene, dict) or not validate_scene_shape(scene):
                        continue
                    key = normalize_person_key(extract_scene_person_name(scene))
                    if key not in pending:
                        continue
                    scenes[key] = dict(scene)
                    pending.pop(key)
        return scenes

    async def _call_json(self, *, operation: str, **kwargs: Any) -> dict[str, Any]:
        if operation == "entity_plan":
            prompt = self._entity_prompt(**kwargs)
        elif operation == "scene_write":
            prompt = self._scene_prompt(**kwargs)
        else:
            raise ValueError(f"unsupported celebrity content operation: {operation}")
        result = await safe_generate_json(
            self.ai,
            prompt=prompt,
            system=(
                "You create factual celebrity comparison data. Return one valid JSON "
                "object only. Never add people outside an explicitly locked list."
            ),
        )
        return result.value

    @staticmethod
    def _candidate_is_valid(candidate: Candidate) -> bool:
        key = normalize_person_key(candidate.name)
        if not key or len(key.split()) > 6:
            return False
        if any(word in key.split() for word in _GROUP_WORDS):
            return False
        country_code = normalize_country_code(candidate.country_code)
        if not country_code or not canonical_country_label(country_code):
            return False
        return True

    @staticmethod
    def _entity_prompt(
        *,
        topic: dict[str, Any],
        language: str,
        subject: str,
        requested_count: int,
        blacklist: list[str],
    ) -> str:
        return f"""Plan {requested_count} individual public celebrity candidates.

Topic: {json.dumps(topic, ensure_ascii=False)}
Language: {language}
Subject: {subject}
Do not return these normalized identities: {json.dumps(blacklist)}

Return JSON: {{"candidates":[{{"name":"Person", "countryCode":"US", "selectionReason":"why", "aliases":[]}}]}}
Use real individual people only. Do not use groups, couples, families, brands, or teams.
"""

    @staticmethod
    def _scene_prompt(
        *,
        topic: dict[str, Any],
        language: str,
        metadata_contract: dict[str, Any],
        locked_names: list[str],
    ) -> str:
        return f"""Write exactly one factual card scene for each locked person.

Topic: {json.dumps(topic, ensure_ascii=False)}
Language: {language}
Locked people: {json.dumps(locked_names, ensure_ascii=False)}
Video metadata context: {json.dumps({key: value for key, value in metadata_contract.items() if key != 'scenes'}, ensure_ascii=False)}

Return JSON with a scenes array. Every scene requires title, voiceover, caption,
image_prompt, statusText, countryCode, countryLabel, metricLabel, metricValue,
factClaim, factValue, factUnit, factAsOf, factContext, and sourceRequirement.
Do not add, remove, substitute, combine, or rename locked people.
"""
