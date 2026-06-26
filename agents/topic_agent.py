"""Topic generation agent — generates high-potential YouTube video topics."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from core import database as db
from core.config import get_settings

logger = logging.getLogger(__name__)

# ── Category hints (synced from test_video.py) ───────────────
CATEGORY_HINTS = {
    "Evolution": "the evolution/history of a specific technology, product, vehicle, tool, concept, or industry. Think: phones, cars, computers, weapons, medicine, architecture, fashion, money, sports, music, food, energy, maps, lighting, etc.",
    "Ranking": "a top 20 ranking of something fascinating: most dangerous, most expensive, most powerful, strangest, biggest, deadliest, etc. in any domain: animals, countries, disasters, inventions, crimes, buildings, sports records, etc.",
    "WhatIf": "a mind-bending hypothetical scenario about nature, physics, biology, society, or technology. Think: what if gravity reversed, what if the sun disappeared, what if humans could fly, etc.",
    "Science": "a fascinating scientific topic that blows people's minds. Think: quantum physics, black holes, DNA, the brain, parasites, the ocean floor, antimatter, time, infinity, etc.",
    "History": "a dramatic historical event, era, empire, war, or figure that most people don't know the full story of.",
    "Comparison": "a fascinating comparison between two things people think they understand but actually don't.",
    "Geography": "a ranking or exploration of countries, cities, natural wonders, or geographic extremes.",
    "Celebrity": "a THEMED RANKING of celebrities/famous people with specific data. PROVEN VIRAL TOPICS: Top 100 richest actors/singers in 2026, oldest celebrities still alive, celebrities who died from overdoses, Hollywood actors with most Oscar wins, longest celebrity marriages, youngest billionaires, celebrities over 50 without children, famous last words of legends, musicians who died too young, most followed on social media, celebrity transformations, K-pop idols net worth, tallest/shortest celebrities, celebrities who went from poor to rich. ALWAYS use a specific NUMBER in the topic (Top 40, 50 oldest, etc.) and add YEAR (2026) when relevant.",
}


class TopicAgent(BaseAgent):
    """Generate YouTube video topics informed by reference channel analysis.

    Uses reference channel data (top categories, title patterns, topic gaps)
    to generate SEO-optimised topics scored on search volume, CTR potential,
    competition, and data availability.
    """

    def __init__(self) -> None:
        super().__init__(name="topic_agent")
        settings = get_settings()
        self._history_path: Path = settings.storage_dir / "topics_history.json"

    # ── Topic history tracking ────────────────────────────────

    def _load_topic_history(self) -> list[dict[str, Any]]:
        """Load topic history from JSON file."""
        if self._history_path.exists():
            try:
                return json.loads(self._history_path.read_text())
            except (json.JSONDecodeError, Exception):
                return []
        return []

    def _save_topic_history(self, entry: dict[str, Any]) -> None:
        """Append a new topic entry to history."""
        history = self._load_topic_history()
        history.append(entry)
        self._history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2)
        )

    async def run(
        self, category: str, language: str = "vi", count: int = 5,
    ) -> list[dict[str, Any]]:
        """Generate and store scored video topics for a given category.

        Args:
            category: Video category (e.g. ``WhatIf``, ``Ranking``, ``History``).
            language: Target language code (default: ``vi``).
            count: Number of topics to generate (AI may return more).

        Returns:
            A list of accepted topic dicts inserted into the database.
        """
        await self.log(topic_id=None, status="running")

        try:
            # ── Step 1: Fetch reference channel data ────────────
            reference_data = await self._fetch_reference_data()
            self.logger.info(
                "Loaded reference data from %d channel(s)", len(reference_data)
            )

            # ── Step 2: Load topic history for dedup ────────────
            used_topics = self._load_topic_history()
            used_in_category = [
                t["subtopic"] for t in used_topics if t.get("category") == category
            ]
            self.logger.info(
                "Loaded %d previously used subtopics for category %s",
                len(used_in_category), category,
            )

            # ── Step 3: Generate topics (two-step per topic) ────
            raw_topics: list[dict[str, Any]] = []
            for i in range(count):
                self.logger.info("Generating topic %d/%d...", i + 1, count)

                # Step 3a: AI generates a fresh subtopic
                subtopic = await self._ai_generate_subtopic(
                    category=category,
                    language=language,
                    used_subtopics=used_in_category,
                    reference_data=reference_data,
                )
                self.logger.info("  AI-generated subtopic: %s", subtopic)

                # Step 3b: Generate full topic around that subtopic
                topic = await self._generate_topic_from_subtopic(
                    category=category,
                    language=language,
                    subtopic=subtopic,
                    reference_data=reference_data,
                )
                raw_topics.append(topic)

                # Track the subtopic to avoid repeats in this batch
                used_in_category.append(subtopic)

            self.logger.info("AI generated %d raw topics", len(raw_topics))

            # ── Step 4: Filter by score threshold ───────────────
            qualified = [t for t in raw_topics if t.get("score", 0) >= 80]
            self.logger.info(
                "%d / %d topics passed score threshold (>= 80)",
                len(qualified), len(raw_topics),
            )

            # ── Step 5: Dedup against existing topics ───────────
            accepted: list[dict[str, Any]] = []
            for topic in qualified:
                title = topic.get("title", "").strip()
                if not title:
                    continue

                exists = await db.fetchval(
                    "SELECT COUNT(*) FROM topics WHERE title = $1 AND language = $2",
                    title, language,
                )
                if exists and exists > 0:
                    self.logger.debug("Skipping duplicate topic: %s", title)
                    continue

                # ── Step 6: Insert into database ────────────────
                topic_id = await self._insert_topic(topic, language, reference_data)
                topic["id"] = topic_id
                accepted.append(topic)

                # ── Save to topic history ───────────────────────
                self._save_topic_history({
                    "category": category,
                    "subtopic": topic.get("subtopic", ""),
                    "title": title,
                    "language": language,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            self.logger.info(
                "Accepted %d new topics (category=%s, language=%s)",
                len(accepted), category, language,
            )

            await self.log(topic_id=None, status="completed")
            await self.notify(
                f"Generated <b>{len(accepted)}</b> new topics "
                f"for category <b>{category}</b> ({language})"
            )
            return accepted

        except Exception as exc:
            await self.log(topic_id=None, status="failed", error=str(exc))
            await self.notify(f"❌ Topic generation failed: {exc}")
            raise

    # ── Reference data loading ────────────────────────────────

    async def _fetch_reference_data(self) -> list[dict[str, Any]]:
        """Fetch analysed reference channel data from the database.

        Returns:
            A list of dicts with ``top_categories``, ``title_patterns``,
            ``topic_gaps``, and ``content_style`` per channel.
        """
        rows = await db.fetch(
            """
            SELECT id, channel_name, top_categories, title_patterns,
                   topic_gaps, content_style
            FROM reference_channels
            WHERE last_analyzed_at IS NOT NULL
            ORDER BY last_analyzed_at DESC
            LIMIT 10
            """
        )

        results: list[dict[str, Any]] = []
        for row in rows:
            top_categories = row.get("top_categories") or []
            if isinstance(top_categories, str):
                top_categories = json.loads(top_categories)

            title_patterns = row.get("title_patterns") or []
            if isinstance(title_patterns, str):
                title_patterns = json.loads(title_patterns)

            topic_gaps = row.get("topic_gaps") or []
            if isinstance(topic_gaps, str):
                topic_gaps = json.loads(topic_gaps)

            results.append({
                "channel_id": row["id"],
                "channel_name": row["channel_name"],
                "top_categories": top_categories,
                "title_patterns": title_patterns,
                "topic_gaps": topic_gaps,
                "content_style": row.get("content_style", ""),
            })

        return results

    # ── Two-step AI topic generation ──────────────────────────

    async def _ai_generate_subtopic(
        self,
        category: str,
        language: str,
        used_subtopics: list[str],
        reference_data: list[dict[str, Any]],
    ) -> str:
        """Let AI generate a fresh, creative subtopic that hasn't been used.

        Args:
            category: Target video category.
            language: Target language code.
            used_subtopics: List of previously used subtopics to avoid.
            reference_data: Reference channel data for context.

        Returns:
            A specific subtopic string.
        """
        language_names: dict[str, str] = {
            "vi": "Vietnamese",
            "en": "English",
            "ja": "Japanese",
        }
        language_name = language_names.get(language, language)

        hint = CATEGORY_HINTS.get(category, "an interesting educational topic")

        # Show last 30 used subtopics to prevent repeats
        used_list = (
            "\n".join(f"- {t}" for t in used_subtopics[-30:])
            if used_subtopics
            else "None yet"
        )

        # Aggregate topic gaps from reference data for richer suggestions
        all_gaps: list[str] = []
        for ref in reference_data:
            all_gaps.extend(ref.get("topic_gaps", []))
        unique_gaps = list(dict.fromkeys(all_gaps))[:20]
        gaps_context = (
            f"\nTopic gaps from successful channels (high potential): {json.dumps(unique_gaps, ensure_ascii=False)}"
            if unique_gaps
            else ""
        )

        prompt = f"""You are a YouTube content strategist. Generate 1 SPECIFIC, FRESH subtopic for a "{category}" video.

