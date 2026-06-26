"""Shorts generation agent — cuts engaging clips from rendered videos."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from agents.base_agent import BaseAgent
from core import database as db
from core.storage import get_asset_path

logger = logging.getLogger(__name__)

# FFmpeg timeout (3 minutes per short)
_FFMPEG_TIMEOUT_SEC = 180

# Hard limits for short duration
_MIN_SHORT_SEC = 15
_MAX_SHORT_SEC = 60


class ShortsAgent(BaseAgent):
    """Generates YouTube Shorts by extracting the most engaging segments.

    Uses AI to identify high-engagement moments in the script, then
    cuts vertical (9:16) clips from the rendered video using FFmpeg.
    """

    def __init__(self) -> None:
        super().__init__(name="shorts_agent")

    # ── Public entry point ────────────────────────────────────

    async def run(self, video_id: int, count: int = 3) -> list[dict[str, Any]]:  # type: ignore[override]
        """Generate YouTube Shorts from an existing video.

        Args:
            video_id: The rendered video row ID.
            count: Number of shorts to generate (default 3).

        Returns:
            A list of dicts with ``file_path``, ``duration``, and ``hook_text``.
        """
        # Fetch video record
        video = await self._fetch_video(video_id)
        if video is None:
            raise ValueError(f"Video {video_id} not found")

        topic_id: int = video["topic_id"]
        video_path = Path(video["file_path"])
        video_duration: int = video.get("duration_sec", 0)

        if not video_path.is_file():
            raise FileNotFoundError(f"Video file missing: {video_path}")

        await self.log(topic_id, "running")

        try:
            # Fetch the script for AI analysis
            script = await self._fetch_script(topic_id)
            if script is None:
                raise ValueError(f"No script found for topic {topic_id}")

            sections_raw = script["sections"]
            sections: list[dict[str, Any]] = (
                json.loads(sections_raw)
                if isinstance(sections_raw, str)
                else sections_raw
            )

            # Use AI to select the best segments
            selections = await self._select_segments(
                sections=sections,
                video_duration=video_duration,
                count=count,
            )

            # Cut each segment
            results: list[dict[str, Any]] = []
            for idx, sel in enumerate(selections):
                start_sec: float = sel["start_sec"]
                end_sec: float = sel["end_sec"]
                hook_text: str = sel.get("hook_text", "")

                # Clamp to valid range
                start_sec = max(0.0, start_sec)
                if video_duration > 0:
                    end_sec = min(float(video_duration), end_sec)

                duration = end_sec - start_sec
                if duration < _MIN_SHORT_SEC:
                    # Extend to minimum
                    end_sec = start_sec + _MIN_SHORT_SEC
                if duration > _MAX_SHORT_SEC:
                    end_sec = start_sec + _MAX_SHORT_SEC

                # Output path
                output_path = get_asset_path(topic_id, f"shorts/short_{idx}.mp4")
                await self._cut_short(video_path, start_sec, end_sec, output_path)

                actual_duration = round(end_sec - start_sec)

                # Store in shorts table
                await db.execute(
                    """
                    INSERT INTO shorts (video_id, file_path, start_sec, end_sec, status, created_at)
                    VALUES ($1, $2, $3, $4, 'ready', NOW())
                    """,
                    video_id,
                    str(output_path),
                    round(start_sec),
                    round(end_sec),
                )

                # Also track as an asset
                await self.save_asset(
                    topic_id=topic_id,
                    asset_type="short",
                    file_path=str(output_path),
                    license_type="original",
                    short_index=idx,
                    hook_text=hook_text,
                    start_sec=start_sec,
                    end_sec=end_sec,
                )

                results.append({
                    "file_path": str(output_path),
                    "duration": actual_duration,
                    "hook_text": hook_text,
                })

                self.logger.info(
                    "Short %d: %.1fs–%.1fs (%ds) — %s",
                    idx,
                    start_sec,
                    end_sec,
                    actual_duration,
                    hook_text[:60],
                )

            await self.log(topic_id, "completed")
            await self.notify(
                f"📱 {len(results)} Shorts ready for video <b>{video_id}</b>"
            )
            return results

        except Exception as exc:
            await self.log(topic_id, "failed", error=str(exc))
            raise

    # ── AI segment selection ──────────────────────────────────

    async def _select_segments(
        self,
        sections: list[dict[str, Any]],
        video_duration: int,
        count: int,
    ) -> list[dict[str, Any]]:
        """Use AI to pick the most engaging video segments for Shorts.

        Args:
            sections: Parsed script sections.
            video_duration: Total video duration in seconds.
            count: Number of segments to select.

        Returns:
            A list of dicts with ``section_index``, ``hook_text``,
            ``start_sec``, and ``end_sec``.
        """
        # Build a summary of sections with estimated timing
        section_count = len(sections)
        avg_section_dur = video_duration / max(section_count, 1)

        section_summaries: list[str] = []
        for idx, section in enumerate(sections):
            est_start = round(idx * avg_section_dur)
            est_end = round((idx + 1) * avg_section_dur)
            title = section.get("title", section.get("header", f"Section {idx + 1}"))
            narration = section.get("narration", section.get("description", ""))
            preview = narration[:200] if narration else ""
            section_summaries.append(
                f"[{idx}] \"{title}\" (~{est_start}s–{est_end}s): {preview}"
            )

        sections_text = "\n".join(section_summaries)

        prompt = f"""You are a YouTube Shorts strategist. Given these video sections, select the {count} most engaging segments for YouTube Shorts (each 30–60 seconds).

