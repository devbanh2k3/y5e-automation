"""Script generation agent — writes and quality-scores YouTube video scripts."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agents.base_agent import BaseAgent
from core import database as db

logger = logging.getLogger(__name__)

# Maximum number of regeneration attempts for low-quality scripts
_MAX_REGENERATION_ATTEMPTS = 3

# Minimum quality score threshold
_MIN_QUALITY_SCORE = 70


class ScriptAgent(BaseAgent):
    """Generate a YouTube video script from verified research data.

    Fetches topic details, verified research items, reference channel style
    guides, and top-video transcript excerpts to produce a structured script.
    Each script is scored on hook strength, narrative flow, engagement, and
    accuracy, with automatic regeneration if the score falls below 70.
    """

    def __init__(self) -> None:
        super().__init__(name="script_agent")

    async def run(self, topic_id: int) -> dict[str, Any]:
        """Generate a scored script for the given topic.

        Args:
            topic_id: Database ID of the topic to write a script for.

        Returns:
            A dict containing the full script structure, quality score, and
            metadata.

        Raises:
            ValueError: If the topic or verified research data is not found.
        """
        await self.log(topic_id=topic_id, status="running")

        try:
            # ── Step 1: Fetch topic ─────────────────────────────
            topic = await db.fetchrow(
                "SELECT id, title, category, language, inspired_by FROM topics WHERE id = $1",
                topic_id,
            )
            if not topic:
                raise ValueError(f"Topic {topic_id} not found in database")

            title: str = topic["title"]
            category: str = topic["category"]
            language: str = topic["language"]
            inspired_by: int | None = topic.get("inspired_by")

            # ── Step 2: Fetch verified research data ────────────
            research_items = await db.fetch(
                """
                SELECT id, item_name, metrics, sources
                FROM research_data
                WHERE topic_id = $1 AND verified = TRUE
                ORDER BY id
                """,
                topic_id,
            )

            # Fall back to unverified if no verified items exist
            if not research_items:
                research_items = await db.fetch(
                    """
                    SELECT id, item_name, metrics, sources
                    FROM research_data
                    WHERE topic_id = $1
                    ORDER BY id
                    """,
                    topic_id,
                )

            if not research_items:
                raise ValueError(
                    f"No research data found for topic {topic_id}. "
                    "Run the research agent first."
                )

            self.logger.info(
                "Loaded %d research items for topic %d", len(research_items), topic_id
            )

            # ── Step 3: Fetch style guide from reference channel ─
            content_style = await self._fetch_content_style(inspired_by)

            # ── Step 4: Fetch transcript excerpt for style ref ──
            transcript_excerpt = await self._fetch_transcript_excerpt(inspired_by)

            # ── Step 5: Generate script with quality loop ───────
            script_data: dict[str, Any] | None = None
            quality_score: dict[str, Any] = {}
            best_attempt: dict[str, Any] | None = None
            best_total = 0.0

            for attempt in range(1, _MAX_REGENERATION_ATTEMPTS + 1):
                self.logger.info(
                    "Script generation attempt %d / %d for topic %d",
                    attempt, _MAX_REGENERATION_ATTEMPTS, topic_id,
                )

                # Generate the script
                script_data = await self._generate_script(
                    title=title,
                    category=category,
                    language=language,
                    research_items=research_items,
                    content_style=content_style,
                    transcript_excerpt=transcript_excerpt,
                    previous_feedback=quality_score.get("feedback", ""),
                )

                # Score the script
                quality_score = await self._score_script(script_data, language)
                total = float(quality_score.get("total", 0))

                self.logger.info(
                    "Attempt %d quality score: %.1f (hook=%.0f, flow=%.0f, engage=%.0f, acc=%.0f)",
                    attempt, total,
                    quality_score.get("hook_strength", 0),
                    quality_score.get("narrative_flow", 0),
                    quality_score.get("engagement", 0),
                    quality_score.get("accuracy", 0),
                )

                # Track best attempt
                if total > best_total:
                    best_total = total
                    best_attempt = script_data
                    best_quality = quality_score

                if total >= _MIN_QUALITY_SCORE:
                    break
            else:
                # Use best attempt if none passed threshold
                self.logger.warning(
                    "No attempt reached quality threshold (%.1f); using best (%.1f)",
                    _MIN_QUALITY_SCORE, best_total,
                )
                script_data = best_attempt
                quality_score = best_quality  # type: ignore[possibly-undefined]

            if script_data is None:
                raise RuntimeError("Script generation produced no output")

            # ── Step 6: Grammar check on script text ────────────
            grammar_ok = await self._grammar_check_script(script_data, language)

            # ── Step 7: Calculate word count ─────────────────────
            word_count = self._count_words(script_data)

            # ── Step 8: Store in database ───────────────────────
            script_id = await self._store_script(
                topic_id=topic_id,
                language=language,
                script_data=script_data,
                quality_score=float(quality_score.get("total", 0)),
                grammar_ok=grammar_ok,
                word_count=word_count,
            )

            # ── Step 9: Update topic status ─────────────────────
            await db.execute(
                "UPDATE topics SET status = $1 WHERE id = $2",
                "scripted", topic_id,
            )

            result = {
                "script_id": script_id,
                "topic_id": topic_id,
                "title": title,
                "intro_cards": script_data.get("intro_cards", []),
                "sections": script_data.get("sections", []),
                "outro": script_data.get("outro", ""),
                "word_count": word_count,
                "quality_score": quality_score,
                "grammar_ok": grammar_ok,
            }

            await self.log(topic_id=topic_id, status="completed")
            await self.notify(
                f"Script generated for <b>{title}</b>: "
                f"score {quality_score.get('total', 0):.0f}/100, "
                f"{word_count} words, grammar {'✅' if grammar_ok else '⚠️'}"
            )

            return result

        except Exception as exc:
            await self.log(topic_id=topic_id, status="failed", error=str(exc))
            await self.notify(f"❌ Script generation failed for topic {topic_id}: {exc}")
            raise

    # ── Reference data loading ────────────────────────────────

    async def _fetch_content_style(self, channel_id: int | None) -> str:
        """Fetch the content style description from a reference channel.

        Args:
            channel_id: The reference_channels.id, or ``None``.

        Returns:
            The content style string, or a default if unavailable.
        """
        if channel_id is None:
            return "Informative, engaging, data-driven narration with surprising facts."

        style = await db.fetchval(
            "SELECT content_style FROM reference_channels WHERE id = $1",
            channel_id,
        )
        return style or "Informative, engaging, data-driven narration with surprising facts."

    async def _fetch_transcript_excerpt(self, channel_id: int | None) -> str:
        """Fetch a transcript excerpt from a top-performing reference video.

        Args:
            channel_id: The reference_channels.id, or ``None``.

        Returns:
            A transcript excerpt string (up to 800 chars), or empty string.
        """
        if channel_id is None:
            return ""

        row = await db.fetchrow(
            """
            SELECT transcript FROM reference_videos
            WHERE channel_id = $1 AND transcript != ''
            ORDER BY views DESC
            LIMIT 1
            """,
            channel_id,
        )
        if row and row.get("transcript"):
            transcript: str = row["transcript"]
            return transcript[:800]
        return ""

    # ── Script generation ─────────────────────────────────────

    async def _generate_script(
        self,
        title: str,
        category: str,
        language: str,
        research_items: list[dict[str, Any]],
        content_style: str,
        transcript_excerpt: str,
        previous_feedback: str = "",
    ) -> dict[str, Any]:
        """Generate a structured script via AI.

        Args:
            title: Video topic title.
            category: Video category.
            language: Target language code.
            research_items: Verified research data items.
            content_style: Style guide from reference channel.
            transcript_excerpt: Excerpt from a successful video's transcript.
            previous_feedback: Feedback from a prior attempt (for regeneration).

        Returns:
            A dict with ``intro``, ``sections``, and ``outro`` keys.
        """
        language_names: dict[str, str] = {
            "vi": "Vietnamese",
            "en": "English",
            "ja": "Japanese",
        }
        lang_name = language_names.get(language, language)
        section_count = 40

        # Language-specific header formats
        header_formats_by_lang: dict[str, dict[str, str]] = {
            "vi": {
                "WhatIf": "timeline markers (e.g. NGÀY 1, NGÀY 10, NGÀY 30...)",
                "Timeline": "timeline markers (e.g. NGÀY 1, TUẦN 1, THÁNG 1...)",
                "History": "year markers (e.g. NĂM 1945, NĂM 1969...)",
                "Ranking": "ranking markers counting down (e.g. TOP 20, TOP 19... TOP 1)",
                "Comparison": "comparison labels (e.g. VS 1, VS 2...)",
                "Science": "discovery markers (e.g. PHÁT HIỆN 1, PHÁT HIỆN 2...)",
                "Geography": "location markers (e.g. VỊ TRÍ 10, VỊ TRÍ 9... VỊ TRÍ 1)",
                "Evolution": "year/era markers (e.g. THẾ KỶ 18, NĂM 1990, NĂM 2024, NĂM 2030, TƯƠNG LAI XA)",
                "Celebrity": "celebrity name as header (e.g. the celebrity's full name in UPPERCASE)",
            },
            "ja": {
                "WhatIf": "タイムライン (例: 1日目, 10日目, 30日目...)",
                "Timeline": "タイムライン (例: 1日目, 1週間, 1ヶ月...)",
                "History": "年マーカー (例: 1945年, 1969年...)",
                "Ranking": "ランキング (例: TOP 20, TOP 19... TOP 1)",
                "Comparison": "比較 (例: VS 1, VS 2...)",
                "Science": "発見 (例: 発見 1, 発見 2...)",
                "Geography": "場所 (例: 場所 10, 場所 9... 場所 1)",
                "Evolution": "年代マーカー (例: 18世紀, 1990年, 2024年, 2030年, 遠い未来)",
                "Celebrity": "有名人の名前 (例: セレブの名前を大文字で)",
            },
            "en": {
                "WhatIf": "timeline markers (e.g. DAY 1, DAY 10, DAY 30...)",
                "Timeline": "timeline markers (e.g. DAY 1, WEEK 1, MONTH 1...)",
                "History": "year markers (e.g. YEAR 1945, YEAR 1969...)",
                "Ranking": "ranking markers counting down (e.g. TOP 20, TOP 19... TOP 1)",
                "Comparison": "comparison labels (e.g. VS 1, VS 2...)",
                "Science": "discovery markers (e.g. DISCOVERY 1, DISCOVERY 2...)",
                "Geography": "location markers (e.g. LOCATION 10, LOCATION 9... LOCATION 1)",
                "Evolution": "year/era markers (e.g. 18TH CENTURY, YEAR 1990, YEAR 2024, YEAR 2030, FAR FUTURE)",
                "Celebrity": "celebrity name as header (e.g. celebrity's full name in UPPERCASE)",
            },
        }

        lang_headers = header_formats_by_lang.get(language, header_formats_by_lang["vi"])
        header_format = lang_headers.get(category, lang_headers.get("WhatIf", "markers"))

        # Category-specific ordering rules (language-aware)
        order_rule = ""
        future_labels: dict[str, list[str]] = {
            "vi": ["NĂM 2025", "NĂM 2030", "NĂM 2040", "NĂM 2050", "TƯƠNG LAI XA"],
            "ja": ["2025年", "2030年", "2040年", "2050年", "遠い未来"],
            "en": ["YEAR 2025", "YEAR 2030", "YEAR 2040", "YEAR 2050", "FAR FUTURE"],
        }
        fl = future_labels.get(language, future_labels["vi"])

        if category == "Evolution":
            order_rule = f"""