The subtopic should be about: {hint}
{gaps_context}

ALREADY USED SUBTOPICS (DO NOT repeat these):
{used_list}

Rules:
1. Must be SPECIFIC (not "technology" but "điện thoại di động" or "dao kéo")
2. Must be something with RICH visual content (good for video)
3. Must have enough historical depth for 20 cards
4. Must be DIFFERENT from all used subtopics above
5. Think about what's TRENDING or what viewers are curious about right now

Return JSON:
{{
    "subtopic": "specific subtopic in {language_name}, 2-5 words",
    "reason": "why this topic will get views"
}}"""

        system_prompt = (
            "You are a YouTube content strategist specializing in viral video topics. "
            "Return a valid JSON object only."
        )

        result = await self.ai_json(prompt, system=system_prompt)
        return result.get("subtopic", "công nghệ thú vị")

    async def _generate_topic_from_subtopic(
        self,
        category: str,
        language: str,
        subtopic: str,
        reference_data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate a full scored topic around a specific subtopic.

        Args:
            category: Target video category.
            language: Target language code.
            subtopic: The specific subtopic to build the topic around.
            reference_data: Reference channel data for context.

        Returns:
            A topic dict with title, subtitle, hook, subtopic, score,
            score_details, and category.
        """
        language_names: dict[str, str] = {
            "vi": "Vietnamese",
            "en": "English",
            "ja": "Japanese",
        }
        language_name = language_names.get(language, language)

        # Aggregate reference insights
        all_categories: list[dict[str, Any]] = []
        all_patterns: list[str] = []

        for ref in reference_data:
            all_categories.extend(ref.get("top_categories", []))
            all_patterns.extend(ref.get("title_patterns", []))

        unique_patterns = list(dict.fromkeys(all_patterns))[:10]
        category_summary = self._summarise_categories(all_categories)

        prompt = f"""Generate 1 YouTube video topic for category "{category}" in {language_name}.

SPECIFIC SUBTOPIC: The video MUST be about "{subtopic}".
DO NOT make a video about con người/human body/human evolution unless the subtopic specifically says so.

Reference data from successful channels:
- Top categories and average views: {json.dumps(category_summary, ensure_ascii=False)}
- Successful title patterns: {json.dumps(unique_patterns, ensure_ascii=False)}

The topic MUST be:
- Extremely click-worthy (gây tò mò mạnh)
- Suitable for an educational/infotainment channel
- About "{subtopic}" specifically
- Something that could go viral (lên xu hướng)

Return JSON:
{{
    "title": "catchy title about {subtopic}, max 60 chars, in {language_name}",
    "subtitle": "banner text for the video, max 40 chars",
    "category": "{category}",
    "hook": "1 sentence that makes viewers NEED to watch",
    "subtopic": "{subtopic}",
    "score": 0-100 based on: search_volume(40%), ctr_potential(30%), competition(20%), data_availability(10%),
    "score_details": {{"search_volume": 0-100, "ctr_potential": 0-100, "competition": 0-100, "data_availability": 0-100}}
}}"""

        system_prompt = (
            "You are a YouTube content strategist specializing in viral video topics. "
            "Generate topics that balance search demand with low competition. "
            "Return a valid JSON object only."
        )

        result = await self.ai_json(prompt, system=system_prompt)

        # Normalise: ensure it's a single topic dict
        if isinstance(result, list) and len(result) > 0:
            result = result[0]
        if not isinstance(result, dict):
            result = {}

        # Ensure required fields are present
        result.setdefault("title", f"{subtopic}")
        result.setdefault("subtitle", "")
        result.setdefault("hook", "")
        result.setdefault("subtopic", subtopic)
        result.setdefault("category", category)
        result.setdefault("score", 0)
        result.setdefault("score_details", {})

        return result

    @staticmethod
    def _summarise_categories(
        categories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Aggregate category performance across multiple channels.

        Args:
            categories: Raw category entries from reference channels.

        Returns:
            Deduplicated category summaries with combined view stats.
        """
        agg: dict[str, dict[str, Any]] = {}
        for cat in categories:
            name = cat.get("category", "Other")
            if name not in agg:
                agg[name] = {"category": name, "total_views": 0, "count": 0}
            agg[name]["total_views"] += cat.get("avg_views", 0) * cat.get("count", 1)
            agg[name]["count"] += cat.get("count", 0)

        result: list[dict[str, Any]] = []
        for entry in agg.values():
            count = entry["count"] if entry["count"] > 0 else 1
            result.append({
                "category": entry["category"],
                "avg_views": round(entry["total_views"] / count),
                "count": entry["count"],
            })

        return sorted(result, key=lambda x: x["avg_views"], reverse=True)

    # ── Database insertion ────────────────────────────────────

    async def _insert_topic(
        self,
        topic: dict[str, Any],
        language: str,
        reference_data: list[dict[str, Any]],
    ) -> int:
        """Insert a single topic into the topics table.

        Args:
            topic: Topic dict from AI (title, category, score, score_details).
            language: Language code.
            reference_data: Reference channel data (used to link ``inspired_by``).

        Returns:
            The new topic's database ID.
        """
        # Link to first reference channel if available
        inspired_by: int | None = None
        if reference_data:
            inspired_by = reference_data[0].get("channel_id")

        score_details = topic.get("score_details", {})
        if isinstance(score_details, str):
            score_details = json.loads(score_details)

        row = await db.fetchrow(
            """
            INSERT INTO topics
                (title, category, language, score, score_details, inspired_by, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            topic["title"].strip(),
            topic.get("category", ""),
            language,
            float(topic.get("score", 0)),
            json.dumps(score_details),
            inspired_by,
            "pending",
            datetime.now(timezone.utc),
        )
        return row["id"]  # type: ignore[index]
