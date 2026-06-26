"""Research agent — gathers factual or hypothetical data for video topics."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from agents.base_agent import BaseAgent
from core import database as db

logger = logging.getLogger(__name__)

# Categories that require factual (Wikidata/Wikipedia) research
_FACTUAL_CATEGORIES: frozenset[str] = frozenset({
    "History", "Ranking", "Geography", "Science", "Evolution", "Comparison",
    "Celebrity",
})

# Categories that use AI-inferred hypothetical scenarios
_HYPOTHETICAL_CATEGORIES: frozenset[str] = frozenset({
    "WhatIf", "Timeline",
})

_WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
_WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"


class ResearchAgent(BaseAgent):
    """Gather structured research data for a video topic.

    Supports two research modes:
    - **Factual**: queries Wikidata SPARQL + Wikipedia summaries for data-driven
      categories (History, Ranking, Geography, Science, Evolution, Comparison).
    - **Hypothetical**: uses AI to generate scientifically-plausible scenarios
      for speculative categories (WhatIf, Timeline).
    """

    def __init__(self) -> None:
        super().__init__(name="research_agent")

    async def run(self, topic_id: int) -> list[dict[str, Any]]:
        """Research a topic and store structured data items.

        Args:
            topic_id: The database ID of the topic to research.

        Returns:
            A list of research item dicts stored in ``research_data``.

        Raises:
            ValueError: If the topic does not exist.
        """
        await self.log(topic_id=topic_id, status="running")

        try:
            # ── Step 1: Load the topic ──────────────────────────
            topic = await db.fetchrow(
                "SELECT id, title, category, language FROM topics WHERE id = $1",
                topic_id,
            )
            if not topic:
                raise ValueError(f"Topic {topic_id} not found in database")

            title: str = topic["title"]
            category: str = topic["category"]
            language: str = topic["language"]

            self.logger.info(
                "Researching topic %d: '%s' (category=%s, mode=%s)",
                topic_id, title, category,
                "factual" if category in _FACTUAL_CATEGORIES else "hypothetical",
            )

            # ── Step 2: Dispatch to appropriate mode ────────────
            if category in _FACTUAL_CATEGORIES:
                items = await self._research_factual(topic_id, title, language)
            elif category in _HYPOTHETICAL_CATEGORIES:
                items = await self._research_hypothetical(topic_id, title, language)
            else:
                # Default to factual with AI fallback
                items = await self._research_factual(topic_id, title, language)
                if not items:
                    items = await self._research_hypothetical(topic_id, title, language)

            self.logger.info("Collected %d research items for topic %d", len(items), topic_id)

            # ── Step 3: Store items in database ─────────────────
            stored_items = await self._store_items(topic_id, items)

            # ── Step 4: Update topic status ─────────────────────
            await db.execute(
                "UPDATE topics SET status = $1 WHERE id = $2",
                "researched", topic_id,
            )

            await self.log(topic_id=topic_id, status="completed")
            await self.notify(
                f"Research complete for topic <b>{title}</b>: "
                f"{len(stored_items)} items collected"
            )

            return stored_items

        except Exception as exc:
            await self.log(topic_id=topic_id, status="failed", error=str(exc))
            await self.notify(f"❌ Research failed for topic {topic_id}: {exc}")
            raise

    # ── Factual research (Wikidata + Wikipedia) ───────────────

    async def _research_factual(
        self, topic_id: int, title: str, language: str,
    ) -> list[dict[str, Any]]:
        """Perform factual research using Wikidata SPARQL and Wikipedia.

        Args:
            topic_id: Topic database ID.
            title: Topic title string.
            language: Target language code.

        Returns:
            A list of research item dicts.
        """
        # Generate SPARQL query via AI
        sparql_query = await self._generate_sparql(title)
        self.logger.info("Generated SPARQL query (%d chars)", len(sparql_query))

        # Execute SPARQL query
        sparql_results = await self._execute_sparql(sparql_query)
        self.logger.info("SPARQL returned %d results", len(sparql_results))

        # Process results into research items
        items: list[dict[str, Any]] = []
        for row in sparql_results[:30]:  # Cap at 30 items to avoid overloading
            item = self._parse_sparql_row(row)
            if not item or not item.get("item_name"):
                continue

            # Fetch Wikipedia summary for each item
            wiki_summary = await self._fetch_wikipedia_summary(item["item_name"])
            if wiki_summary:
                item["description"] = wiki_summary.get("extract", item.get("description", ""))
                item["sources"].append({
                    "type": "wikipedia",
                    "url": wiki_summary.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    "title": wiki_summary.get("title", ""),
                })

            # Generate image query via AI
            image_query = await self._generate_image_query(item["item_name"], title)
            item["image_query"] = image_query

            items.append(item)

        # If SPARQL returned too few results, supplement with AI
        if len(items) < 5:
            self.logger.info(
                "SPARQL yielded only %d items; supplementing with AI", len(items)
            )
            ai_items = await self._ai_supplement_factual(title, language, items)
            items.extend(ai_items)

        return items

    async def _generate_sparql(self, topic_title: str) -> str:
        """Generate a Wikidata SPARQL query using AI.

        Args:
            topic_title: The topic title to research.

        Returns:
            A SPARQL query string.
        """
        prompt = f"""Write a Wikidata SPARQL query to find data about: {topic_title}

