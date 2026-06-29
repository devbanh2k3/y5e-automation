"""Pipeline orchestrator — runs the full video creation pipeline end-to-end.

Coordinates all agents in sequence: topic generation → research → fact-check
→ script → images + music (parallel) → video render → shorts → thumbnail
→ upload.  Each step is wrapped in error handling with logging and Telegram
notifications.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from agents.ai_fact_verification_agent import AIFactVerificationAgent
from agents.metadata_optimizer_agent import MetadataOptimizerAgent
from agents.real_image_agent import RealImageAgent
from core import database as db
from core.config import get_settings
from core.fact_verification import apply_fact_corrections
from core.fact_verification import align_fact_verification_to_content_contract
from core.notifier import notify, notify_error
from core.quality_gate import run_production_quality_gate
from core.reviews import create_review
from core.video_contract import (
    apply_verified_images_to_video_data,
    build_local_render_video_data,
    build_video_data_from_content_contract,
    validate_video_data,
)
from services.thumbnail_collage import build_review_thumbnail

logger = logging.getLogger(__name__)

_LOCAL_RENDER_TIMEOUT_SEC = 600


class PipelineError(Exception):
    """Raised when a pipeline step fails in a way that aborts the run."""


class Pipeline:
    """Orchestrates the full video creation pipeline.

    Each step instantiates the responsible agent, runs it, validates
    the output, and proceeds to the next step.  If a step fails the
    error is logged, a Telegram notification is sent, and the pipeline
    raises :class:`PipelineError`.

    Usage::

        pipeline = Pipeline()
        result = await pipeline.run_full(category="science", language="vi")
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger("pipeline")

    # ── Full pipeline ────────────────────────────────────────

    async def run_full(
        self,
        category: str,
        language: str = "vi",
    ) -> dict[str, Any]:
        """Run the complete video pipeline from topic to YouTube upload.

        Args:
            category: Content category (e.g. ``"science"``, ``"history"``).
            language: Target language code (default ``"vi"`` for Vietnamese).

        Returns:
            A dict summarising the pipeline run with keys:
            ``topic``, ``video``, ``upload_result``, ``shorts``.

        Raises:
            PipelineError: If any step fails fatally.
        """
        started_at = datetime.now(timezone.utc)
        await notify(
            f"🚀 <b>Pipeline started</b>\n"
            f"Category: <b>{category}</b>\n"
            f"Language: <b>{language}</b>"
        )

        topic: dict[str, Any] | None = None
        topic_id: int | None = None
        video: dict[str, Any] | None = None
        video_id: int | None = None
        upload_result: dict[str, Any] | None = None
        shorts_results: list[dict[str, Any]] = []

        try:
            # ── Step 1: Generate topic ───────────────────────
            topic = await self._step(
                step_name="Topic Generation",
                topic_id=None,
                coro=self._run_topic_agent(category, language),
            )
            topic_id = topic["id"]

            # ── Step 2: Research ─────────────────────────────
            await self._step(
                step_name="Research",
                topic_id=topic_id,
                coro=self._run_research_agent(topic_id),
            )

            # ── Step 3: Fact-check ───────────────────────────
            fact_result = await self._step(
                step_name="Fact Check",
                topic_id=topic_id,
                coro=self._run_fact_check_agent(topic_id),
            )
            rejected = fact_result.get("rejected", 0)
            total = fact_result.get("total", 1)
            if total > 0 and rejected > total * 0.5:
                raise PipelineError(
                    f"Too many facts rejected ({rejected}/{total}). "
                    f"Topic may be unreliable."
                )

            # ── Step 4: Script ───────────────────────────────
            await self._step(
                step_name="Script Writing",
                topic_id=topic_id,
                coro=self._run_script_agent(topic_id),
            )

            # ── Step 5 & 6: Images + Music (parallel) ───────
            image_task = asyncio.create_task(
                self._step(
                    step_name="Image Generation",
                    topic_id=topic_id,
                    coro=self._run_image_agent(topic_id),
                )
            )
            music_task = asyncio.create_task(
                self._step(
                    step_name="Music Selection",
                    topic_id=topic_id,
                    coro=self._run_music_agent(topic_id),
                )
            )

            images, music = await asyncio.gather(image_task, music_task)

            # ── Step 7: Render video ─────────────────────────
            video = await self._step(
                step_name="Video Render",
                topic_id=topic_id,
                coro=self._run_video_agent(topic_id),
            )
            video_id = video["id"]

            # ── Step 7b: Generate shorts ─────────────────────
            shorts_results = await self._step(
                step_name="Shorts Generation",
                topic_id=topic_id,
                coro=self._run_shorts_agent(video_id),
            )

            # ── Step 8: Thumbnail ────────────────────────────
            await self._step(
                step_name="Thumbnail",
                topic_id=topic_id,
                coro=self._run_thumbnail_agent(topic_id),
            )

            # ── Step 9: Upload main video ────────────────────
            upload_result = await self._step(
                step_name="Upload",
                topic_id=topic_id,
                coro=self._run_upload_agent(video_id),
            )

            # ── Step 10: Upload shorts ───────────────────────
            for idx, short in enumerate(shorts_results):
                short_id = short.get("id")
                if short_id:
                    try:
                        short_upload = await self._run_upload_short(short_id)
                        self.logger.info(
                            "Short %d/%d uploaded: %s",
                            idx + 1, len(shorts_results),
                            short_upload.get("youtube_id", "unknown"),
                        )
                    except Exception as exc:
                        self.logger.warning(
                            "Short %d upload failed (non-fatal): %s",
                            short_id, exc,
                        )

            # ── Complete ─────────────────────────────────────
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            url = upload_result.get("url", "N/A") if upload_result else "N/A"
            await notify(
                f"✅ <b>Pipeline complete!</b>\n"
                f"🎬 {upload_result.get('title', 'Video') if upload_result else 'Video'}\n"
                f"🔗 {url}\n"
                f"⏱ {elapsed:.0f}s elapsed"
            )

            return {
                "topic": topic,
                "video": video,
                "upload_result": upload_result,
                "shorts": shorts_results,
                "elapsed_seconds": elapsed,
            }

        except PipelineError:
            raise
        except Exception as exc:
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            await notify(
                f"❌ <b>Pipeline failed</b> after {elapsed:.0f}s\n"
                f"Error: <code>{str(exc)[:300]}</code>"
            )
            raise PipelineError(f"Pipeline failed: {exc}") from exc

    async def run_smoke(
        self,
        *,
        category: str,
        language: str = "vi",
        mode: str = "smoke",
    ) -> dict[str, Any]:
        """Return a no-side-effect pipeline summary for deployment validation."""
        reason = f"{mode} mode"
        steps = [
            "topic",
            "research",
            "fact_check",
            "script",
            "assets",
            "render",
            "thumbnail",
            "upload",
        ]
        return {
            "mode": mode,
            "category": category,
            "language": language,
            "steps": [
                {"name": step, "status": "skipped", "reason": reason}
                for step in steps
            ],
            "side_effects": {
                "ai_calls": False,
                "render": False,
                "upload": False,
            },
        }

    async def run_local_render(
        self,
        *,
        category: str,
        language: str = "vi",
        card_layout: str = "flag_hero",
        selected_topic: dict[str, Any] | None = None,
        duration_target: int = 60,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Create a local render artifact using explicit fallback content."""
        resolved_category = category.strip() or "Local"
        content_contract: dict[str, Any] | None = None
        fact_verification_contract: dict[str, Any] | None = None
        image_verification_contract: dict[str, Any] | None = None
        production_summary: dict[str, Any] = {}
        fallback_used = True
        topic_id = self._new_local_render_topic_id()
        pipeline_started = time.monotonic()
        stage_timings: dict[str, dict[str, float]] = {}

        def record_stage(stage_name: str, started_at: float) -> None:
            stage_timings[stage_name] = {
                "seconds": round(time.monotonic() - started_at, 3)
            }

        if resolved_category.lower() in {"celebrity", "nguoi_noi_tieng", "người nổi tiếng"}:
            from agents.content_agent import ContentAgent

            stage_started = time.monotonic()
            content_kwargs: dict[str, Any] = {
                "niche": "celebrity",
                "language": language,
                "subject": "người nổi tiếng",
                "card_layout": card_layout,
                "selected_topic": selected_topic,
                "duration_target": duration_target,
            }
            if (
                get_settings().resilient_card_pipeline_enabled
                and self._uses_resilient_card_pipeline(duration_target)
            ):
                content_kwargs["run_id"] = str(topic_id)
            if progress_callback is not None:
                content_kwargs["progress_callback"] = progress_callback
            content_contract = await ContentAgent().run(
                **content_kwargs,
            )
            record_stage("content", stage_started)
            if content_contract.get("_production_inventory") is not None:
                stage_started = time.monotonic()
                recovered = await self._prepare_resilient_celebrity_contract(
                    topic_id=topic_id,
                    content_contract=content_contract,
                    selected_topic=selected_topic,
                    language=language,
                    progress_callback=progress_callback,
                )
                content_contract = recovered["content_contract"]
                fact_verification_contract = recovered["fact_verification_contract"]
                image_verification_contract = recovered["image_verification_contract"]
                production_summary = recovered["production_summary"]
                record_stage("card_recovery", stage_started)
            elif content_contract.get("contentFormat"):
                stage_started = time.monotonic()
                fact_verification_contract = await AIFactVerificationAgent().run(
                    content_contract=content_contract,
                )
                content_contract = apply_fact_corrections(
                    content_contract,
                    fact_verification_contract,
                )
                fact_verification_contract = align_fact_verification_to_content_contract(
                    fact_verification_contract,
                    content_contract,
                )
                record_stage("fact_verification", stage_started)
            video_data = build_video_data_from_content_contract(content_contract)
            if image_verification_contract is None:
                stage_started = time.monotonic()
                image_verification_contract = await RealImageAgent().run_for_content_contract(
                    topic_id=topic_id,
                    content_contract=content_contract,
                    strict=True,
                )
                record_stage("image_verification", stage_started)
            video_data = apply_verified_images_to_video_data(
                video_data,
                image_verification_contract,
            )
            if fact_verification_contract:
                video_data["fact_verification_contract"] = fact_verification_contract
            fallback_used = False
        else:
            title = f"{resolved_category} Local Render Validation"
            video_data = build_local_render_video_data(
                title=title,
                category=resolved_category,
                language=language,
            )
        validate_video_data(video_data)

        stage_started = time.monotonic()
        render_result = await self._render_local_video(
            topic_id=topic_id,
            video_data=video_data,
        )
        record_stage("render", stage_started)
        review: dict[str, Any] | None = None
        quality_gate: dict[str, Any] | None = None
        metadata_variants: dict[str, Any] = {}
        selected_metadata: dict[str, Any] = {}
        thumbnail: dict[str, Any] = {}
        if content_contract:
            stage_started = time.monotonic()
            quality_gate = run_production_quality_gate(
                topic_id=topic_id,
                video_path=render_result["file_path"],
                video_data=video_data,
                content_contract=content_contract,
                fact_verification_contract=fact_verification_contract,
                image_verification_contract=image_verification_contract,
                expected_card_layout=card_layout,
            )
            record_stage("quality_gate", stage_started)
            stage_started = time.monotonic()
            metadata_variants = await MetadataOptimizerAgent().run(
                content_contract=content_contract,
                selected_topic=selected_topic,
            )
            record_stage("metadata", stage_started)
            selected_metadata = metadata_variants.get("selected_metadata", {})
            youtube_title = str(selected_metadata.get("title") or content_contract["youtube_title"])
            youtube_description = str(
                selected_metadata.get("description") or content_contract["youtube_description"]
            )
            youtube_tags = selected_metadata.get("tags") or content_contract["youtube_tags"]
            stage_started = time.monotonic()
            thumbnail = build_review_thumbnail(
                review_id="",
                topic_dir=get_settings().storage_dir / "topics" / str(topic_id),
                content_contract=content_contract,
                image_verification_contract=image_verification_contract,
                selected_metadata=selected_metadata,
            )
            record_stage("thumbnail", stage_started)
            stage_started = time.monotonic()
            review = await create_review(
                job_id="",
                topic_id=topic_id,
                video_id=render_result["video_id"],
                file_path=render_result["file_path"],
                content_contract=content_contract,
                fact_verification_contract=fact_verification_contract,
                image_verification_contract=image_verification_contract,
                quality_gate=quality_gate,
                metadata_variants=metadata_variants,
                selected_metadata=selected_metadata,
                youtube_title=youtube_title,
                youtube_description=youtube_description,
                youtube_tags=youtube_tags,
                thumbnail_prompt=content_contract["thumbnail_prompt"],
                thumbnail=thumbnail,
            )
            record_stage("review", stage_started)

        record_stage("total", pipeline_started)

        return {
            "mode": "local_render",
            "category": resolved_category,
            "language": language,
            "topic_id": topic_id,
            "video_id": render_result["video_id"],
            "file_path": render_result["file_path"],
            "duration_sec": render_result["duration_sec"],
            "status": render_result["status"],
            "fallback_used": fallback_used,
            "review_id": review["review_id"] if review else "",
            "review_status": review["status"] if review else "",
            "content_contract": content_contract,
            "fact_verification_contract": fact_verification_contract,
            "youtube_title": (
                selected_metadata.get("title") or content_contract["youtube_title"]
                if content_contract
                else ""
            ),
            "youtube_description": (
                selected_metadata.get("description") or content_contract["youtube_description"]
                if content_contract
                else ""
            ),
            "youtube_tags": (
                selected_metadata.get("tags") or content_contract["youtube_tags"]
                if content_contract
                else []
            ),
            "thumbnail_prompt": content_contract["thumbnail_prompt"] if content_contract else "",
            "thumbnail": thumbnail,
            "image_verification_contract": image_verification_contract,
            "quality_gate": quality_gate,
            "metadata_variants": metadata_variants,
            "selected_metadata": selected_metadata,
            "selected_topic": selected_topic,
            "stage_timings": stage_timings,
            "production_summary": production_summary,
        }

    async def _prepare_resilient_celebrity_contract(
        self,
        *,
        topic_id: int,
        content_contract: dict[str, Any],
        selected_topic: dict[str, Any] | None,
        language: str,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Run fact/image gates per card and remove the in-memory inventory marker."""

        from agents.celebrity_content_orchestrator import CelebrityContentOrchestrator

        inventory = content_contract.get("_production_inventory")
        run_id = str(content_contract.get("_production_run_id") or topic_id)
        clean_contract = {
            key: value
            for key, value in content_contract.items()
            if not key.startswith("_production_")
        }
        settings = get_settings()
        orchestrator = CelebrityContentOrchestrator(
            planner_attempts=settings.card_planner_attempts,
            content_attempts=settings.card_content_repair_attempts,
            fact_attempts=settings.card_fact_repair_attempts,
            replacement_attempts=settings.card_replacement_attempts,
            minimum_ratio=settings.card_minimum_ratio,
        )
        return await orchestrator.verify_and_recover(
            {**clean_contract, "inventory": inventory, "run_id": run_id},
            topic_id=topic_id,
            topic=selected_topic or {"title": clean_contract.get("title", "")},
            language=language,
            fact_agent=AIFactVerificationAgent(),
            image_agent=RealImageAgent(),
            progress_callback=progress_callback,
        )

    @staticmethod
    def _uses_resilient_card_pipeline(duration_target: int) -> bool:
        scene_count = max(6, min(80, round((duration_target - 8) / 5.0)))
        return scene_count > 24

    @staticmethod
    def _new_local_render_topic_id() -> int:
        """Return a unique local-render topic id without requiring a database row."""
        return int(datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"))

    async def _render_local_video(
        self,
        *,
        topic_id: int,
        video_data: dict[str, Any],
        output_filename: str = "final_video.mp4",
    ) -> dict[str, Any]:
        """Render a local MP4 with Remotion using deterministic fallback data."""
        settings = get_settings()
        topic_dir = settings.storage_dir / "topics" / str(topic_id)
        topic_dir.mkdir(parents=True, exist_ok=True)

        data_path = topic_dir / "video_data.json"
        data_path.write_text(json.dumps(video_data, ensure_ascii=False, indent=2))

        project_root = Path(__file__).resolve().parent.parent
        video_engine_dir = project_root / "video_engine"
        public_dir = video_engine_dir / "public"
        images_dir = public_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        public_data_path = public_dir / "video_data.json"
        self._apply_render_media_defaults(video_data=video_data, public_dir=public_dir)
        public_data_path.write_text(json.dumps(video_data, ensure_ascii=False, indent=2))
        data_path.write_text(json.dumps(video_data, ensure_ascii=False, indent=2))
        self._copy_render_images_to_public(
            topic_dir=topic_dir,
            public_dir=public_dir,
            video_data=video_data,
        )

        placeholder_path = images_dir / "local-placeholder.svg"
        if not placeholder_path.exists():
            placeholder_path.write_text(
                "\n".join(
                    [
                        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">',
                        '<rect width="1200" height="800" fill="#111111"/>',
                        '<rect x="48" y="48" width="1104" height="704" fill="#20242c" stroke="#e52d27" stroke-width="16"/>',
                        '<text x="600" y="370" text-anchor="middle" fill="#ffffff" font-family="Arial, sans-serif" font-size="72" font-weight="700">LOCAL RENDER</text>',
                        '<text x="600" y="460" text-anchor="middle" fill="#e52d27" font-family="Arial, sans-serif" font-size="40" font-weight="700">Y5E AUTOMATION</text>',
                        "</svg>",
                    ]
                )
            )

        output_path = topic_dir / output_filename
        raw_output_path = output_path.with_suffix(".raw.mp4")
        props_json = json.dumps(video_data, ensure_ascii=False)
        composition_id = self._composition_id_for_template(str(video_data.get("template", "")))
        cmd = [
            "npx",
            "remotion",
            "render",
            "src/index.tsx",
            composition_id,
            str(raw_output_path),
            f"--props={props_json}",
            "--codec=h264",
            "--crf=20",
        ]
        browser_executable = os.getenv("REMOTION_BROWSER_EXECUTABLE", "").strip()
        if browser_executable:
            cmd.append(f"--browser-executable={browser_executable}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(video_engine_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=_LOCAL_RENDER_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(
                f"Local Remotion render timed out after {_LOCAL_RENDER_TIMEOUT_SEC}s"
            )

        if process.returncode != 0:
            stderr_text = stderr.decode(errors="replace")[:2000]
            raise RuntimeError(
                f"Local Remotion render failed (exit {process.returncode}): {stderr_text}"
            )

        await self._apply_export_hygiene(input_path=raw_output_path, output_path=output_path)
        raw_output_path.unlink(missing_ok=True)

        return {
            "video_id": topic_id,
            "file_path": str(output_path.resolve()),
            "duration_sec": 0,
            "status": "rendered",
        }

    @staticmethod
    def _apply_render_media_defaults(*, video_data: dict[str, Any], public_dir: Path) -> None:
        """Apply neutral branding and random background music for local renders."""
        video_data["logoPath"] = ""
        if str(video_data.get("musicPath", "")).strip():
            return

        project_root = Path(__file__).resolve().parent.parent
        music_roots = [
            project_root / "assets" / "audio" / "bgm",
            project_root / "assets" / "audio",
        ]
        supported_suffixes = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
        tracks: list[Path] = []
        for music_root in music_roots:
            if not music_root.is_dir():
                continue
            tracks.extend(
                path
                for path in music_root.rglob("*")
                if path.is_file() and path.suffix.lower() in supported_suffixes
            )
        if not tracks:
            return

        selected = random.choice(sorted(set(tracks), key=str))
        audio_dir = public_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        destination = audio_dir / selected.name
        shutil.copy2(selected, destination)
        video_data["musicPath"] = f"audio/{destination.name}"

    @staticmethod
    async def _apply_export_hygiene(*, input_path: Path, output_path: Path) -> None:
        """Create a YouTube-friendly MP4 without internal render metadata."""
        tmp_output = output_path.with_suffix(".cleaning.mp4")
        tmp_output.unlink(missing_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-map_metadata",
            "-1",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(tmp_output),
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(output_path.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            stderr_text = stderr.decode(errors="replace")[:2000]
            raise RuntimeError(
                f"MP4 export hygiene failed (exit {process.returncode}): {stderr_text}"
            )
        tmp_output.replace(output_path)

    @staticmethod
    def _copy_render_images_to_public(
        *,
        topic_dir: Path,
        public_dir: Path,
        video_data: dict[str, Any],
    ) -> None:
        """Copy verified topic images into Remotion public assets before render."""
        cards = video_data.get("cards")
        if not isinstance(cards, list):
            return

        for card in cards:
            if not isinstance(card, dict):
                continue
            for field_name in ("imagePath", "secondaryImagePath"):
                image_path = str(card.get(field_name, "")).strip()
                if not image_path.startswith("images/"):
                    continue
                source_path = topic_dir / image_path
                if not source_path.is_file():
                    continue
                target_path = public_dir / image_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, target_path)

    @staticmethod
    def _composition_id_for_template(template: str) -> str:
        compositions = {
            "timeline": "TimelineVideo",
            "ranking": "RankingVideo",
            "comparison": "ComparisonVideo",
        }
        return compositions.get(template.strip(), "TimelineVideo")

    # ── Analytics shortcut ───────────────────────────────────

    async def run_analytics(self) -> dict[str, Any]:
        """Run the analytics agent to collect performance data.

        Returns:
            The analytics report dict.
        """
        from agents.analytics_agent import AnalyticsAgent

        agent = AnalyticsAgent()
        return await agent.run()

    # ── Step wrapper with logging ────────────────────────────

    async def _step(
        self,
        step_name: str,
        topic_id: int | None,
        coro: Any,
    ) -> Any:
        """Execute a pipeline step with logging and error handling.

        Args:
            step_name: Human-readable step name for logging.
            topic_id: Related topic ID (may be ``None`` for first step).
            coro: The awaitable coroutine to execute.

        Returns:
            The result of the coroutine.

        Raises:
            PipelineError: If the step fails.
        """
        self.logger.info("▶ Starting step: %s (topic_id=%s)", step_name, topic_id)
        step_start = datetime.now(timezone.utc)

        try:
            # Log step start in pipeline_logs
            await db.execute(
                """
                INSERT INTO pipeline_logs
                    (topic_id, agent_name, status, started_at, created_at)
                VALUES ($1, $2, 'running', $3, $3)
                """,
                topic_id,
                f"pipeline.{step_name.lower().replace(' ', '_')}",
                step_start,
            )

            result = await coro

            elapsed = (datetime.now(timezone.utc) - step_start).total_seconds()
            self.logger.info(
                "✓ Step '%s' completed in %.1fs", step_name, elapsed
            )

            # Log step completion
            await db.execute(
                """
                INSERT INTO pipeline_logs
                    (topic_id, agent_name, status, started_at, completed_at, created_at)
                VALUES ($1, $2, 'completed', $3, $4, $4)
                """,
                topic_id,
                f"pipeline.{step_name.lower().replace(' ', '_')}",
                step_start,
                datetime.now(timezone.utc),
            )

            return result

        except Exception as exc:
            elapsed = (datetime.now(timezone.utc) - step_start).total_seconds()
            error_msg = f"Step '{step_name}' failed after {elapsed:.1f}s: {exc}"
            self.logger.error(error_msg, exc_info=True)

            # Log step failure
            await db.execute(
                """
                INSERT INTO pipeline_logs
                    (topic_id, agent_name, status, error_message,
                     started_at, completed_at, created_at)
                VALUES ($1, $2, 'failed', $3, $4, $5, $5)
                """,
                topic_id,
                f"pipeline.{step_name.lower().replace(' ', '_')}",
                str(exc)[:500],
                step_start,
                datetime.now(timezone.utc),
            )

            await notify_error(
                agent=f"Pipeline → {step_name}",
                error=str(exc)[:500],
            )

            raise PipelineError(error_msg) from exc

    # ── Individual agent runners ─────────────────────────────

    async def _run_topic_agent(
        self, category: str, language: str
    ) -> dict[str, Any]:
        """Run the TopicAgent to generate and score a topic.

        Args:
            category: Content category.
            language: Target language.

        Returns:
            The selected topic dict with an ``id`` key.

        Raises:
            PipelineError: If no viable topics are generated.
        """
        from agents.topic_agent import TopicAgent

        agent = TopicAgent()
        topics = await agent.run(category=category, language=language, count=1)

        if not topics:
            raise PipelineError(
                f"No viable topics generated for category='{category}', "
                f"language='{language}'"
            )

        # Pick the highest-scored topic
        if isinstance(topics, list):
            selected = max(topics, key=lambda t: t.get("score", 0))
        else:
            selected = topics

        self.logger.info(
            "Topic selected: '%s' (id=%d, score=%.1f)",
            selected.get("title", "?"),
            selected.get("id", 0),
            selected.get("score", 0),
        )
        return selected

    async def _run_research_agent(self, topic_id: int) -> dict[str, Any]:
        """Run the ResearchAgent to gather data for a topic.

        Args:
            topic_id: The topic to research.

        Returns:
            The research result dict.
        """
        from agents.research_agent import ResearchAgent

        agent = ResearchAgent()
        return await agent.run(topic_id=topic_id)

    async def _run_fact_check_agent(self, topic_id: int) -> dict[str, Any]:
        """Run the FactCheckAgent to verify researched claims.

        Args:
            topic_id: The topic whose facts to verify.

        Returns:
            A dict with ``total``, ``verified``, and ``rejected`` counts.
        """
        from agents.fact_check_agent import FactCheckAgent

        agent = FactCheckAgent()
        return await agent.run(topic_id=topic_id)

    async def _run_script_agent(self, topic_id: int) -> dict[str, Any]:
        """Run the ScriptAgent to generate a narration script.

        Args:
            topic_id: The topic to write a script for.

        Returns:
            The script result dict.
        """
        from agents.script_agent import ScriptAgent

        agent = ScriptAgent()
        return await agent.run(topic_id=topic_id)

    async def _run_image_agent(self, topic_id: int) -> dict[str, Any]:
        """Run the ImageAgent to generate or source images.

        Args:
            topic_id: The topic to generate images for.

        Returns:
            The image generation result dict.
        """
        from agents.image_agent import ImageAgent

        agent = ImageAgent()
        return await agent.run(topic_id=topic_id)

    async def _run_music_agent(self, topic_id: int) -> dict[str, Any]:
        """Run the MusicAgent to select background music.

        Args:
            topic_id: The topic to select music for.

        Returns:
            The music selection result dict.
        """
        from agents.music_agent import MusicAgent

        agent = MusicAgent()
        return await agent.run(topic_id=topic_id)

    async def _run_video_agent(self, topic_id: int) -> dict[str, Any]:
        """Run the VideoAgent to render the final video.

        Args:
            topic_id: The topic whose assets to render into a video.

        Returns:
            A dict with at least an ``id`` key (the videos table PK).
        """
        from agents.video_agent import VideoAgent

        agent = VideoAgent()
        return await agent.run(topic_id=topic_id)

    async def _run_shorts_agent(self, video_id: int) -> list[dict[str, Any]]:
        """Run the ShortsAgent to create short-form clips.

        Args:
            video_id: The rendered video to cut shorts from.

        Returns:
            A list of short dicts with ``id`` and ``file_path`` keys.
        """
        from agents.shorts_agent import ShortsAgent

        agent = ShortsAgent()
        result = await agent.run(video_id=video_id)

        # Normalise return type — agent may return dict or list
        if isinstance(result, dict):
            return result.get("shorts", [result])
        if isinstance(result, list):
            return result
        return [result]

    async def _run_thumbnail_agent(self, topic_id: int) -> dict[str, Any]:
        """Run the ThumbnailAgent to generate a custom thumbnail.

        Args:
            topic_id: The topic to generate a thumbnail for.

        Returns:
            The thumbnail generation result dict.
        """
        from agents.thumbnail_agent import ThumbnailAgent

        agent = ThumbnailAgent()
        return await agent.run(topic_id=topic_id)

    async def _run_upload_agent(self, video_id: int) -> dict[str, Any]:
        """Run the UploadAgent to publish the video to YouTube.

        Args:
            video_id: The rendered video's database ID.

        Returns:
            A dict with ``youtube_id``, ``title``, and ``url`` keys.
        """
        from agents.upload_agent import UploadAgent

        agent = UploadAgent()
        return await agent.run(video_id=video_id)

    async def _run_upload_short(self, short_id: int) -> dict[str, Any]:
        """Upload a single short video to YouTube.

        This creates a temporary ``videos``-compatible record for the
        short and uses the UploadAgent to publish it.

        Args:
            short_id: The ``shorts`` table primary key.

        Returns:
            Upload result dict from UploadAgent.
        """
        short = await db.fetchrow(
            "SELECT * FROM shorts WHERE id = $1", short_id
        )
        if not short:
            raise PipelineError(f"Short {short_id} not found")

        if not short["file_path"]:
            raise PipelineError(f"Short {short_id} has no file_path")

        # Get the parent video's topic_id for metadata
        parent_video = await db.fetchrow(
            "SELECT topic_id FROM videos WHERE id = $1", short["video_id"]
        )
        if not parent_video:
            raise PipelineError(
                f"Parent video {short['video_id']} not found for short {short_id}"
            )

        # Create a videos row for the short so UploadAgent can process it
        row = await db.fetchrow(
            """
            INSERT INTO videos (topic_id, file_path, resolution, duration_sec,
                                fps, codec, status, created_at)
            VALUES ($1, $2, '1080x1920', $3, 30, 'h264', 'rendered', $4)
            RETURNING id
            """,
            parent_video["topic_id"],
            short["file_path"],
            (short.get("end_sec", 0) - short.get("start_sec", 0)),
            datetime.now(timezone.utc),
        )
        short_video_id: int = row["id"]  # type: ignore[index]

        from agents.upload_agent import UploadAgent

        agent = UploadAgent()
        result = await agent.run(video_id=short_video_id)

        # Link the YouTube ID back to the shorts row
        if result.get("youtube_id"):
            await db.execute(
                "UPDATE shorts SET youtube_id = $1, status = 'published' WHERE id = $2",
                result["youtube_id"],
                short_id,
            )

        return result


# ── CLI entry point ──────────────────────────────────────────

async def main() -> None:
    """Run the pipeline from the command line.

    Usage::

        python -m agents.pipeline
    """
    import sys

    from core.database import init_db, close_db

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    # Parse CLI arguments
    category = sys.argv[1] if len(sys.argv) > 1 else "science"
    language = sys.argv[2] if len(sys.argv) > 2 else "vi"

    logger.info("Initialising database…")
    await init_db()

    try:
        pipeline = Pipeline()
        result = await pipeline.run_full(category=category, language=language)
        logger.info("Pipeline finished successfully: %s", result.get("upload_result"))
    except PipelineError as exc:
        logger.error("Pipeline aborted: %s", exc)
        sys.exit(1)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
