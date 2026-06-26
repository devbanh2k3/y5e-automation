"""Video rendering agent — builds Remotion projects and mixes audio."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from core import database as db
from core.config import get_settings
from core.storage import get_asset_path, get_topic_dir

logger = logging.getLogger(__name__)

# Maps topic categories to Remotion composition/template names
TEMPLATE_MAP: dict[str, str] = {
    "WhatIf": "TimelineVideo",
    "Timeline": "TimelineVideo",
    "History": "TimelineVideo",
    "Ranking": "RankingVideo",
    "Comparison": "ComparisonVideo",
    "Science": "TimelineVideo",
    "Geography": "RankingVideo",
    "Evolution": "TimelineVideo",
    "Celebrity": "TimelineVideo",
}

_DEFAULT_TEMPLATE = "TimelineVideo"

# Template key used in video_data.json (lowercase of the composition name)
_TEMPLATE_KEY_MAP: dict[str, str] = {
    "TimelineVideo": "timeline",
    "RankingVideo": "ranking",
    "ComparisonVideo": "comparison",
}

# Remotion render timeout (10 minutes)
_RENDER_TIMEOUT_SEC = 600

# FFmpeg timeout (5 minutes)
_FFMPEG_TIMEOUT_SEC = 300


def build_video_result(
    *,
    video_id: int,
    file_path: str,
    duration_sec: int,
    resolution: str,
) -> dict[str, Any]:
    """Return the stable video result contract used by the pipeline."""
    return {
        "id": video_id,
        "video_id": video_id,
        "file_path": file_path,
        "duration_sec": duration_sec,
        "resolution": resolution,
    }


class VideoAgent(BaseAgent):
    """Renders a full video using Remotion and mixes background music via FFmpeg.

    Pipeline:
    1. Gather all assets (images, music, SFX) from the DB.
    2. Build a ``video_data.json`` matching the Remotion ``VideoData`` TS type.
    3. Copy assets into ``video_engine/public/``.
    4. Run ``npx remotion render`` to produce the raw video.
    5. Mix background music via FFmpeg.
    6. Probe final duration with ffprobe.
    7. Store the result in the ``videos`` table.
    """

    def __init__(self) -> None:
        super().__init__(name="video_agent")
        self._settings = get_settings()
        self._project_root = Path(__file__).resolve().parent.parent
        self._video_engine_dir = self._project_root / "video_engine"

    # ── Public entry point ────────────────────────────────────

    async def run(self, topic_id: int) -> dict[str, Any]:  # type: ignore[override]
        """Render a video for the given topic and mix audio.

        Args:
            topic_id: Topic to render.

        Returns:
            Dict with ``file_path``, ``duration_sec``, and ``resolution``.
        """
        await self.log(topic_id, "running")

        try:
            # 1. Load all required data
            topic = await self._fetch_topic(topic_id)
            if topic is None:
                raise ValueError(f"Topic {topic_id} not found")

            script = await self._fetch_script(topic_id)
            if script is None:
                raise ValueError(f"No script found for topic {topic_id}")

            assets = await self._fetch_assets(topic_id)

            # 2. Determine template
            category: str = topic.get("category", "")
            template_name = TEMPLATE_MAP.get(category, _DEFAULT_TEMPLATE)
            template_key = _TEMPLATE_KEY_MAP.get(template_name, "timeline")

            # 3. Parse sections
            sections_raw = script["sections"]
            sections: list[dict[str, Any]] = (
                json.loads(sections_raw)
                if isinstance(sections_raw, str)
                else sections_raw
            )

            # 3b. Parse intro cards (hook)
            intro_cards_raw = script.get("intro_cards", [])
            intro_cards: list[dict[str, Any]] = (
                json.loads(intro_cards_raw)
                if isinstance(intro_cards_raw, str)
                else intro_cards_raw
            )

            # 4. Categorise assets
            image_assets = [a for a in assets if a["asset_type"] == "image"]
            music_assets = [a for a in assets if a["asset_type"] == "music"]
            sfx_assets = [a for a in assets if a["asset_type"] == "sfx"]

            # 5. Prepare public directory
            public_dir = self._video_engine_dir / "public"
            images_pub = public_dir / "images"
            audio_pub = public_dir / "audio"
            images_pub.mkdir(parents=True, exist_ok=True)
            audio_pub.mkdir(parents=True, exist_ok=True)

            # 6. Copy image assets
            image_map = self._copy_images(image_assets, images_pub)

            # 7. Copy audio assets
            music_pub_path = self._copy_music(music_assets, audio_pub)
            sfx_pub_paths = self._copy_sfx(sfx_assets, audio_pub)

            # 8. Copy logo if available
            logo_src = self._project_root / "assets" / "branding" / "logo.png"
            logo_pub = images_pub / "logo.png"
            if logo_src.is_file():
                shutil.copy2(str(logo_src), str(logo_pub))

            # 9. Build video_data.json
            cards = self._build_cards(sections, image_map)

            # 9b. Build intro cards data
            intro_cards_data = []
            for idx, ic in enumerate(intro_cards):
                intro_cards_data.append({
                    "text": ic.get("text", ""),
                    "subtext": ic.get("subtext", ""),
                    "imagePath": f"images/intro_{idx}.webp",
                })

            video_data = self._build_video_data(
                template_key=template_key,
                topic=topic,
                script=script,
                cards=cards,
                intro_cards=intro_cards_data,
                music_pub="audio/bgm.mp3" if music_pub_path else "",
                sfx_pub=sfx_pub_paths,
                has_logo=logo_pub.is_file(),
            )

            data_file = public_dir / "video_data.json"
            data_file.write_text(json.dumps(video_data, ensure_ascii=False, indent=2))
            self.logger.info("Wrote video_data.json (%d cards)", len(cards))

            # 10. Render with Remotion
            topic_dir = get_topic_dir(topic_id)
            raw_output = topic_dir / "raw_video.mp4"
            await self._run_remotion(template_name, raw_output, data_file)

            # 11. Mix audio
            final_output = topic_dir / "final_video.mp4"
            if music_pub_path and music_pub_path.is_file():
                await self._mix_audio(raw_output, music_pub_path, final_output)
            else:
                # No music to mix — use raw video as final
                shutil.copy2(str(raw_output), str(final_output))

            # 12. Probe duration
            duration_sec = await self._probe_duration(final_output)

            # 13. Store in videos table
            resolution = "1920x1080"
            video_row = await db.fetchrow(
                """
                INSERT INTO videos (topic_id, file_path, resolution, duration_sec, fps, codec, status, created_at)
                VALUES ($1, $2, $3, $4, 30, 'h264', 'rendered', NOW())
                RETURNING id
                """,
                topic_id,
                str(final_output),
                resolution,
                duration_sec,
            )
            video_id: int = video_row["id"]  # type: ignore[index]

            await self.log(topic_id, "completed")
            await self.notify(
                f"🎬 Video rendered for topic <b>{topic_id}</b> — "
                f"{duration_sec}s, video_id={video_id}"
            )

            return build_video_result(
                video_id=video_id,
                file_path=str(final_output),
                duration_sec=duration_sec,
                resolution=resolution,
            )

        except Exception as exc:
            await self.log(topic_id, "failed", error=str(exc))
            raise

    # ── Asset copying helpers ─────────────────────────────────

    @staticmethod
    def _copy_images(
        image_assets: list[dict[str, Any]], dest_dir: Path
    ) -> dict[int, str]:
        """Copy image assets into the Remotion public/images/ directory.

        Args:
            image_assets: Image asset rows from the DB.
            dest_dir: Target images directory.

        Returns:
            A mapping from section_index → relative image path.
        """
        image_map: dict[int, str] = {}

        for asset in image_assets:
            src = Path(asset["file_path"])
            if not src.is_file():
                logger.warning("Image file missing: %s", src)
                continue

            metadata = asset.get("metadata", {})
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            section_idx: int = metadata.get("section_index", 0)

            dest_name = f"section_{section_idx}.webp"
            dest = dest_dir / dest_name
            shutil.copy2(str(src), str(dest))
            image_map[section_idx] = f"images/{dest_name}"

        return image_map

    @staticmethod
    def _copy_music(
        music_assets: list[dict[str, Any]], dest_dir: Path
    ) -> Path | None:
        """Copy the first music asset to public/audio/.

        Args:
            music_assets: Music asset rows from the DB.
            dest_dir: Target audio directory.

        Returns:
            Path to the copied file, or ``None``.
        """
        if not music_assets:
            return None

        src = Path(music_assets[0]["file_path"])
        if not src.is_file():
            logger.warning("Music file missing: %s", src)
            return None

        dest = dest_dir / "bgm.mp3"
        shutil.copy2(str(src), str(dest))
        return dest

    @staticmethod
    def _copy_sfx(
        sfx_assets: list[dict[str, Any]], dest_dir: Path
    ) -> dict[str, str]:
        """Copy SFX assets to public/audio/ and build a role → path map.

        Args:
            sfx_assets: SFX asset rows from the DB.
            dest_dir: Target audio directory.

        Returns:
            A mapping from role → relative path (e.g. ``audio/whoosh.mp3``).
        """
        sfx_map: dict[str, str] = {}

        for asset in sfx_assets:
            src = Path(asset["file_path"])
            if not src.is_file():
                continue

            metadata = asset.get("metadata", {})
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            role: str = metadata.get("role", src.stem)

            dest = dest_dir / src.name
            shutil.copy2(str(src), str(dest))
            sfx_map[role] = f"audio/{src.name}"

        return sfx_map

    # ── Video data builder ────────────────────────────────────

    @staticmethod
    def _build_cards(
        sections: list[dict[str, Any]],
        image_map: dict[int, str],
    ) -> list[dict[str, str]]:
        """Build the ``cards`` array for video_data.json.

        Args:
            sections: Parsed script sections.
            image_map: section_index → relative image path.

        Returns:
            A list of card dicts for the Remotion composition.
        """
        cards: list[dict[str, str]] = []

        for idx, section in enumerate(sections):
            card: dict[str, str] = {
                "header": section.get("header", section.get("title", f"Section {idx + 1}")),
                "title": section.get("title", section.get("header", "")),
                "description": section.get("narration", section.get("description", "")),
                "imagePath": image_map.get(idx, ""),
                "statusText": section.get("status_text", section.get("label", f"#{idx + 1}")),
            }
            cards.append(card)

        return cards

    @staticmethod
    def _build_video_data(
        template_key: str,
        topic: dict[str, Any],
        script: dict[str, Any],
        cards: list[dict[str, str]],
        intro_cards: list[dict[str, str]] | None = None,
        music_pub: str = "",
        sfx_pub: dict[str, str] | None = None,
        has_logo: bool = False,
    ) -> dict[str, Any]:
        """Assemble the full ``video_data.json`` structure."""
        if sfx_pub is None:
            sfx_pub = {}
        title: str = topic.get("title", "Untitled")
        language: str = topic.get("language", "vi")
        intro: str = script.get("intro", "")
        subtitle = intro[:120].rstrip(".") if intro else ""

        return {
            "template": template_key,
            "title": title,
            "subtitle": subtitle,
            "language": language,
            "cards": cards,
            "introCards": intro_cards or [],
            "musicPath": music_pub,
            "sfxPaths": {
                "transition": sfx_pub.get("transition", ""),
                "alert": sfx_pub.get("alert", ""),
                "reveal": sfx_pub.get("reveal", ""),
            },
            "logoPath": "images/logo.png" if has_logo else "",
            "holdDurationFrames": 240,
            "transitionDurationFrames": 15,
        }

    # ── Remotion render ───────────────────────────────────────

    async def _run_remotion(
        self, template_name: str, output_path: Path, data_file: Path
    ) -> None:
        """Execute the Remotion CLI to render the video.

        Args:
            template_name: Remotion composition ID.
            output_path: Where to write the rendered MP4.
            data_file: Path to video_data.json.

        Raises:
            RuntimeError: If the render exits with a non-zero code.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        props_json = json.dumps({"dataFile": "video_data.json"})

        cmd = [
            "npx",
            "remotion",
            "render",
            "src/index.tsx",
            template_name,
            str(output_path),
            f"--props={props_json}",
            "--codec=h264",
            "--crf=20",
        ]

        self.logger.info("Remotion render: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self._video_engine_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=_RENDER_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(
                f"Remotion render timed out after {_RENDER_TIMEOUT_SEC}s"
            )

        if process.returncode != 0:
            stderr_text = stderr.decode(errors="replace")[:2000]
            raise RuntimeError(
                f"Remotion render failed (exit {process.returncode}): {stderr_text}"
            )

        self.logger.info("Remotion render completed → %s", output_path)

    # ── Audio mixing ──────────────────────────────────────────

    async def _mix_audio(
        self, video_path: Path, music_path: Path, output_path: Path
    ) -> None:
        """Mix background music into the video at a low volume.

        Uses FFmpeg's ``volume`` and ``afade`` filters.  The video stream
        is copied without re-encoding.

        Args:
            video_path: Input video (from Remotion).
            music_path: Background music file.
            output_path: Where to write the final MP4.

        Raises:
            RuntimeError: If FFmpeg exits non-zero.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-i", str(music_path),
            "-filter_complex",
            "[1:a]volume=0.15,afade=t=in:st=0:d=2[bg]",
            "-map", "0:v",
            "-map", "[bg]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(output_path),
        ]

        self.logger.info("FFmpeg audio mix: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=_FFMPEG_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(
                f"FFmpeg audio mix timed out after {_FFMPEG_TIMEOUT_SEC}s"
            )

        if process.returncode != 0:
            stderr_text = stderr.decode(errors="replace")[:2000]
            raise RuntimeError(
                f"FFmpeg mix failed (exit {process.returncode}): {stderr_text}"
            )

        self.logger.info("Audio mix completed → %s", output_path)

    # ── FFprobe duration ──────────────────────────────────────

    async def _probe_duration(self, video_path: Path) -> int:
        """Get video duration in seconds using ffprobe.

        Args:
            video_path: Path to the video file.

        Returns:
            Duration rounded to the nearest whole second.
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(video_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=30
        )

        if process.returncode != 0:
            self.logger.warning(
                "ffprobe failed (exit %d) — defaulting duration to 0",
                process.returncode,
            )
            return 0

        try:
            probe_data = json.loads(stdout.decode())
            duration_str: str = probe_data.get("format", {}).get("duration", "0")
            return round(float(duration_str))
        except (json.JSONDecodeError, ValueError, TypeError):
            self.logger.warning("Could not parse ffprobe output — defaulting to 0")
            return 0

    # ── DB helpers ────────────────────────────────────────────

    @staticmethod
    async def _fetch_topic(topic_id: int) -> dict[str, Any] | None:
        """Load a topic row."""
        return await db.fetchrow(
            "SELECT id, title, category, language, status FROM topics WHERE id = $1",
            topic_id,
        )

    @staticmethod
    async def _fetch_script(topic_id: int) -> dict[str, Any] | None:
        """Load the latest script for a topic."""
        return await db.fetchrow(
            """
            SELECT id, topic_id, language, intro, sections, outro, word_count
            FROM scripts
            WHERE topic_id = $1
            ORDER BY id DESC
            LIMIT 1
            """,
            topic_id,
        )

    @staticmethod
    async def _fetch_assets(topic_id: int) -> list[dict[str, Any]]:
        """Load all assets for a topic."""
        return await db.fetch(
            "SELECT id, asset_type, file_path, source_url, license, metadata FROM assets WHERE topic_id = $1",
            topic_id,
        )
