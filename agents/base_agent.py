"""Abstract base class for all pipeline agents."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from core import ai_client, database as db
from core.notifier import notify
from core.storage import get_asset_path

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Common interface and utilities shared by every pipeline agent.

    Subclasses must implement :meth:`run`.

    Usage::

        class MyAgent(BaseAgent):
            def __init__(self):
                super().__init__(name="my_agent")

            async def run(self, **kwargs) -> dict:
                result = await self.ai("Generate something creative")
                return {"output": result}
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.logger = logging.getLogger(f"agent.{name}")

    # ── Abstract entry point ──────────────────────────────────

    @abstractmethod
    async def run(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the agent's main logic.

        Args:
            **kwargs: Agent-specific parameters (e.g. ``topic_id``).

        Returns:
            A dict summarising the result of the run.
        """

    # ── AI helpers ────────────────────────────────────────────

    async def ai(self, prompt: str, system: str | None = None, **kwargs: Any) -> str:
        """Call the unified AI client and return plain text.

        Args:
            prompt: User-role message.
            system: Optional system-role message.
            **kwargs: Forwarded to :func:`ai_client.generate`.

        Returns:
            The model's reply string.
        """
        return await ai_client.generate(
            prompt=prompt,
            system=system,
            agent_name=self.name,
            **kwargs,
        )

    async def ai_json(self, prompt: str, system: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Call the unified AI client and return parsed JSON.

        Args:
            prompt: User-role message.
            system: Optional system-role message.
            **kwargs: Forwarded to :func:`ai_client.generate_json`.

        Returns:
            Parsed dict from the model's JSON response.
        """
        return await ai_client.generate_json(
            prompt=prompt,
            system=system,
            agent_name=self.name,
            **kwargs,
        )

    # ── Asset persistence ─────────────────────────────────────

    async def save_asset(
        self,
        topic_id: int,
        asset_type: str,
        file_path: str,
        source_url: str = "",
        license_type: str = "unknown",
        **metadata: Any,
    ) -> int:
        """Register an asset in the database and return its ID.

        Args:
            topic_id: Parent topic ID.
            asset_type: Asset category (``image``, ``audio``, ``video``, etc.).
            file_path: Path to the file on disk (relative or absolute).
            source_url: Original source URL.
            license_type: License string (e.g. ``CC0``, ``royalty-free``).
            **metadata: Additional metadata stored as JSONB.

        Returns:
            The auto-generated asset row ID.
        """
        row = await db.fetchrow(
            """
            INSERT INTO assets (topic_id, asset_type, file_path, source_url, license, metadata, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            topic_id,
            asset_type,
            file_path,
            source_url,
            license_type,
            json.dumps(metadata),
            datetime.now(timezone.utc),
        )
        asset_id: int = row["id"]  # type: ignore[index]
        self.logger.info("Saved asset %d (type=%s) for topic %d", asset_id, asset_type, topic_id)
        return asset_id

    # ── Pipeline logging ──────────────────────────────────────

    async def log(
        self,
        topic_id: int | None,
        status: str,
        error: str | None = None,
    ) -> None:
        """Write a pipeline log entry.

        Args:
            topic_id: Related topic ID (can be ``None``).
            status: Current status (``running``, ``completed``, ``failed``).
            error: Optional error message.
        """
        now = datetime.now(timezone.utc)
        completed_at = now if status in ("completed", "failed") else None

        await db.execute(
            """
            INSERT INTO pipeline_logs
                (topic_id, agent_name, status, error_message, started_at, completed_at, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            topic_id,
            self.name,
            status,
            error,
            now,
            completed_at,
            now,
        )
        self.logger.info(
            "Pipeline log: topic=%s agent=%s status=%s",
            topic_id, self.name, status,
        )

    # ── Notifications ─────────────────────────────────────────

    async def notify(self, message: str) -> None:
        """Send a Telegram notification prefixed with the agent name.

        Args:
            message: Notification body (HTML).
        """
        formatted = f"🤖 <b>[{self.name}]</b> {message}"
        await notify(formatted)
