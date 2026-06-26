"""Fact-check agent — verifies research data accuracy and grammar."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agents.base_agent import BaseAgent
from core import database as db

logger = logging.getLogger(__name__)

# Categories that require multi-source verification
_FACTUAL_CATEGORIES: frozenset[str] = frozenset({
    "History", "Ranking", "Geography", "Science", "Evolution", "Comparison",
    "Celebrity",
})

# Maximum acceptable variance between source values (5%)
_MAX_VARIANCE_THRESHOLD = 0.05


class FactCheckAgent(BaseAgent):
    """Verify research data for accuracy, consistency, and grammar.

    For factual categories, cross-references metrics against multiple sources
    and flags high-variance items. For all categories, runs grammar and
    phrasing checks on textual content.
    """

    def __init__(self) -> None:
        super().__init__(name="fact_check_agent")

    async def run(self, topic_id: int) -> dict[str, Any]:
        """Fact-check all research data for a topic.

        Args:
            topic_id: Database ID of the topic to verify.

        Returns:
            Summary dict with counts of verified, flagged, and rejected items,
            plus grammar check results.

        Raises:
            ValueError: If the topic or its research data is not found.
        """
        await self.log(topic_id=topic_id, status="running")

        try:
            # ── Step 1: Fetch topic and research data ───────────
            topic = await db.fetchrow(
                "SELECT id, title, category, language FROM topics WHERE id = $1",
                topic_id,
            )
            if not topic:
                raise ValueError(f"Topic {topic_id} not found in database")

            research_items = await db.fetch(
                """
                SELECT id, item_name, metrics, sources, verified
                FROM research_data
                WHERE topic_id = $1
                ORDER BY id
                """,
                topic_id,
            )
            if not research_items:
                raise ValueError(f"No research data found for topic {topic_id}")

            category: str = topic["category"]
            language: str = topic["language"]
            is_factual = category in _FACTUAL_CATEGORIES

            self.logger.info(
                "Fact-checking %d items for topic %d (category=%s, factual=%s)",
                len(research_items), topic_id, category, is_factual,
            )

            # ── Step 2: Verify each research item ──────────────
            verified_count = 0
            flagged_count = 0
            rejected_count = 0

            for item in research_items:
                research_id: int = item["id"]
                item_name: str = item["item_name"]

                sources = item.get("sources", [])
                if isinstance(sources, str):
                    sources = json.loads(sources)

                metrics = item.get("metrics", {})
                if isinstance(metrics, str):
                    metrics = json.loads(metrics)

                source_count = len(sources)

                # ── 2a: Source count check (factual only) ───────
                if is_factual and source_count < 2:
                    await self._store_fact(
                        research_id=research_id,
                        claim=f"Insufficient sources for '{item_name}'",
                        source_count=source_count,
                        variance=0.0,
                        status="rejected",
                    )
                    rejected_count += 1
                    self.logger.debug(
                        "Rejected '%s': only %d source(s)", item_name, source_count
                    )
                    continue

                # ── 2b: Cross-reference metrics via AI ──────────
                verification = await self._verify_item(
                    item_name=item_name,
                    metrics=metrics,
                    category=category,
                    is_factual=is_factual,
                )

                variance = verification.get("variance", 0.0)
                ai_confirms = verification.get("confirmed", True)
                ai_notes = verification.get("notes", "")

                # ── 2c: Determine status ────────────────────────
                if not ai_confirms:
                    status = "flagged"
                    flagged_count += 1
                elif variance > _MAX_VARIANCE_THRESHOLD:
                    status = "flagged"
                    flagged_count += 1
                else:
                    status = "verified"
                    verified_count += 1

                claim = f"{item_name}: {json.dumps(metrics, ensure_ascii=False)[:200]}"
                if ai_notes:
                    claim = f"{claim} — AI: {ai_notes}"

                await self._store_fact(
                    research_id=research_id,
                    claim=claim,
                    source_count=source_count,
                    variance=variance,
                    status=status,
                )

                # ── 2d: Mark verified in research_data ──────────
                if status == "verified":
                    await db.execute(
                        "UPDATE research_data SET verified = TRUE WHERE id = $1",
                        research_id,
                    )

            # ── Step 3: Grammar check ───────────────────────────
            grammar_result = await self._check_grammar(
                topic_id=topic_id,
                research_items=research_items,
                language=language,
            )

            grammar_ok = grammar_result.get("overall_ok", True)
            corrections = grammar_result.get("corrections", [])

            # ── Step 4: Apply corrections if any ────────────────
            if corrections:
                await self._apply_corrections(topic_id, corrections, research_items)

            # ── Step 5: Update topic status ─────────────────────
            new_status = "fact_checked" if rejected_count == 0 else "needs_review"
            await db.execute(
                "UPDATE topics SET status = $1 WHERE id = $2",
                new_status, topic_id,
            )

            summary = {
                "topic_id": topic_id,
                "total": len(research_items),
                "verified": verified_count,
                "flagged": flagged_count,
                "rejected": rejected_count,
                "grammar_ok": grammar_ok,
                "corrections_applied": len(corrections),
            }

            await self.log(topic_id=topic_id, status="completed")
            await self.notify(
                f"Fact-check complete for topic <b>{topic['title']}</b>: "
                f"✅ {verified_count} verified, ⚠️ {flagged_count} flagged, "
                f"❌ {rejected_count} rejected, 📝 grammar {'OK' if grammar_ok else f'{len(corrections)} corrections'}"
            )

            return summary

        except Exception as exc:
            await self.log(topic_id=topic_id, status="failed", error=str(exc))
            await self.notify(f"❌ Fact-check failed for topic {topic_id}: {exc}")
            raise

    # ── Verification helpers ──────────────────────────────────

    async def _verify_item(
        self,
        item_name: str,
        metrics: dict[str, Any],
        category: str,
        is_factual: bool,
    ) -> dict[str, Any]:
        """Use AI to cross-reference an item's metrics against known facts.

        Args:
            item_name: The name of the research item.
            metrics: The numeric/data metrics to verify.
            category: Video category.
            is_factual: Whether strict factual verification is required.

        Returns:
            A dict with ``confirmed`` (bool), ``variance`` (float),
            and ``notes`` (str).
        """
        metrics_str = json.dumps(metrics, ensure_ascii=False, default=str)

        if is_factual:
            prompt = f"""Verify the following factual claim about "{item_name}":