Each short should have:
- A strong hook that grabs attention in the first 2 seconds
- Standalone value — viewers should understand it without watching the full video
- High emotional impact or surprising information

Video sections:
{sections_text}

Total video duration: {video_duration} seconds

Return ONLY a JSON array. Each element must have:
- "section_index": int (0-based index of the source section)
- "hook_text": str (compelling hook text for the short, max 15 words)
- "start_sec": float (start timestamp in the video)
- "end_sec": float (end timestamp, ensuring 30–60 second duration)

Return exactly {count} segments. Ensure no overlaps.
"""

        try:
            result = await self.ai_json(
                prompt=prompt,
                system="You are a YouTube content strategist. Return valid JSON only.",
            )

            # Handle both direct array and wrapped object responses
            if isinstance(result, list):
                segments = result
            elif isinstance(result, dict):
                # Try common wrapper keys
                for key in ("segments", "shorts", "selections", "results"):
                    if key in result and isinstance(result[key], list):
                        segments = result[key]
                        break
                else:
                    # If the dict itself looks like a single segment, wrap it
                    if "section_index" in result:
                        segments = [result]
                    else:
                        segments = list(result.values())[0] if result else []
            else:
                segments = []

            # Validate and sanitise each segment
            validated: list[dict[str, Any]] = []
            for seg in segments[:count]:
                validated.append({
                    "section_index": int(seg.get("section_index", 0)),
                    "hook_text": str(seg.get("hook_text", "Watch this!")),
                    "start_sec": float(seg.get("start_sec", 0)),
                    "end_sec": float(seg.get("end_sec", 45)),
                })

            return validated

        except Exception:
            self.logger.exception("AI segment selection failed — using fallback")
            return self._fallback_segments(sections, video_duration, count)

    @staticmethod
    def _fallback_segments(
        sections: list[dict[str, Any]],
        video_duration: int,
        count: int,
    ) -> list[dict[str, Any]]:
        """Generate evenly-spaced fallback segments when AI fails.

        Args:
            sections: Script sections.
            video_duration: Total video length in seconds.
            count: Number of segments.

        Returns:
            A list of segment dicts.
        """
        segment_len = 45  # Target 45 seconds per short
        section_count = len(sections)
        avg_dur = video_duration / max(section_count, 1)

        # Pick evenly-spaced sections
        step = max(section_count // max(count, 1), 1)
        selected_indices = [
            min(i * step, section_count - 1) for i in range(count)
        ]

        results: list[dict[str, Any]] = []
        for idx in selected_indices:
            start = round(idx * avg_dur)
            end = min(start + segment_len, video_duration)
            title = sections[idx].get("title", sections[idx].get("header", ""))
            results.append({
                "section_index": idx,
                "hook_text": title[:60] if title else f"Section {idx + 1}",
                "start_sec": float(start),
                "end_sec": float(end),
            })

        return results

    # ── FFmpeg cutting ────────────────────────────────────────

    async def _cut_short(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
        output_path: Path,
    ) -> None:
        """Extract and crop a vertical segment from the video.

        The output is cropped to 9:16 (1080×1920) for YouTube Shorts.

        Args:
            video_path: Source video.
            start_sec: Start time.
            end_sec: End time.
            output_path: Destination file.

        Raises:
            RuntimeError: If FFmpeg exits non-zero.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-ss", f"{start_sec:.2f}",
            "-to", f"{end_sec:.2f}",
            "-vf", "crop=ih*9/16:ih,scale=1080:1920",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        self.logger.info("Cutting short: %.1f–%.1f → %s", start_sec, end_sec, output_path.name)

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
                f"FFmpeg short cut timed out after {_FFMPEG_TIMEOUT_SEC}s"
            )

        if process.returncode != 0:
            stderr_text = stderr.decode(errors="replace")[:2000]
            raise RuntimeError(
                f"FFmpeg short cut failed (exit {process.returncode}): {stderr_text}"
            )

    # ── DB helpers ────────────────────────────────────────────

    @staticmethod
    async def _fetch_video(video_id: int) -> dict[str, Any] | None:
        """Load a video row."""
        return await db.fetchrow(
            """
            SELECT id, topic_id, file_path, duration_sec, resolution, status
            FROM videos
            WHERE id = $1
            """,
            video_id,
        )

    @staticmethod
    async def _fetch_script(topic_id: int) -> dict[str, Any] | None:
        """Load the latest script for a topic."""
        return await db.fetchrow(
            """
            SELECT id, topic_id, intro, sections, outro, word_count
            FROM scripts
            WHERE topic_id = $1
            ORDER BY id DESC
            LIMIT 1
            """,
            topic_id,
        )
