"""Trend/search metadata optimizer for rendered review candidates."""

from __future__ import annotations

import re
from typing import Any

from agents.base_agent import BaseAgent


class MetadataOptimizerAgent(BaseAgent):
    """Generate review-time YouTube metadata variants."""

    def __init__(self) -> None:
        super().__init__(name="metadata_optimizer_agent")

    async def run(
        self,
        *,
        content_contract: dict[str, Any],
        selected_topic: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            payload = await self.ai_json(
                self._build_prompt(content_contract=content_contract, selected_topic=selected_topic),
                system=(
                    "You are a YouTube metadata strategist for fact-safe celebrity "
                    "data-comparison videos. Return strict JSON only."
                ),
            )
            if not isinstance(payload, dict):
                raise ValueError("metadata optimizer payload must be an object")
            return self._normalize_payload(payload, content_contract=content_contract)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic metadata variants: %s", exc)
            return self._fallback_metadata(content_contract)

    @staticmethod
    def _build_prompt(
        *,
        content_contract: dict[str, Any],
        selected_topic: dict[str, Any] | None,
    ) -> str:
        scenes = content_contract.get("scenes") if isinstance(content_contract.get("scenes"), list) else []
        people = [str(scene.get("title", "")).strip() for scene in scenes[:8] if isinstance(scene, dict)]
        metric = ""
        if scenes and isinstance(scenes[0], dict):
            metric = str(scenes[0].get("metricLabel") or scenes[0].get("factUnit") or "").strip()
        return f"""Generate trend/search optimized YouTube metadata variants.

Content title: {content_contract.get("title", "")}
Current YouTube title: {content_contract.get("youtube_title", "")}
Hook: {content_contract.get("hook", "")}
Metric: {metric}
People/examples: {people}
Selected topic: {selected_topic or {}}

Rules:
1. Generate 5 title variants using mixed formats: curiosity, direct_search, comparison, trend_year, data_shock.
2. Do not use only "Top 10" style titles.
3. Keep titles fact-safe and under 90 characters.
4. Generate 3 descriptions.
5. Generate 12-20 tags, 3 thumbnail text suggestions, 5-10 search keywords.
6. Score each title with search, curiosity, trend, specificity, and safety scores from 0-100.

Return JSON only:
{{
  "trend_angle": "...",
  "title_variants": [
    {{
      "title": "...",
      "format": "curiosity | direct_search | comparison | trend_year | data_shock",
      "score_breakdown": {{
        "search": 90,
        "curiosity": 90,
        "trend": 85,
        "specificity": 90,
        "safety": 95
      }}
    }}
  ],
  "description_variants": ["...", "...", "..."],
  "tags": ["celebrity", "data comparison"],
  "thumbnail_text_suggestions": ["..."],
  "search_keywords": ["..."]
}}"""

    @classmethod
    def _normalize_payload(
        cls,
        payload: dict[str, Any],
        *,
        content_contract: dict[str, Any],
    ) -> dict[str, Any]:
        raw_titles = payload.get("title_variants")
        if not isinstance(raw_titles, list) or not raw_titles:
            raise ValueError("metadata title_variants are required")

        title_variants = []
        for index, item in enumerate(raw_titles[:5]):
            if not isinstance(item, dict):
                continue
            title = cls._clean_title(str(item.get("title", "")).strip())
            if not title:
                continue
            score_breakdown = cls._normalize_score_breakdown(item.get("score_breakdown"))
            title_variants.append(
                {
                    "title": title,
                    "format": str(item.get("format", "variant")).strip() or "variant",
                    "score_breakdown": score_breakdown,
                    "score_total": cls._score_total(score_breakdown),
                }
            )
        if not title_variants:
            raise ValueError("metadata title_variants are empty after normalization")
        title_variants.sort(key=lambda item: item["score_total"], reverse=True)

        descriptions = cls._string_list(payload.get("description_variants"), limit=3)
        if not descriptions:
            descriptions = [str(content_contract.get("youtube_description", "")).strip()]
        tags = cls._string_list(payload.get("tags"), limit=20)
        if not tags:
            tags = cls._string_list(content_contract.get("youtube_tags"), limit=20)
        thumbnail_text = cls._string_list(payload.get("thumbnail_text_suggestions"), limit=3)
        if not thumbnail_text:
            thumbnail_text = [cls._thumbnail_text_from_title(title_variants[0]["title"])]
        keywords = cls._string_list(payload.get("search_keywords"), limit=10)
        if not keywords:
            keywords = cls._keywords_from_contract(content_contract)

        return {
            "schema_version": "metadata_variants_v1",
            "trend_angle": str(payload.get("trend_angle", "")).strip() or "celebrity data curiosity",
            "title_variants": title_variants,
            "description_variants": descriptions[:3],
            "tags": tags[:20],
            "thumbnail_text_suggestions": thumbnail_text[:3],
            "search_keywords": keywords[:10],
            "selected_metadata": {
                "title": title_variants[0]["title"],
                "description": descriptions[0] if descriptions else "",
                "tags": tags[:20],
                "thumbnail_text": thumbnail_text[0] if thumbnail_text else "",
            },
        }

    @classmethod
    def _fallback_metadata(cls, content_contract: dict[str, Any]) -> dict[str, Any]:
        scenes = content_contract.get("scenes") if isinstance(content_contract.get("scenes"), list) else []
        first = scenes[0] if scenes and isinstance(scenes[0], dict) else {}
        last = scenes[-1] if scenes and isinstance(scenes[-1], dict) else {}
        metric = str(first.get("metricLabel") or first.get("factUnit") or "CELEBRITY DATA").strip().upper()
        top_name = cls._person_name(str(last.get("title", "Celebrity")))
        base_title = str(content_contract.get("youtube_title") or content_contract.get("title") or "Celebrity Data Comparison").strip()
        titles = [
            f"Celebrity {metric.title()} Numbers That Feel Unreal",
            f"{top_name} vs Everyone Else: The {metric.title()} Gap",
            f"Most Surprising Celebrity {metric.title()} in 2026",
            base_title[:90],
            f"The Celebrity Ranking Where #{1} Changes Everything",
        ]
        title_variants = [
            {
                "title": cls._clean_title(title),
                "format": ["data_shock", "comparison", "trend_year", "direct_search", "curiosity"][index],
                "score_breakdown": {
                    "search": 82 - index,
                    "curiosity": 94 - index,
                    "trend": 84,
                    "specificity": 88,
                    "safety": 96,
                },
            }
            for index, title in enumerate(titles)
        ]
        return cls._normalize_payload(
            {
                "trend_angle": f"2026 celebrity {metric.lower()} data gap",
                "title_variants": title_variants,
                "description_variants": [
                    str(content_contract.get("youtube_description", "")).strip()
                    or f"A fact-safe celebrity data comparison using public {metric.lower()} estimates.",
                    f"These celebrity {metric.lower()} numbers are ranked from public estimates.",
                    f"Watch the full countdown and compare the biggest {metric.lower()} gaps.",
                ],
                "tags": [
                    "celebrity",
                    "data comparison",
                    "celebrity ranking",
                    metric.lower(),
                    "famous people",
                    "2026",
                    "shorts",
                    "comparison",
                    "viral data",
                    "ranking",
                    "entertainment",
                    "public estimates",
                ],
                "thumbnail_text_suggestions": ["THE GAP", f"{metric}?!", "WHO LEADS?"],
                "search_keywords": cls._keywords_from_contract(content_contract),
            },
            content_contract=content_contract,
        )

    @staticmethod
    def _normalize_score_breakdown(value: Any) -> dict[str, int]:
        source = value if isinstance(value, dict) else {}
        return {
            key: max(0, min(100, int(float(source.get(key, 75)))))
            for key in ("search", "curiosity", "trend", "specificity", "safety")
        }

    @staticmethod
    def _score_total(score_breakdown: dict[str, int]) -> float:
        return round(
            score_breakdown["search"] * 0.25
            + score_breakdown["curiosity"] * 0.25
            + score_breakdown["trend"] * 0.20
            + score_breakdown["specificity"] * 0.20
            + score_breakdown["safety"] * 0.10,
            2,
        )

    @staticmethod
    def _string_list(value: Any, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned

    @staticmethod
    def _clean_title(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()[:90]

    @staticmethod
    def _person_name(value: str) -> str:
        return re.sub(r"^#\s*\d+\s*", "", value).strip() or "Celebrity"

    @staticmethod
    def _thumbnail_text_from_title(title: str) -> str:
        words = title.upper().split()
        return " ".join(words[:3])[:24] or "DATA GAP"

    @classmethod
    def _keywords_from_contract(cls, content_contract: dict[str, Any]) -> list[str]:
        title = str(content_contract.get("title") or content_contract.get("youtube_title") or "")
        scenes = content_contract.get("scenes") if isinstance(content_contract.get("scenes"), list) else []
        names = [cls._person_name(str(scene.get("title", ""))) for scene in scenes[:4] if isinstance(scene, dict)]
        return cls._string_list(
            [
                title.lower(),
                "celebrity data comparison",
                "celebrity ranking 2026",
                *[name.lower() for name in names],
            ],
            limit=10,
        )