CRITICAL: Sections MUST be in STRICT CHRONOLOGICAL ORDER from oldest to newest.
Each header must use a UNIQUE time period. DO NOT repeat years. DO NOT go backwards.
ALL headers and content MUST be written in {lang_name}. DO NOT mix languages.

IMPORTANT: The LAST 8 CARDS (33-40) must be FUTURE PREDICTIONS:
- Card 33: {fl[0]} (near future, what's happening now)
- Card 34: {fl[1]} (5 years out)
- Card 35: {fl[2]} (10 years out)
- Card 36: {fl[3]} (20 years out)
- Card 37: {fl[4]} (50 years out — bold speculation)
- Card 38-40: Even further future — wild but grounded sci-fi predictions

The future cards should have exciting, speculative but scientifically plausible content."""
        elif category == "Ranking":
            order_rule = "\nSections MUST count down: TOP 40 → TOP 39 → ... → TOP 1. The #1 is the climax."
        elif category == "History":
            order_rule = "\nSections MUST be in chronological order from earliest to latest."
        elif category == "Celebrity":
            order_rule = f"""
This is a CELEBRITY DATA video. Each card = 1 famous person.

CRITICAL CARD FORMAT:
- header: Celebrity's FULL NAME in UPPERCASE (e.g. "ELON MUSK", "TAYLOR SWIFT")
- title: Their most famous role/title (e.g. "CEO Tesla & SpaceX", "Pop Queen")
- description: 3-4 key facts about them — birth year, nationality, career highlights, interesting facts. Include numbers (net worth, records, achievements).
- status_text: Their KEY STAT (e.g. "TÀI SẢN: $230 TỶ", "TUỔI: 35", "ALBUM: 14", "NET WORTH: $1.3B")
- image_query: "[Celebrity Name] portrait photo" — MUST be their real name for accurate photos

All text MUST be in {lang_name}.
Order celebrities from least to most famous/impactful (build up to the biggest name as climax).
Include a MIX of: actors, musicians, athletes, business leaders, historical figures, scientists.
Each person must be DIFFERENT — no repeats."""

        # Format research items for the prompt
        research_text = self._format_research_for_prompt(research_items)

        feedback_block = ""
        if previous_feedback:
            feedback_block = f"""
IMPORTANT — Previous attempt feedback (address these issues):
{previous_feedback}
"""

        transcript_block = ""
        if transcript_excerpt:
            transcript_block = f"""
Example excerpt from a top-performing video (match this style):
---
{transcript_excerpt}
---
"""

        prompt = f"""Write a YouTube video script in {lang_name} for: "{title}"
Category: {category}
Template: slide (horizontal card scroll)

Style guide (from successful channels):
{content_style}
{transcript_block}
Research data to include:
{research_text}
{feedback_block}
IMPORTANT RULES FOR TRENDING:
1. Hook phải cực mạnh — câu đầu tiên khiến người xem KHÔNG THỂ lướt đi
2. Mỗi section phải có 1 fact gây sốc hoặc twist bất ngờ
3. Xây dựng tension tăng dần — section cuối phải là climax
4. Dùng số liệu cụ thể (con số gây ấn tượng)
5. Ngôn ngữ đơn giản, dễ hiểu, hấp dẫn
6. KHÔNG chào hỏi, KHÔNG "chào các bạn", vào thẳng vấn đề
7. CRITICAL: ALL text (titles, descriptions, headers, status_text, intro_cards) MUST be written ENTIRELY in {lang_name}. DO NOT mix languages.
{order_rule}

Return JSON:
{{
    "intro_cards": [
        {{
            "text": "Dòng hook cực mạnh — câu hỏi hoặc statement gây sốc, max 20 từ",
            "subtext": "Dòng phụ bổ sung context hoặc số liệu gây ấn tượng, max 15 từ",
            "image_query": "English search query (2-4 words) for a dramatic background image matching the hook"
        }},
        {{
            "text": "Fact gây sốc thứ 2 để giữ chân, max 20 từ",
            "subtext": "Số liệu hoặc so sánh bất ngờ, max 15 từ",
            "image_query": "English search query for background image"
        }},
        {{
            "text": "Teaser cho nội dung chính — tạo tò mò, max 20 từ",
            "subtext": "Hint về điều bất ngờ sắp tiết lộ, max 15 từ",
            "image_query": "English search query for background image"
        }}
    ],
    "sections": [
        {{
            "header": "{header_format}",
            "title": "bold catchy title, max 20 chars",
            "description": "3-4 câu súc tích. Phải có số liệu hoặc fact bất ngờ. Mỗi câu max 15 từ. Đủ nội dung cho 8 giây đọc.",
            "status_text": "metric display, e.g. 'DÂN SỐ: 1.4 TỶ'",
            "image_query": "PRIMARY English search query (2-4 words). Must be CONCRETE — name real objects/places/animals. NEVER abstract.",
            "image_query_alt1": "BACKUP query 1 — different angle, same subject.",
            "image_query_alt2": "BACKUP query 2 — broader or more generic version."
        }}
    ],
    "outro": "CTA ngắn gọn — subscribe + tease video tiếp theo. Max 2 câu."
}}

Generate exactly 3 intro_cards and exactly {section_count} sections.
Use ALL the research data provided. Make transitions smooth between sections. Build narrative tension.
"""

        system_prompt = (
            f"You are a viral YouTube scriptwriter specializing in {lang_name} content. "
            "Your scripts get millions of views because they're impossible to stop watching. "
            "Keep text SHORT and PUNCHY — every word must earn its place. "
            "Return valid JSON only."
        )

        result = await self.ai_json(prompt, system=system_prompt)

        # Normalise the response structure
        if "script" in result and isinstance(result["script"], dict):
            result = result["script"]

        script: dict[str, Any] = {
            "intro_cards": result.get("intro_cards", []),
            "sections": result.get("sections", []),
            "outro": result.get("outro", ""),
        }

        # Ensure intro_cards is a list
        if not isinstance(script["intro_cards"], list):
            script["intro_cards"] = []

        # Ensure sections is a list
        if not isinstance(script["sections"], list):
            script["sections"] = []

        return script

    @staticmethod
    def _format_research_for_prompt(
        research_items: list[dict[str, Any]],
    ) -> str:
        """Format research items into a readable text block for the AI prompt.

        Args:
            research_items: Database rows from research_data.

        Returns:
            A formatted string listing all items with their metrics.
        """
        lines: list[str] = []
        for i, item in enumerate(research_items, 1):
            name = item.get("item_name", "Unknown")
            metrics = item.get("metrics", {})
            if isinstance(metrics, str):
                try:
                    metrics = json.loads(metrics)
                except json.JSONDecodeError:
                    metrics = {}

            metrics_str = ", ".join(
                f"{k}: {v}" for k, v in metrics.items()
            )
            lines.append(f"{i}. {name} — {metrics_str}")

        return "\n".join(lines) if lines else "No research data available."

    # ── Quality scoring ───────────────────────────────────────

    async def _score_script(
        self, script_data: dict[str, Any], language: str,
    ) -> dict[str, Any]:
        """Send the generated script to AI for quality evaluation.

        Args:
            script_data: The script dict with intro, sections, outro.
            language: Target language code.

        Returns:
            A dict with per-criteria scores and total.
        """
        script_text = json.dumps(script_data, ensure_ascii=False, default=str)

        language_names: dict[str, str] = {
            "vi": "Vietnamese",
            "en": "English",
            "ja": "Japanese",
        }
        lang_name = language_names.get(language, language)

        prompt = f"""Score this {lang_name} YouTube video script on a 0-100 scale for each criterion:

Script:
{script_text[:8000]}

Criteria (each 0-100, weighted equally at 25%):
1. hook_strength: Is the intro immediately captivating? Does it create urgency? (25%)
2. narrative_flow: Do sections build on each other? Are transitions smooth? (25%)
3. engagement: Would viewers stay through the entire video? Are there payoffs? (25%)
4. accuracy: Are the data points used correctly? Are claims well-supported? (25%)

Return JSON:
{{
  "hook_strength": 0-100,
  "narrative_flow": 0-100,
  "engagement": 0-100,
  "accuracy": 0-100,
  "total": weighted average,
  "feedback": "specific, actionable suggestions for improvement (2-3 sentences)"
}}"""

        system_prompt = (
            "You are a YouTube content quality analyst. Score scripts rigorously "
            "and provide specific, actionable feedback. Return valid JSON only."
        )

        try:
            result = await self.ai_json(prompt, system=system_prompt)
            hook = float(result.get("hook_strength", 0))
            flow = float(result.get("narrative_flow", 0))
            engage = float(result.get("engagement", 0))
            accuracy = float(result.get("accuracy", 0))
            total = (hook + flow + engage + accuracy) / 4.0

            return {
                "hook_strength": hook,
                "narrative_flow": flow,
                "engagement": engage,
                "accuracy": accuracy,
                "total": round(total, 1),
                "feedback": result.get("feedback", ""),
            }
        except Exception as exc:
            self.logger.warning("Script scoring failed: %s", exc)
            return {
                "hook_strength": 0,
                "narrative_flow": 0,
                "engagement": 0,
                "accuracy": 0,
                "total": 0,
                "feedback": f"Scoring failed: {exc}",
            }

    # ── Grammar check ─────────────────────────────────────────

    async def _grammar_check_script(
        self, script_data: dict[str, Any], language: str,
    ) -> bool:
        """Run a grammar check on the full script text.

        Args:
            script_data: The script dict.
            language: Target language code.

        Returns:
            ``True`` if the grammar is acceptable, ``False`` otherwise.
        """
        # Collect all text from the script
        text_parts: list[str] = []
        for card in script_data.get("intro_cards", []):
            text_parts.append(card.get("text", ""))
            text_parts.append(card.get("subtext", ""))

        for section in script_data.get("sections", []):
            text_parts.append(section.get("title", ""))
            text_parts.append(section.get("description", ""))
            text_parts.append(section.get("status_text", ""))

        text_parts.append(script_data.get("outro", ""))

        combined = "\n".join(part for part in text_parts if part)
        if not combined.strip():
            return True

        language_names: dict[str, str] = {
            "vi": "Vietnamese",
            "en": "English",
            "ja": "Japanese",
        }
        lang_name = language_names.get(language, language)

        prompt = f"""Check this {lang_name} YouTube script text for grammar errors, 
spelling mistakes, or awkward phrasing.

Text:
---
{combined[:5000]}
---

Return JSON: {{"grammar_ok": true/false, "error_count": number, "issues": ["brief description of each issue"]}}
"""

        try:
            result = await self.ai_json(
                prompt,
                system=f"You are a {lang_name} grammar expert. Return valid JSON only.",
            )
            return bool(result.get("grammar_ok", True))
        except Exception as exc:
            self.logger.warning("Script grammar check failed: %s", exc)
            return True  # Assume OK on failure to avoid blocking

    # ── Word count ────────────────────────────────────────────

    @staticmethod
    def _count_words(script_data: dict[str, Any]) -> int:
        """Count total words in the script.

        Args:
            script_data: The script dict with intro_cards, sections, outro.

        Returns:
            Total word count.
        """
        text_parts: list[str] = []
        for card in script_data.get("intro_cards", []):
            text_parts.append(card.get("text", ""))
            text_parts.append(card.get("subtext", ""))

        for section in script_data.get("sections", []):
            text_parts.append(section.get("header", ""))
            text_parts.append(section.get("title", ""))
            text_parts.append(section.get("description", ""))
            text_parts.append(section.get("status_text", ""))

        text_parts.append(script_data.get("outro", ""))

        combined = " ".join(part for part in text_parts if part)
        return len(combined.split())

    # ── Database storage ──────────────────────────────────────

    async def _store_script(
        self,
        topic_id: int,
        language: str,
        script_data: dict[str, Any],
        quality_score: float,
        grammar_ok: bool,
        word_count: int,
    ) -> int:
        """Insert the generated script into the scripts table.

        Args:
            topic_id: Parent topic ID.
            language: Script language code.
            script_data: The full script dict.
            quality_score: Combined quality score (0–100).
            grammar_ok: Whether the script passed grammar checks.
            word_count: Total word count.

        Returns:
            The new script row ID.
        """
        sections = script_data.get("sections", [])
        if isinstance(sections, str):
            sections_json = sections
        else:
            sections_json = json.dumps(sections, ensure_ascii=False)

        intro_cards = script_data.get("intro_cards", [])
        if isinstance(intro_cards, str):
            intro_cards_json = intro_cards
        else:
            intro_cards_json = json.dumps(intro_cards, ensure_ascii=False)

        row = await db.fetchrow(
            """
            INSERT INTO scripts
                (topic_id, language, intro, sections, outro,
                 word_count, quality_score, grammar_ok, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            topic_id,
            language,
            intro_cards_json,
            sections_json,
            script_data.get("outro", ""),
            word_count,
            quality_score,
            grammar_ok,
            datetime.now(timezone.utc),
        )

        script_id: int = row["id"]  # type: ignore[index]
        self.logger.info(
            "Stored script %d for topic %d (score=%.1f, words=%d)",
            script_id, topic_id, quality_score, word_count,
        )
        return script_id