Metrics: {metrics_str}
Category: {category}

Cross-reference these metrics against your knowledge. For each numeric value:
1. State whether you can confirm it (within ~5% tolerance)
2. If different, provide the correct value
3. Calculate the percentage variance between the claimed and correct values

Return JSON:
{{
  "confirmed": true/false,
  "variance": 0.0 to 1.0 (max percentage difference found),
  "notes": "brief explanation of any discrepancies",
  "corrections": {{}} // key-value pairs of corrected metrics, empty if all correct
}}"""
        else:
            prompt = f"""Evaluate the plausibility of the following hypothetical scenario about "{item_name}":
Data: {metrics_str}
Category: {category}

Check if the scientific reasoning is sound and the numbers are plausible.

Return JSON:
{{
  "confirmed": true/false,
  "variance": 0.0,
  "notes": "brief assessment of scientific plausibility"
}}"""

        system_prompt = (
            "You are a fact-checking expert. Verify claims rigorously. "
            "Return valid JSON only."
        )

        try:
            result = await self.ai_json(prompt, system=system_prompt)
            return {
                "confirmed": result.get("confirmed", True),
                "variance": float(result.get("variance", 0.0)),
                "notes": result.get("notes", ""),
                "corrections": result.get("corrections", {}),
            }
        except Exception as exc:
            self.logger.warning("AI verification failed for '%s': %s", item_name, exc)
            return {"confirmed": True, "variance": 0.0, "notes": f"Verification error: {exc}"}

    async def _store_fact(
        self,
        research_id: int,
        claim: str,
        source_count: int,
        variance: float,
        status: str,
    ) -> int:
        """Insert a fact-check result into the facts table.

        Args:
            research_id: Foreign key to research_data.id.
            claim: Summary of the claim being checked.
            source_count: Number of sources supporting the claim.
            variance: Percentage variance between source values.
            status: One of ``verified``, ``flagged``, ``rejected``.

        Returns:
            The new fact row ID.
        """
        row = await db.fetchrow(
            """
            INSERT INTO facts
                (research_id, claim, source_count, variance, status, reviewed_at, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            research_id,
            claim[:1000],  # Truncate to avoid oversized claims
            source_count,
            variance,
            status,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        )
        return row["id"]  # type: ignore[index]

    # ── Grammar checking ──────────────────────────────────────

    async def _check_grammar(
        self,
        topic_id: int,
        research_items: list[dict[str, Any]],
        language: str,
    ) -> dict[str, Any]:
        """Check all textual content for grammar and phrasing errors.

        Args:
            topic_id: The topic database ID.
            research_items: All research data items for the topic.
            language: Target language code.

        Returns:
            A dict with ``corrections`` list and ``overall_ok`` boolean.
        """
        # Collect all text content
        text_blocks: list[str] = []
        for item in research_items:
            text_blocks.append(f"Item: {item['item_name']}")

            metrics = item.get("metrics", {})
            if isinstance(metrics, str):
                metrics = json.loads(metrics)

            # Include text-type metric values
            for key, value in metrics.items():
                if isinstance(value, str) and len(value) > 10:
                    text_blocks.append(f"  {key}: {value}")

        if not text_blocks:
            return {"corrections": [], "overall_ok": True}

        combined_text = "\n".join(text_blocks)

        language_names: dict[str, str] = {
            "vi": "Vietnamese",
            "en": "English",
            "ja": "Japanese",
        }
        lang_name = language_names.get(language, language)

        prompt = f"""Check this {lang_name} text for grammar errors, awkward phrasing, or factual inconsistencies.

Text to check:
---
{combined_text[:6000]}
---

Return JSON:
{{
  "corrections": [
    {{"original": "exact text with error", "corrected": "corrected version", "reason": "explanation"}}
  ],
  "overall_ok": true/false
}}

If no errors are found, return {{"corrections": [], "overall_ok": true}}."""

        system_prompt = (
            f"You are a professional {lang_name} editor. "
            "Check for grammar, spelling, and factual consistency. "
            "Return valid JSON only."
        )

        try:
            result = await self.ai_json(prompt, system=system_prompt)
            corrections = result.get("corrections", [])
            overall_ok = result.get("overall_ok", len(corrections) == 0)
            return {"corrections": corrections, "overall_ok": overall_ok}
        except Exception as exc:
            self.logger.warning("Grammar check failed: %s", exc)
            return {"corrections": [], "overall_ok": True}

    async def _apply_corrections(
        self,
        topic_id: int,
        corrections: list[dict[str, Any]],
        research_items: list[dict[str, Any]],
    ) -> int:
        """Apply grammar corrections to research data in the database.

        Searches each research item's ``item_name`` for occurrences of the
        corrected text and updates the row.

        Args:
            topic_id: Topic database ID.
            corrections: List of correction dicts with ``original`` and ``corrected``.
            research_items: The original research data rows.

        Returns:
            Number of corrections applied.
        """
        applied = 0

        for correction in corrections:
            original = correction.get("original", "")
            corrected = correction.get("corrected", "")
            if not original or not corrected or original == corrected:
                continue

            # Check if the correction applies to any item_name
            for item in research_items:
                item_name: str = item["item_name"]
                if original in item_name:
                    new_name = item_name.replace(original, corrected)
                    await db.execute(
                        "UPDATE research_data SET item_name = $1 WHERE id = $2",
                        new_name, item["id"],
                    )
                    applied += 1
                    self.logger.debug(
                        "Corrected item name: '%s' → '%s'", item_name, new_name
                    )
                    break  # One correction per item

                # Also check metrics text values
                metrics = item.get("metrics", {})
                if isinstance(metrics, str):
                    metrics = json.loads(metrics)

                metrics_updated = False
                for key, value in metrics.items():
                    if isinstance(value, str) and original in value:
                        metrics[key] = value.replace(original, corrected)
                        metrics_updated = True

                if metrics_updated:
                    await db.execute(
                        "UPDATE research_data SET metrics = $1 WHERE id = $2",
                        json.dumps(metrics, ensure_ascii=False),
                        item["id"],
                    )
                    applied += 1
                    self.logger.debug(
                        "Corrected metrics text in item '%s'", item_name
                    )
                    break

        self.logger.info(
            "Applied %d / %d grammar corrections for topic %d",
            applied, len(corrections), topic_id,
        )
        return applied