Requirements:
- Query must be valid SPARQL for https://query.wikidata.org/sparql
- Include ?itemLabel for item names
- Include relevant numeric properties (population, area, GDP, year, etc.)
- Use SERVICE wikibase:label for automatic labels
- LIMIT 30 results
- ORDER BY a relevant metric (DESC if ranking is useful)

Return ONLY the SPARQL query, no explanation."""

        raw = await self.ai(prompt, system="You are a SPARQL expert. Return only valid SPARQL code.")

        # Strip code fences if present
        query = raw.strip()
        if query.startswith("```"):
            lines = query.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            query = "\n".join(lines).strip()

        return query

    async def _execute_sparql(self, query: str) -> list[dict[str, Any]]:
        """Execute a SPARQL query against Wikidata.

        Args:
            query: The SPARQL query string.

        Returns:
            A list of result binding dicts.
        """
        headers = {
            "Accept": "application/sparql-results+json",
            "User-Agent": "YouTubeAIAutomation/1.0 (research agent)",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    _WIKIDATA_SPARQL_URL,
                    params={"query": query, "format": "json"},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            bindings = data.get("results", {}).get("bindings", [])
            return bindings

        except httpx.HTTPStatusError as exc:
            self.logger.warning(
                "Wikidata SPARQL query failed (HTTP %d): %s",
                exc.response.status_code, exc.response.text[:200],
            )
            return []
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            self.logger.warning("Wikidata SPARQL request error: %s", exc)
            return []

    @staticmethod
    def _parse_sparql_row(row: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a SPARQL result binding into a structured research item.

        Args:
            row: A single SPARQL result binding dict.

        Returns:
            A research item dict, or ``None`` if the row is unusable.
        """
        item_label = row.get("itemLabel", {}).get("value", "")
        if not item_label:
            return None

        # Extract all numeric and text values as metrics
        metrics: dict[str, Any] = {}
        sources: list[dict[str, Any]] = [{"type": "wikidata", "url": "", "title": "Wikidata"}]

        for key, binding in row.items():
            if key in ("item", "itemLabel"):
                continue
            value = binding.get("value", "")
            datatype = binding.get("datatype", "")

            if "integer" in datatype or "decimal" in datatype or "double" in datatype:
                try:
                    metrics[key] = float(value)
                except (ValueError, TypeError):
                    metrics[key] = value
            else:
                metrics[key] = value

            # Extract Wikidata entity URL
            if key == "item":
                sources[0]["url"] = value

        return {
            "item_name": item_label,
            "metrics": metrics,
            "description": "",
            "sources": sources,
            "image_query": "",
        }

    async def _fetch_wikipedia_summary(
        self, title: str,
    ) -> dict[str, Any] | None:
        """Fetch the Wikipedia REST summary for a given article title.

        Args:
            title: The Wikipedia article title (can contain spaces).

        Returns:
            The summary response dict, or ``None`` on failure.
        """
        encoded_title = quote_plus(title.replace(" ", "_"))
        url = f"{_WIKIPEDIA_SUMMARY_URL}/{encoded_title}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "YouTubeAIAutomation/1.0"},
                )
                if resp.status_code == 404:
                    self.logger.debug("Wikipedia article not found: %s", title)
                    return None
                resp.raise_for_status()
                return resp.json()

        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
            self.logger.debug("Wikipedia summary fetch failed for '%s': %s", title, exc)
            return None

    async def _generate_image_query(self, item_name: str, topic_title: str) -> str:
        """Generate an English image search query for a research item.

        Args:
            item_name: The name of the specific item.
            topic_title: The overall topic title for context.

        Returns:
            A concise English search query string.
        """
        prompt = (
            f"Generate a single, concise English image search query (max 8 words) "
            f"to find a real, high-quality photo of '{item_name}' "
            f"in the context of '{topic_title}'. "
            f"Return ONLY the search query text, nothing else."
        )
        query = await self.ai(prompt, system="Return only the search query.")
        return query.strip().strip('"').strip("'")

    async def _ai_supplement_factual(
        self, title: str, language: str, existing_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Use AI to generate additional factual research items when SPARQL yields few results.

        Args:
            title: Topic title.
            language: Target language.
            existing_items: Items already collected (to avoid duplication).

        Returns:
            A list of supplementary research item dicts.
        """
        existing_names = [i["item_name"] for i in existing_items]
        needed = max(5, 10 - len(existing_items))

        prompt = f"""Generate {needed} factual data items for the YouTube video topic: "{title}"

Already collected items (do NOT repeat these): {json.dumps(existing_names, ensure_ascii=False)}

For each item, provide:
- item_name: the name of the entity/thing
- metrics: a dict of relevant numeric data (e.g. population, area, year, speed, etc.)
- description: 2-3 sentences of factual information
- sources: [{{type: "ai_knowledge", url: "", title: "AI Knowledge Base"}}]
- image_query: an English search query to find a real photo (max 8 words)

All facts must be verifiable and accurate. Return a JSON array."""

        result = await self.ai_json(
            prompt,
            system="You are a research assistant. Provide accurate, verifiable facts with real numbers.",
        )

        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("items", "data", "results"):
                if key in result and isinstance(result[key], list):
                    return result[key]
        return []

    # ── Hypothetical research (AI-inferred) ───────────────────

    async def _research_hypothetical(
        self, topic_id: int, title: str, language: str,
    ) -> list[dict[str, Any]]:
        """Generate hypothetical timeline/scenarios via AI.

        Args:
            topic_id: Topic database ID.
            title: Topic title string.
            language: Target language code.

        Returns:
            A list of research item dicts based on AI speculation.
        """
        prompt = f"""Create a detailed hypothetical timeline for: {title}

Base all reasoning on real scientific knowledge. For each milestone, provide:
- item_name: a concise name for this milestone/event (in English)
- metrics: {{time_point: "Day X / Year Y / etc.", severity: 1-10, probability: "X%", key_numbers: "specific data"}}
- description: 2-3 sentences explaining what happens and why, based on real science
- scientific_basis: a brief explanation of the real science behind this prediction
- sources: [{{type: "scientific_inference", url: "", title: "Scientific Reasoning"}}]
- image_query: an English search query for finding a real photo that represents this scenario (max 8 words)

Generate 10-15 milestones in chronological order. Make each milestone increasingly dramatic
but scientifically plausible. Include specific numbers and data points.

Return a JSON array of milestone objects."""

        system_prompt = (
            "You are a science communicator creating hypothetical scenarios. "
            "Your speculation must be grounded in real physics, biology, chemistry, "
            "and other sciences. Include specific numbers. Return valid JSON only."
        )

        result = await self.ai_json(prompt, system=system_prompt)

        items: list[dict[str, Any]] = []
        raw_items: list[dict[str, Any]] = []

        if isinstance(result, list):
            raw_items = result
        elif isinstance(result, dict):
            for key in ("milestones", "timeline", "items", "data", "results"):
                if key in result and isinstance(result[key], list):
                    raw_items = result[key]
                    break

        for item in raw_items:
            # Normalise to our standard schema
            normalised: dict[str, Any] = {
                "item_name": item.get("item_name", item.get("name", "")),
                "metrics": item.get("metrics", {}),
                "description": item.get("description", ""),
                "sources": item.get("sources", [
                    {"type": "scientific_inference", "url": "", "title": "Scientific Reasoning"}
                ]),
                "image_query": item.get("image_query", ""),
            }

            # Merge scientific_basis into description if provided separately
            basis = item.get("scientific_basis", "")
            if basis and basis not in normalised["description"]:
                normalised["description"] = f"{normalised['description']} ({basis})"

            if normalised["item_name"]:
                items.append(normalised)

        return items

    # ── Database storage ──────────────────────────────────────

    async def _store_items(
        self, topic_id: int, items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Insert research items into the research_data table.

        Args:
            topic_id: The parent topic's database ID.
            items: Processed research item dicts.

        Returns:
            The items list, enriched with database IDs.
        """
        stored: list[dict[str, Any]] = []

        for item in items:
            item_name = item.get("item_name", "")
            if not item_name:
                continue

            metrics = item.get("metrics", {})
            if isinstance(metrics, str):
                metrics = json.loads(metrics)

            sources = item.get("sources", [])
            if isinstance(sources, str):
                sources = json.loads(sources)

            row = await db.fetchrow(
                """
                INSERT INTO research_data
                    (topic_id, item_name, metrics, sources, verified, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                topic_id,
                item_name,
                json.dumps(metrics, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                False,
                datetime.now(timezone.utc),
            )

            item["id"] = row["id"]  # type: ignore[index]
            stored.append(item)

        self.logger.info(
            "Stored %d research items for topic %d", len(stored), topic_id
        )
        return stored
