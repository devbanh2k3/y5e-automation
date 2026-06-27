"""Independent AI fact verification for factual Celebrity content."""

from __future__ import annotations

import json
import re
from typing import Any

from agents.base_agent import BaseAgent
from core.fact_verification import (
    FactVerificationError,
    build_fact_verification_contract_v1,
    validate_fact_verification_contract_v1,
)


class AIFactVerificationAgent(BaseAgent):
    """Challenge structured claims in a separate AI pass before rendering."""

    def __init__(self) -> None:
        super().__init__(name="ai_fact_verification_agent")

    async def run(
        self,
        *,
        content_contract: dict[str, Any],
    ) -> dict[str, Any]:
        scenes = content_contract.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise FactVerificationError("content contract requires factual scenes")
        claims = [
            {
                "scene_index": index,
                "person_name": re.sub(
                    r"^#\s*\d+\s*",
                    "",
                    str(scene.get("title", "")),
                ).strip(),
                "metric_label": scene.get("metricLabel", ""),
                "factClaim": scene.get("factClaim", ""),
                "factValue": scene.get("factValue", ""),
                "factUnit": scene.get("factUnit", ""),
                "factAsOf": scene.get("factAsOf", ""),
                "factContext": scene.get("factContext", ""),
            }
            for index, scene in enumerate(scenes)
        ]
        prompt = f"""Independently verify every factual claim below.

Content format: {content_contract.get('contentFormat', 'ranking')}
Metric scope: {content_contract.get('metricScope', '')}
Time scope: {content_contract.get('timeScope', '')}
Claims:
{json.dumps(claims, ensure_ascii=False, indent=2)}

Challenge identity, value, unit, date, scope, ordering, privacy, and plausibility.
Use established public knowledge. Never invent private or uncertain facts. Mark an
uncertain claim rejected. Return one item per input scene as JSON:
{{"items": [{{"scene_index": 0, "person_name": "...", "metric_label": "...",
"original_value": "...", "verified_value": "...", "unit": "...",
"as_of": "...", "status": "verified|corrected|rejected", "confidence": 0.0,
"reason": "...", "knowledge_cutoff_risk": "low|medium|high"}}]}}"""
        response = await self.ai_json(
            prompt,
            system=(
                "You are an adversarial factual verifier. You are independent from the "
                "content writer. Return strict JSON only and reject uncertainty."
            ),
        )
        items = response.get("items") if isinstance(response, dict) else None
        if not isinstance(items, list) or len(items) != len(scenes):
            raise FactVerificationError("AI verifier must return one item per scene")
        normalized: list[dict[str, Any]] = []
        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                raise FactVerificationError(f"items[{index}] must be an object")
            item = dict(raw)
            item["scene_index"] = index
            item["status"] = str(item.get("status", "rejected")).strip().lower()
            normalized.append(item)
        contract = build_fact_verification_contract_v1(normalized)
        validate_fact_verification_contract_v1(contract, require_ai_verified=True)
        return contract
