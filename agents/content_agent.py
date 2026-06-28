"""Content planning agent for MVP video scripts and metadata."""

from __future__ import annotations

import json
from typing import Any

from agents.base_agent import BaseAgent
from core.video_contract import (
    build_content_contract_v2,
    canonical_country_label,
    normalize_country_code,
    validate_content_contract_v2,
)

_CELEBRITY_GROUP_NAMES = {
    "bts",
    "blackpink",
    "coldplay",
    "one direction",
    "the beatles",
    "beatles",
    "the rolling stones",
    "rolling stones",
    "u2",
}

_FIXED_TEMPLATE_SECONDS = 8
_SECONDS_PER_CARD = 5.0
_MIN_DURATION_SCENES = 6
_MAX_DURATION_SCENES = 24


class ContentAgent(BaseAgent):
    """Build a production-shaped content contract without external side effects."""

    def __init__(self) -> None:
        super().__init__(name="content_agent")

    async def run(
        self,
        *,
        niche: str,
        language: str = "vi",
        subject: str = "người nổi tiếng",
        card_layout: str = "flag_hero",
        selected_topic: dict[str, Any] | None = None,
        duration_target: int = 60,
    ) -> dict[str, Any]:
        """Return a complete content contract for the requested niche."""
        normalized_niche = niche.strip().lower() or "celebrity"
        if normalized_niche in {
            "country_comparison_comedy",
            "country_comparison",
            "world_differences",
            "so_sanh_quoc_gia_hai_huoc",
        }:
            contract = self._build_country_comparison_comedy_contract(
                language=language,
                subject=subject,
            )
            validate_content_contract_v2(contract)
            return contract

        contract = await self._build_ai_celebrity_contract(
            language=language,
            subject=subject,
            card_layout=card_layout,
            selected_topic=selected_topic,
            duration_target=duration_target,
        )
        validate_content_contract_v2(contract)
        return contract

    async def _build_ai_celebrity_contract(
        self,
        *,
        language: str,
        subject: str,
        card_layout: str,
        selected_topic: dict[str, Any] | None = None,
        duration_target: int = 60,
    ) -> dict[str, Any]:
        try:
            topic = selected_topic or await self._generate_celebrity_topic(
                language=language,
                subject=subject,
            )
            contract = await self._generate_celebrity_contract_from_topic(
                language=language,
                subject=subject,
                topic=topic,
                card_layout=card_layout,
                duration_target=duration_target,
                desired_scene_count=self.desired_scene_count_for_duration(duration_target),
            )
            validate_content_contract_v2(contract)
            return contract
        except Exception as exc:
            if selected_topic is not None:
                raise
            self.logger.warning("Falling back to seeded celebrity contract: %s", exc)
            return self._build_celebrity_contract(
                language=language,
                subject=subject,
                card_layout=card_layout,
                duration_target=duration_target,
            )

    async def _generate_celebrity_topic(
        self,
        *,
        language: str,
        subject: str,
    ) -> dict[str, Any]:
        prompt = f"""Generate 1 optimized Celebrity topic for a YouTube data-comparison video.

Niche: Celebrity / famous people statistics
Audience language: {language}
Subject hint: {subject}

Choose a topic that can be rendered as ranking cards and is likely to perform well:
- richest singers/actors
- most followed celebrities
- youngest/oldest celebrities in a category
- highest paid actors
- celebrity transformations with measurable before/after data
- longest marriages or career milestones

Rules:
1. Return a specific ranking topic, not a generic category.
2. Prefer topics with real public data and real image availability.
3. Avoid defamation, private allegations, medical claims, or unsafe gossip.
4. Include the metric label that each card should compare.

Return JSON only:
{{
  "title": "Top 10 ...",
  "angle": "short_snake_case_angle",
  "metric_label": "NET WORTH | FOLLOWERS | AGE | HEIGHT | AWARDS | YEARS",
  "reason": "why this topic can get views"
}}"""
        system = (
            "You are a YouTube strategist for celebrity data-comparison videos. "
            "Return valid JSON only. Optimize for viral potential, data availability, "
            "and image verification."
        )
        topic = await self.ai_json(prompt, system=system)
        if not isinstance(topic, dict) or not str(topic.get("title", "")).strip():
            raise ValueError("AI celebrity topic is missing title")
        topic.setdefault("metric_label", "NET WORTH")
        topic.setdefault("angle", "celebrity_ranking")
        topic.setdefault("reason", "")
        return topic

    async def _generate_celebrity_contract_from_topic(
        self,
        *,
        language: str,
        subject: str,
        topic: dict[str, Any],
        card_layout: str,
        duration_target: int = 60,
        desired_scene_count: int | None = None,
    ) -> dict[str, Any]:
        scene_count = desired_scene_count or self.desired_scene_count_for_duration(duration_target)
        prompt = f"""Create a complete content_contract_v2 payload for a Celebrity data-comparison video.

Topic candidate:
{json.dumps(topic, ensure_ascii=False, indent=2)}

Language: {language}
Subject hint: {subject}

Hard rules:
1. Use exactly {scene_count} ranking scenes.
2. Each scene must be one real public celebrity/person.
3. Each scene must include short voiceover, caption, image_prompt, statusText.
4. Each scene must include countryCode and countryLabel matching the person's nationality/origin.
5. Each scene must include metricLabel and metricValue.
6. Numbers must be phrased as public estimates when exact live data may change.
7. Do not invent scandals, private allegations, health claims, or criminal claims.
8. image_prompt must ask for a real editorial/photo-source image, not AI art.
9. Put lower ranks first and #1 last so the video builds suspense.
10. Use individual people only. Do not use bands, groups, teams, brands, couples, or families.
11. Follow content_format, metric_scope, and time_scope from the topic exactly.
12. For factual formats include factClaim, factValue, factUnit, factAsOf, and factContext in every scene.

Return JSON only with this shape:
{{
  "title": "video title",
  "hook": "short hook sentence",
  "target_audience": "who this is for",
  "youtube_title": "SEO title",
  "youtube_description": "description including public estimate/source caution",
  "youtube_tags": ["celebrity", "data comparison"],
  "thumbnail_prompt": "thumbnail prompt",
  "scenes": [
    {{
      "title": "#10 Celebrity Name",
      "voiceover": "one concise sentence",
      "caption": "short metric text",
      "image_prompt": "real editorial photo of Celebrity Name",
      "statusText": "#10 | metric",
      "countryCode": "US",
      "countryLabel": "UNITED STATES",
      "metricLabel": "{topic.get("metric_label", "NET WORTH")}",
      "metricValue": "metric",
      "sourceRequirement": "what source must later verify this"
    }}
  ]
}}"""
        system = (
            "You are a production content planner for YouTube Shorts-style data "
            "comparison videos. Return strict JSON only. Favor verifiable public data."
        )
        raw_contract = await self.ai_json(prompt, system=system)
        if not isinstance(raw_contract, dict):
            raise ValueError("AI celebrity contract must be an object")

        return self._normalize_ai_celebrity_contract(
            raw_contract=raw_contract,
            language=language,
            topic=topic,
            card_layout=card_layout,
            duration_target=duration_target,
            desired_scene_count=scene_count,
        )

    @staticmethod
    def _normalize_ai_celebrity_contract(
        *,
        raw_contract: dict[str, Any],
        language: str,
        topic: dict[str, Any],
        card_layout: str,
        duration_target: int = 60,
        desired_scene_count: int | None = None,
    ) -> dict[str, Any]:
        scenes = raw_contract.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("AI celebrity contract requires scenes")
        scene_count = desired_scene_count or ContentAgent.desired_scene_count_for_duration(duration_target)
        if len(scenes) < scene_count:
            raise ValueError(
                f"AI celebrity contract requires at least {scene_count} scenes, got {len(scenes)}"
            )

        normalized_scenes: list[dict[str, Any]] = []
        metric_label = str(topic.get("metric_label", "NET WORTH") or "NET WORTH").strip()
        for index, scene in enumerate(scenes[:scene_count]):
            if not isinstance(scene, dict):
                raise ValueError(f"scene {index} must be an object")
            title = str(scene.get("title", "")).strip()
            person_name = ContentAgent._extract_ranked_name(title)
            if ContentAgent._is_group_or_band_name(person_name):
                raise ValueError(f"scene {index} is not an individual person: {person_name}")
            metric_value = str(scene.get("metricValue", scene.get("caption", ""))).strip()
            country_code = normalize_country_code(str(scene.get("countryCode", "")))
            country_label = canonical_country_label(country_code)
            if not country_label:
                country_label = str(scene.get("countryLabel", "")).strip().upper()
            fact_value = str(scene.get("factValue") or metric_value).strip()
            fact_unit = str(scene.get("factUnit") or metric_label).strip().upper()
            fact_as_of = str(scene.get("factAsOf") or topic.get("time_scope") or "2026").strip()
            fact_context = str(
                scene.get("factContext")
                or scene.get("sourceRequirement")
                or topic.get("metric_scope")
                or "public estimate"
            ).strip()
            fact_claim = str(scene.get("factClaim") or "").strip()
            if not fact_claim and topic.get("content_format"):
                fact_claim = (
                    f"{person_name} has a public {metric_label.lower()} estimate "
                    f"of {fact_value} as of {fact_as_of}."
                )
            normalized_scenes.append(
                {
                    "title": title,
                    "voiceover": str(scene.get("voiceover", "")).strip(),
                    "caption": str(scene.get("caption", metric_value)).strip(),
                    "image_prompt": str(scene.get("image_prompt", "")).strip(),
                    "statusText": str(scene.get("statusText", metric_value)).strip(),
                    "countryCode": country_code,
                    "countryLabel": country_label,
                    "metricLabel": str(scene.get("metricLabel", metric_label)).strip().upper(),
                    "metricValue": metric_value,
                    "sourceRequirement": str(
                        scene.get("sourceRequirement", "public source required")
                    ).strip(),
                    **(
                        {
                            "factClaim": fact_claim,
                            "factValue": fact_value,
                            "factUnit": fact_unit,
                            "factAsOf": fact_as_of,
                            "factContext": fact_context,
                        }
                        if topic.get("content_format")
                        else {}
                    ),
                }
            )

        tags = raw_contract.get("youtube_tags")
        youtube_tags = [str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else []
        if "data comparison" not in youtube_tags:
            youtube_tags.append("data comparison")
        if "celebrity" not in youtube_tags:
            youtube_tags.append("celebrity")

        return build_content_contract_v2(
            niche="celebrity",
            title=str(raw_contract.get("title", topic["title"])).strip(),
            hook=str(raw_contract.get("hook", topic.get("reason", ""))).strip(),
            target_audience=str(
                raw_contract.get(
                    "target_audience",
                    "Viewers who like celebrity statistics and data comparison.",
                )
            ).strip(),
            language=language,
            scenes=normalized_scenes,
            thumbnail_prompt=str(raw_contract.get("thumbnail_prompt", "")).strip(),
            youtube_title=str(raw_contract.get("youtube_title", topic["title"])).strip(),
            youtube_description=str(raw_contract.get("youtube_description", "")).strip(),
            youtube_tags=youtube_tags,
            duration_target=duration_target,
            cardLayout=card_layout,
            contentFormat=(
                str(topic["content_format"]) if topic.get("content_format") else None
            ),
            metricScope=str(topic.get("metric_scope", "")),
            timeScope=str(topic.get("time_scope", "")),
        )

    @staticmethod
    def desired_scene_count_for_duration(duration_target: int) -> int:
        raw_count = round((duration_target - _FIXED_TEMPLATE_SECONDS) / _SECONDS_PER_CARD)
        return max(_MIN_DURATION_SCENES, min(_MAX_DURATION_SCENES, raw_count))

    @staticmethod
    def _extract_ranked_name(title: str) -> str:
        parts = title.strip().split(" ", 1)
        return parts[1].strip() if parts and parts[0].startswith("#") and len(parts) > 1 else title.strip()

    @staticmethod
    def _is_group_or_band_name(name: str) -> bool:
        normalized = name.strip().lower()
        return normalized in _CELEBRITY_GROUP_NAMES

    @staticmethod
    def _build_country_comparison_comedy_contract(
        *,
        language: str,
        subject: str,
    ) -> dict[str, Any]:
        scenario = subject.strip() or "parents reward good grades"
        title = "How Parents Reward Good Grades in Different Countries"
        hook = "Same school moment, wildly different country reactions."
        target_audience = (
            "Người xem thích country comparison, school life comedy, family humor, "
            "cultural memes và video hoạt hình ngắn dễ xem."
        )
        country_items = [
            ("JP", "JAPAN", "Silent Nod", "Mom just nods. Somehow, that feels like fireworks."),
            ("US", "UNITED STATES", "Pizza Night", "Good grades unlock pizza, games, and one proud selfie."),
            ("MX", "MEXICO", "La Fiesta", "The whole family hears about that A before dinner."),
            ("PH", "PHILIPPINES", "Jollibee Feast", "One high score can turn into a crispy chicken celebration."),
            ("KR", "SOUTH KOREA", "Study Upgrade", "Great score? Nice. Now prepare for the next academy."),
            ("BR", "BRAZIL", "Big Hug", "Mom celebrates loudly enough for the neighbors to join."),
            ("IN", "INDIA", "Family Broadcast", "Your report card reaches every auntie before you sit down."),
            ("GB", "UNITED KINGDOM", "Calm Praise", "A quiet well done, then tea like nothing happened."),
            ("VN", "VIETNAM", "Proud But Strict", "Mom smiles first, then asks why it was not higher."),
            ("AE", "UNITED ARAB EMIRATES", "Luxury Reward", "In the fantasy version, even the reward looks expensive."),
        ]

        scenes = [
            {
                "title": reaction,
                "voiceover": voiceover,
                "caption": reaction,
                "image_prompt": (
                    "2D animated country comparison comedy scene, school report card, "
                    f"{country_label} family reaction to good grades, expressive characters, "
                    "bright YouTube animation, respectful cultural humor, no real person"
                ),
                "statusText": f"{country_label} | {reaction}",
                "countryCode": country_code,
                "countryLabel": country_label,
                "metricLabel": "REACTION",
                "metricValue": reaction,
            }
            for country_code, country_label, reaction, voiceover in country_items
        ]

        return build_content_contract_v2(
            niche="country_comparison_comedy",
            title=title,
            hook=hook,
            target_audience=target_audience,
            language=language,
            scenes=scenes,
            thumbnail_prompt=(
                "Funny country comparison thumbnail, school report card, flags, shocked parents, "
                "bold text, colorful 2D animation style"
            ),
            youtube_title=f"{title} 🌍",
            youtube_description=(
                "Entertainment and edutainment country comparison video inspired by school life, "
                "family comedy, cultural memes, and common stereotypes. This is not a factual "
                "claim about every family in each country."
            ),
            youtube_tags=[
                "country comparison",
                "different countries",
                "school life",
                "family comedy",
                "world differences",
                "animation",
                "funny parents",
                "good grades",
            ],
            duration_target=60,
            cardLayout="flag_hero",
        )

    @staticmethod
    def _build_celebrity_contract(
        *,
        language: str,
        subject: str,
        card_layout: str = "flag_hero",
        duration_target: int = 60,
    ) -> dict[str, Any]:
        safe_subject = subject.strip() or "người nổi tiếng"
        title = "Top 10 ca sĩ giàu nhất thế giới năm 2026"
        hook = "Data comparison theo estimated net worth, dùng số liệu ước tính công khai."
        target_audience = (
            "Người xem Việt Nam thích video thống kê người nổi tiếng, ranking, "
            "so sánh tài sản và dữ liệu giải trí dễ xem."
        )
        ranking_items = [
            (
                10,
                "Celine Dion",
                550,
                "catalog âm nhạc, tour diễn và thương hiệu Las Vegas",
                "CA",
                "CANADA",
            ),
            (
                9,
                "Elton John",
                650,
                "tour diễn toàn cầu, bản quyền âm nhạc và catalog kinh điển",
                "GB",
                "UNITED KINGDOM",
            ),
            (
                8,
                "Dolly Parton",
                700,
                "bản quyền sáng tác, kinh doanh giải trí và di sản âm nhạc",
                "US",
                "UNITED STATES",
            ),
            (
                7,
                "Bono",
                750,
                "U2, touring, bản quyền và các khoản đầu tư dài hạn",
                "IE",
                "IRELAND",
            ),
            (
                6,
                "Lady Gaga",
                900,
                "âm nhạc, diễn xuất, touring và thương hiệu giải trí toàn cầu",
                "US",
                "UNITED STATES",
            ),
            (
                5,
                "Taylor Swift",
                1100,
                "tour Eras, catalog thu âm và quyền kiểm soát master",
                "US",
                "UNITED STATES",
            ),
            (
                4,
                "Paul McCartney",
                1300,
                "The Beatles, sáng tác, bản quyền và tour diễn",
                "GB",
                "UNITED KINGDOM",
            ),
            (
                3,
                "Rihanna",
                1400,
                "âm nhạc, Fenty Beauty và hệ sinh thái thương hiệu",
                "BB",
                "BARBADOS",
            ),
            (
                2,
                "Beyonce",
                1600,
                "tour diễn, catalog, thương hiệu và dự án giải trí",
                "US",
                "UNITED STATES",
            ),
            (
                1,
                "Jay-Z",
                2500,
                "âm nhạc, đầu tư, rượu champagne và danh mục kinh doanh",
                "US",
                "UNITED STATES",
            ),
        ]

        scenes = [
            {
                "title": f"#{rank} {name}",
                "voiceover": (
                    f"#{rank} là {name}, với estimated net worth khoảng "
                    f"{value}M USD từ {reason}."
                ),
                "caption": f"{value}M USD",
                "image_prompt": (
                    f"editorial celebrity data comparison card for {name}, premium stage lighting, "
                    "clean ranking layout, no logo, respectful entertainment style"
                ),
                "statusText": f"#{rank} | {value}M USD",
                "countryCode": country_code,
                "countryLabel": country_label,
                "metricLabel": "NET WORTH",
                "metricValue": f"{value}M USD",
            }
            for rank, name, value, reason, country_code, country_label in ranking_items
        ]

        return build_content_contract_v2(
            niche="celebrity",
            title=title,
            hook=hook,
            target_audience=target_audience,
            language=language,
            scenes=scenes,
            thumbnail_prompt=(
                "Top 10 richest singers 2026 YouTube thumbnail, gold numbers, celebrity silhouettes, "
                "bold ranking text area, red and white accents, high contrast"
            ),
            youtube_title=f"Top 10 {safe_subject} giàu nhất thế giới năm 2026",
            youtube_description=(
                "Video data comparison xếp hạng ca sĩ giàu nhất thế giới theo estimated net worth. "
                "Các con số là ước tính công khai và cần được fact-check trước khi xuất bản thật."
            ),
            youtube_tags=[
                "nguoi noi tieng",
                "data comparison",
                "richest singers",
                "top 10 celebrities",
                "giai tri",
                "thong ke so sanh",
            ],
            duration_target=duration_target,
            cardLayout=card_layout,
        )
