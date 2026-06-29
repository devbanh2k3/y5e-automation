"""Plan globally unique celebrity subjects before writing card scenes."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Awaitable, Callable

from agents.base_agent import BaseAgent
from core.ai_resilience import safe_generate_json
from core.card_production import (
    Candidate,
    CardState,
    ProductionInventory,
    normalize_person_key,
)
from core.config import get_settings
from core.fact_verification import MIN_FACT_CONFIDENCE
from core.production_checkpoints import CheckpointStore
from core.video_contract import (
    build_image_verification_contract_v1,
    canonical_country_label,
    normalize_country_code,
)

_GROUP_WORDS = {
    "band",
    "brothers",
    "couple",
    "family",
    "group",
    "sisters",
    "team",
}

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


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
        fact_attempts: int = 2,
        replacement_attempts: int = 3,
        chunk_size: int = 12,
        minimum_ratio: float = 0.90,
        storage_dir: Path | None = None,
    ) -> None:
        super().__init__(name="celebrity_content_orchestrator")
        self.reserve_ratio = max(0.0, reserve_ratio)
        self.minimum_reserve = max(0, minimum_reserve)
        self.planner_attempts = max(1, planner_attempts)
        self.content_attempts = max(1, content_attempts)
        self.fact_attempts = max(1, fact_attempts)
        self.replacement_attempts = max(0, replacement_attempts)
        self.chunk_size = max(1, chunk_size)
        self.minimum_ratio = min(1.0, max(0.0, minimum_ratio))
        self.storage_dir = storage_dir or get_settings().storage_dir

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
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        checkpoint = (
            CheckpointStore(self.storage_dir, run_id=run_id) if run_id else None
        )
        saved_inventory = checkpoint.load("card-states") if checkpoint else None
        if isinstance(saved_inventory, dict):
            inventory = ProductionInventory.from_dict(saved_inventory)
            if inventory.target_cards != target_cards:
                inventory = None
        else:
            inventory = None

        if inventory is not None and all(
            card.scene is not None for card in inventory.cards.values()
        ):
            result = dict(metadata_contract)
            result["scenes"] = [
                card.scene for card in inventory.cards.values() if card.scene is not None
            ]
            result["inventory"] = inventory
            result["run_id"] = run_id
            return result

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
        await self._emit_progress(
            progress_callback,
            stage="entity_planning",
            ready=min(len(candidates), target_cards),
            target=target_cards,
        )

        inventory = ProductionInventory(
            target_cards=target_cards,
            format_minimum_cards=min(6, target_cards),
            minimum_ratio=self.minimum_ratio,
        )
        inventory.add_candidates(candidates)
        inventory.lock_candidates(inventory.candidates)
        if checkpoint:
            checkpoint.save(
                "candidate-pool",
                [candidate.to_dict() for candidate in inventory.candidates],
            )
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
        await self._emit_progress(
            progress_callback,
            stage="content_writing",
            ready=sum(card.scene is not None for card in inventory.cards.values()),
            target=target_cards,
        )
        if checkpoint:
            checkpoint.save("card-states", inventory.to_dict())

        result = dict(metadata_contract)
        result["scenes"] = [
            card.scene for card in inventory.cards.values() if card.scene is not None
        ]
        result["inventory"] = inventory
        result["run_id"] = run_id
        return result

    async def verify_and_recover(
        self,
        planned: dict[str, Any],
        *,
        topic_id: int,
        topic: dict[str, Any],
        language: str,
        fact_agent: Any,
        image_agent: Any,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Verify cards independently and replace or skip exhausted slots."""

        inventory = planned.get("inventory")
        if not isinstance(inventory, ProductionInventory):
            raise TypeError("planned content requires a ProductionInventory")
        metadata_contract = {
            key: value
            for key, value in planned.items()
            if key not in {"inventory", "scenes", "run_id"}
        }
        run_id = str(planned.get("run_id") or "").strip()
        checkpoint = (
            CheckpointStore(self.storage_dir, run_id=run_id) if run_id else None
        )

        repaired_count = 0
        for card in inventory.cards.values():
            if (
                card.state is CardState.READY
                and card.scene is not None
                and card.fact_item is not None
                and card.image_item is not None
            ):
                await self._emit_progress(
                    progress_callback,
                    stage="image_verification",
                    ready=len(inventory.ready_cards),
                    target=inventory.target_cards,
                    repairing=inventory.replaced_count,
                )
                continue
            replacements_for_slot = 0
            while True:
                if card.scene is None:
                    scene_map = await self._write_locked_scenes(
                        candidates=[card.candidate],
                        topic=topic,
                        metadata_contract=metadata_contract,
                        language=language,
                    )
                    card.scene = scene_map.get(normalize_person_key(card.candidate.name))
                if card.scene is None:
                    failure = "content_missing"
                else:
                    failure = await self._verify_card_fact(
                        card=card,
                        metadata_contract=metadata_contract,
                        fact_agent=fact_agent,
                    )
                    if failure is None:
                        failure = await self._verify_card_image(
                            card=card,
                            topic_id=topic_id,
                            image_agent=image_agent,
                        )
                if failure is None:
                    card.state = CardState.READY
                    break

                if replacements_for_slot < self.replacement_attempts and inventory.reserve:
                    inventory.replace(card.card_id, reason=failure)
                    replacements_for_slot += 1
                    repaired_count += 1
                    continue
                inventory.skip(card.card_id, reason=failure)
                break
            if checkpoint:
                checkpoint.save("card-states", inventory.to_dict())
                if card.last_error:
                    checkpoint.append_error(
                        {
                            "card": card.card_id,
                            "category": card.last_error,
                            "state": card.state.value,
                        }
                    )
            await self._emit_progress(
                progress_callback,
                stage="image_verification",
                ready=len(inventory.ready_cards),
                target=inventory.target_cards,
                repairing=inventory.replaced_count,
            )

        content_format = str(planned.get("contentFormat") or "ranking")
        final_scenes = inventory.finalize_scenes(content_format=content_format)
        ready_cards = inventory.ready_cards
        fact_items: list[dict[str, Any]] = []
        image_items: list[dict[str, Any]] = []
        for scene_index, (card, final_scene) in enumerate(zip(ready_cards, final_scenes)):
            card.scene = final_scene
            fact_item = dict(card.fact_item or {})
            fact_item["scene_index"] = scene_index
            fact_item["person_name"] = extract_scene_person_name(final_scene)
            fact_items.append(fact_item)
            image_item = dict(card.image_item or {})
            image_item["scene_index"] = scene_index
            image_item["person_name"] = extract_scene_person_name(final_scene)
            image_item["expected_title"] = str(final_scene.get("title", ""))
            image_items.append(image_item)

        content_contract = dict(metadata_contract)
        content_contract["scenes"] = final_scenes
        fact_contract = fact_agent.build_verified_contract(fact_items)
        image_contract = build_image_verification_contract_v1(
            topic_id=topic_id,
            items=image_items,
        )
        await self._emit_progress(
            progress_callback,
            stage="finalizing",
            ready=len(final_scenes),
            target=inventory.target_cards,
        )
        if checkpoint:
            checkpoint.save("scenes", final_scenes)
            checkpoint.save("verification", {"facts": fact_items, "images": image_items})
            checkpoint.save(
                "render-manifest",
                {
                    "target_cards": inventory.target_cards,
                    "minimum_cards": inventory.minimum_cards,
                    "final_cards": len(final_scenes),
                    "ready": True,
                },
            )
        return {
            "content_contract": content_contract,
            "fact_verification_contract": fact_contract,
            "image_verification_contract": image_contract,
            "inventory": inventory,
            "production_summary": {
                "target_cards": inventory.target_cards,
                "minimum_cards": inventory.minimum_cards,
                "final_cards": len(final_scenes),
                "repaired_cards": repaired_count,
                "replaced_cards": inventory.replaced_count,
                "skipped_cards": inventory.skipped_count,
                "degraded": len(final_scenes) < inventory.target_cards,
            },
        }

    async def _emit_progress(
        self,
        callback: ProgressCallback | None,
        *,
        stage: str,
        ready: int,
        target: int,
        repairing: int = 0,
    ) -> None:
        if callback is None:
            return
        try:
            await callback(
                {
                    "stage": stage,
                    "ready": ready,
                    "target": target,
                    "repairing": repairing,
                }
            )
        except Exception as exc:
            self.logger.warning("Production progress callback failed: %s", exc)

    async def _verify_card_fact(
        self,
        *,
        card: Any,
        metadata_contract: dict[str, Any],
        fact_agent: Any,
    ) -> str | None:
        for attempt in range(1, self.fact_attempts + 1):
            card.state = CardState.FACT_CHECKING
            card.attempts["fact"] = attempt
            try:
                items = await fact_agent.verify_scenes(
                    content_contract={**metadata_contract, "scenes": [card.scene]}
                )
            except Exception as exc:
                card.last_error = type(exc).__name__
                continue
            if not items:
                card.last_error = "fact_missing"
                continue
            item = dict(items[0])
            confidence = item.get("confidence")
            if (
                item.get("status") in {"verified", "corrected"}
                and isinstance(confidence, int | float)
                and confidence >= MIN_FACT_CONFIDENCE
            ):
                card.fact_item = item
                if item.get("status") == "corrected":
                    value = str(item.get("verified_value", "")).strip()
                    if value and card.scene is not None:
                        card.scene["factValue"] = value
                        card.scene["metricValue"] = value
                        card.scene["caption"] = value
                card.state = CardState.FACT_READY
                return None
            card.last_error = "fact_rejected"
        return card.last_error or "fact_rejected"

    @staticmethod
    async def _verify_card_image(
        *,
        card: Any,
        topic_id: int,
        image_agent: Any,
    ) -> str | None:
        card.state = CardState.IMAGE_SEARCHING
        try:
            item = await image_agent.verify_scene(
                topic_id=topic_id,
                scene_index=0,
                scene=card.scene,
            )
        except Exception as exc:
            card.last_error = type(exc).__name__
            return "image_error"
        if item.get("status") != "verified":
            card.last_error = str(item.get("reject_reason") or "image_missing")
            return "image_missing"
        card.image_item = dict(item)
        return None

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
