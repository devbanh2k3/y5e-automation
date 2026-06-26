"""Music and SFX sourcing agent — selects mood-matched background music."""

from __future__ import annotations

import logging
import random
import shutil
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from core import database as db
from core.config import get_settings
from core.storage import get_asset_path

logger = logging.getLogger(__name__)

# Maps topic categories to music moods.  Each mood corresponds to a
# subdirectory under ``assets/music/``.
MOOD_MAP: dict[str, str] = {
    "WhatIf": "dramatic",
    "Timeline": "dramatic",
    "History": "epic",
    "Ranking": "upbeat",
    "Comparison": "ambient",
    "Science": "curious",
    "Geography": "ambient",
    "Evolution": "curious",
}

# Default mood when the category is not in the map
_DEFAULT_MOOD = "ambient"

# Required SFX files and their logical roles
_SFX_FILES: dict[str, str] = {
    "transition": "whoosh.mp3",
    "alert": "alert.mp3",
    "reveal": "reveal.mp3",
    "dramatic_hit": "dramatic_hit.mp3",
}

# Supported audio extensions for music tracks
_AUDIO_EXTENSIONS: set[str] = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}


class MusicAgent(BaseAgent):
    """Selects mood-appropriate background music and copies SFX assets.

    Music tracks are chosen randomly from ``assets/music/<mood>/``.
    SFX files are copied from ``assets/sfx/`` into the topic directory.
    """

    def __init__(self) -> None:
        super().__init__(name="music_agent")
        self._settings = get_settings()

    # ── Public entry point ────────────────────────────────────

    async def run(self, topic_id: int) -> dict[str, Any]:  # type: ignore[override]
        """Select background music and copy SFX for a topic.

        Args:
            topic_id: The topic to prepare audio assets for.

        Returns:
            A dict with ``music_path`` and ``sfx_paths`` mapping.
        """
        await self.log(topic_id, "running")

        try:
            # 1. Determine mood from topic category
            topic = await self._fetch_topic(topic_id)
            if topic is None:
                raise ValueError(f"Topic {topic_id} not found")

            category: str = topic.get("category", "")
            mood = MOOD_MAP.get(category, _DEFAULT_MOOD)
            self.logger.info(
                "Topic %d category='%s' → mood='%s'", topic_id, category, mood
            )

            # 2. Find and copy a music track
            music_path = await self._select_music(topic_id, mood)

            # 3. Copy SFX files
            sfx_paths = await self._copy_sfx(topic_id)

            # 4. Persist asset records
            await self.save_asset(
                topic_id=topic_id,
                asset_type="music",
                file_path=str(music_path),
                license_type="royalty-free",
                mood=mood,
                category=category,
            )

            for role, sfx_path in sfx_paths.items():
                await self.save_asset(
                    topic_id=topic_id,
                    asset_type="sfx",
                    file_path=str(sfx_path),
                    license_type="royalty-free",
                    role=role,
                )

            await self.log(topic_id, "completed")
            await self.notify(
                f"🎵 Audio ready for topic <b>{topic_id}</b> "
                f"(mood: {mood}, sfx: {len(sfx_paths)} files)"
            )

            return {
                "music_path": str(music_path),
                "sfx_paths": {
                    role: str(path) for role, path in sfx_paths.items()
                },
            }

        except Exception as exc:
            await self.log(topic_id, "failed", error=str(exc))
            raise

    # ── Music selection ───────────────────────────────────────

    async def _select_music(self, topic_id: int, mood: str) -> Path:
        """Pick a random track from the mood folder and copy it to the topic dir.

        Args:
            topic_id: Target topic ID.
            mood: The mood key (e.g. ``dramatic``, ``epic``).

        Returns:
            Path to the copied music file.

        Raises:
            FileNotFoundError: If no tracks are available for the mood.
        """
        project_root = Path(__file__).resolve().parent.parent
        mood_dir = project_root / "assets" / "music" / mood

        if not mood_dir.is_dir():
            # Fall back to default mood
            mood_dir = project_root / "assets" / "music" / _DEFAULT_MOOD
            self.logger.warning(
                "Mood dir for '%s' not found — falling back to '%s'",
                mood,
                _DEFAULT_MOOD,
            )

        tracks = [
            f
            for f in mood_dir.iterdir()
            if f.is_file() and f.suffix.lower() in _AUDIO_EXTENSIONS
        ] if mood_dir.is_dir() else []

        if not tracks:
            # Last resort: scan all mood directories
            tracks = self._find_any_track(project_root / "assets" / "music")

        if not tracks:
            raise FileNotFoundError(
                f"No music tracks found for mood '{mood}' or any fallback"
            )

        selected = random.choice(tracks)
        self.logger.info("Selected track: %s", selected.name)

        dest = get_asset_path(topic_id, f"audio/bgm{selected.suffix}")
        shutil.copy2(str(selected), str(dest))
        return dest

    @staticmethod
    def _find_any_track(music_root: Path) -> list[Path]:
        """Recursively find any audio file under the music root.

        Args:
            music_root: The ``assets/music/`` directory.

        Returns:
            A list of audio file paths (may be empty).
        """
        if not music_root.is_dir():
            return []
        return [
            f
            for f in music_root.rglob("*")
            if f.is_file() and f.suffix.lower() in _AUDIO_EXTENSIONS
        ]

    # ── SFX copying ───────────────────────────────────────────

    async def _copy_sfx(self, topic_id: int) -> dict[str, Path]:
        """Copy required SFX files to the topic audio directory.

        Missing SFX files are logged as warnings but do not cause failure.

        Args:
            topic_id: Target topic ID.

        Returns:
            A dict mapping logical role to the copied file path.
        """
        project_root = Path(__file__).resolve().parent.parent
        sfx_dir = project_root / "assets" / "sfx"

        copied: dict[str, Path] = {}

        for role, filename in _SFX_FILES.items():
            src = sfx_dir / filename
            if not src.is_file():
                self.logger.warning(
                    "SFX file missing: %s (role=%s) — skipping", src, role
                )
                continue

            dest = get_asset_path(topic_id, f"audio/{filename}")
            shutil.copy2(str(src), str(dest))
            copied[role] = dest
            self.logger.debug("Copied SFX %s → %s", filename, dest)

        return copied

    # ── DB helpers ────────────────────────────────────────────

    @staticmethod
    async def _fetch_topic(topic_id: int) -> dict[str, Any] | None:
        """Load a topic row from the database.

        Args:
            topic_id: The topic ID to fetch.

        Returns:
            A dict of column values, or ``None`` if not found.
        """
        return await db.fetchrow(
            "SELECT id, title, category, language, status FROM topics WHERE id = $1",
            topic_id,
        )
