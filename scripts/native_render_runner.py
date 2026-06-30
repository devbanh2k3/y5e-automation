#!/usr/bin/env python3
"""Host-native resumable Remotion runner for macOS and Windows."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import Settings, get_settings
from core.render_contract import NativeRenderRequest, NativeRenderResult
from core.render_queue import (
    claim_render,
    complete_render,
    publish_runner_heartbeat,
    set_render_status,
)
from services.render_assets import build_render_asset_manifest
from services.render_chunks import RenderChunk, plan_chunks, write_concat_list
from services.render_encoder import (
    EncoderCapabilities,
    EncoderProfile,
    build_encode_command,
    detect_encoder_capabilities,
    select_encoder,
    validate_output,
)

logger = logging.getLogger("native_render_runner")

ChunkRenderer = Callable[[RenderChunk, Path], Awaitable[None]]
ChunkValidator = Callable[[Path, RenderChunk], bool]
Encoder = Callable[[Path, Path, EncoderProfile], Awaitable[None]]


class NativeRenderRunner:
    """Execute one render contract with resumable chunks and encoder fallback."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        project_root: Path = ROOT_DIR,
        chunk_validator: ChunkValidator | None = None,
        encoder: Encoder | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.project_root = project_root.resolve()
        self.video_engine_dir = self.project_root / "video_engine"
        self.chunk_validator = chunk_validator or self._default_chunk_validator
        self.encoder = encoder or self._encode

    async def render_missing_chunks(
        self,
        *,
        chunks: list[RenderChunk],
        chunk_dir: Path,
        render_one: ChunkRenderer,
        max_parallel: int,
        retries: int,
    ) -> tuple[list[Path], int]:
        """Render invalid checkpoints only, with bounded per-chunk retries."""
        chunk_dir.mkdir(parents=True, exist_ok=True)
        semaphore = asyncio.Semaphore(max(1, max_parallel))
        reused = 0
        outputs: list[Path] = []
        pending: list[tuple[RenderChunk, Path]] = []
        for chunk in chunks:
            output = chunk_dir / f"chunk-{chunk.index:04d}.mp4"
            outputs.append(output)
            if output.is_file() and self.chunk_validator(output, chunk):
                reused += 1
            else:
                output.unlink(missing_ok=True)
                pending.append((chunk, output))

        async def run_with_retry(chunk: RenderChunk, output: Path) -> None:
            async with semaphore:
                last_error: Exception | None = None
                for attempt in range(retries + 1):
                    try:
                        temporary = output.with_suffix(".rendering.mp4")
                        temporary.unlink(missing_ok=True)
                        await render_one(chunk, temporary)
                        if not self.chunk_validator(temporary, chunk):
                            raise RuntimeError(f"chunk {chunk.index} validation failed")
                        temporary.replace(output)
                        return
                    except Exception as exc:  # noqa: BLE001 - retry boundary.
                        last_error = exc
                        if attempt >= retries:
                            break
                        await asyncio.sleep(min(2**attempt, 4))
                raise RuntimeError(
                    f"chunk {chunk.index} failed after {retries + 1} attempts: {last_error}"
                ) from last_error

        await asyncio.gather(*(run_with_retry(chunk, path) for chunk, path in pending))
        return outputs, reused

    async def encode_with_fallback(
        self,
        *,
        input_path: Path,
        output_path: Path,
        preference: str,
        strict: bool,
        capabilities: EncoderCapabilities,
    ) -> EncoderProfile:
        """Encode with selected hardware and retry via CPU when allowed."""
        selected = select_encoder(preference, capabilities, strict=strict)
        try:
            await self.encoder(input_path, output_path, selected)
            return selected
        except Exception:
            if strict or selected.name == "libx264":
                raise
            cpu = select_encoder("cpu", capabilities, strict=True)
            output_path.unlink(missing_ok=True)
            await self.encoder(input_path, output_path, cpu)
            return cpu

    async def process(
        self,
        *,
        job_id: str,
        request: NativeRenderRequest,
        capabilities: EncoderCapabilities | None = None,
    ) -> NativeRenderResult:
        """Run all native render stages and return a validated final result."""
        started = time.monotonic()
        topic_dir = Path(request.output_path).parent
        cache_dir = topic_dir / "render-cache" / request.idempotency_key[:16]
        chunk_dir = cache_dir / "chunks"
        cache_dir.mkdir(parents=True, exist_ok=True)
        await set_render_status(job_id, "processing", stage="preparing_assets")

        video_data = json.loads(Path(request.video_data_path).read_text(encoding="utf-8"))
        video_data, asset_hash = await self._prepare_assets(
            request=request,
            video_data=video_data,
            cache_dir=cache_dir,
        )
        native_data_path = cache_dir / "video_data.native.json"
        native_data_path.write_text(
            json.dumps(video_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        total_frames, protected, boundaries = self._timeline(video_data, request.fps)
        chunks = plan_chunks(
            total_frames=total_frames,
            fps=request.fps,
            target_chunk_seconds=request.chunk_seconds,
            protected_ranges=protected,
            card_boundaries=boundaries,
        )
        video_hash = hashlib.sha256(native_data_path.read_bytes()).hexdigest()
        checkpoint_dir = chunk_dir / f"{video_hash[:12]}-{asset_hash[:12]}"
        await set_render_status(job_id, "processing", stage="rendering_chunks")

        async def render_one(chunk: RenderChunk, output: Path) -> None:
            await self._run(
                [
                    "npx", "remotion", "render", "src/index.tsx",
                    request.composition_id, str(output),
                    f"--props={native_data_path}",
                    f"--frames={chunk.start_frame}-{chunk.end_frame}",
                    "--codec=h264", f"--crf={request.crf}",
                    f"--concurrency={max(1, int(os.getenv('REMOTION_CONCURRENCY', '2')))}",
                ],
                cwd=self.video_engine_dir,
                timeout=max(300, request.target_duration * 6),
            )

        paths, reused = await self.render_missing_chunks(
            chunks=chunks,
            chunk_dir=checkpoint_dir,
            render_one=render_one,
            max_parallel=request.max_parallel_chunks,
            retries=self.settings.native_render_chunk_retries,
        )

        await set_render_status(job_id, "processing", stage="joining_chunks")
        concat_file = write_concat_list(paths, cache_dir / "concat.txt")
        joined = cache_dir / "joined.mp4"
        await self._run(
            [
                "ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-c", "copy", str(joined),
            ],
            cwd=cache_dir,
            timeout=max(300, request.target_duration * 2),
        )

        await set_render_status(job_id, "processing", stage="final_encoding")
        capabilities = capabilities or detect_encoder_capabilities()
        output_path = Path(request.output_path)
        temporary_output = output_path.with_name(f".{output_path.name}.native.tmp.mp4")
        temporary_output.unlink(missing_ok=True)
        profile = await self.encode_with_fallback(
            input_path=joined,
            output_path=temporary_output,
            preference=request.preferred_encoder,
            strict=request.encoder_strict,
            capabilities=capabilities,
        )
        probe = validate_output(
            temporary_output,
            expected_duration=total_frames / request.fps,
            require_audio=bool(video_data.get("musicPath")),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_output.replace(output_path)
        metrics = {
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "chunk_count": len(chunks),
            "reused_chunks": reused,
            "encoder": profile.name,
            "probe": probe,
        }
        (cache_dir / "render-manifest.json").write_text(
            json.dumps(metrics, indent=2), encoding="utf-8"
        )
        return NativeRenderResult(
            job_id=job_id,
            status="completed",
            output_path=str(output_path),
            encoder=profile.name,
            metrics=metrics,
        )

    async def _prepare_assets(
        self,
        *,
        request: NativeRenderRequest,
        video_data: dict[str, Any],
        cache_dir: Path,
    ) -> tuple[dict[str, Any], str]:
        cards = [dict(card) for card in video_data.get("cards") or []]
        topic_dir = Path(request.output_path).parent
        sources = [topic_dir / str(card["imagePath"]) for card in cards]
        manifest = build_render_asset_manifest(
            sources,
            cache_dir=cache_dir / "assets",
            max_size=(
                self.settings.render_image_max_width,
                self.settings.render_image_max_height,
            ),
            quality=self.settings.render_image_quality,
        )
        public_dir = self.video_engine_dir / "public" / "render-cache" / request.topic_id
        public_dir.mkdir(parents=True, exist_ok=True)
        for card, item in zip(cards, manifest.items, strict=True):
            foreground = public_dir / item.foreground_path.name
            background = public_dir / item.background_path.name
            shutil.copy2(item.foreground_path, foreground)
            shutil.copy2(item.background_path, background)
            card["normalizedImagePath"] = f"render-cache/{request.topic_id}/{foreground.name}"
            card["backgroundImagePath"] = f"render-cache/{request.topic_id}/{background.name}"
        video_data = dict(video_data)
        video_data["cards"] = cards
        return video_data, manifest.fingerprint

    @staticmethod
    def _timeline(
        video_data: dict[str, Any], fps: int
    ) -> tuple[int, list[tuple[int, int]], list[int]]:
        cards = video_data.get("cards") or []
        intro = 3 * fps
        outro = 5 * fps
        hold = int(video_data.get("holdDurationFrames") or 120)
        transition = int(video_data.get("transitionDurationFrames") or 15)
        cycle = hold + transition
        main = len(cards) * hold + max(0, len(cards) - 1) * transition
        total = intro + main + outro
        outro_start = total - outro
        boundaries = [intro + index * cycle for index in range(len(cards) + 1)]
        boundaries.extend((outro_start, total))
        return total, [(0, intro), (outro_start, total)], sorted(set(boundaries))

    @staticmethod
    def _default_chunk_validator(path: Path, _chunk: RenderChunk) -> bool:
        return path.is_file() and path.stat().st_size > 1024

    async def _encode(self, input_path: Path, output_path: Path, profile: EncoderProfile) -> None:
        await self._run(
            build_encode_command(
                input_path=input_path,
                output_path=output_path,
                profile=profile,
            ),
            cwd=output_path.parent,
            timeout=7200,
        )

    @staticmethod
    async def _run(command: list[str], *, cwd: Path, timeout: float) -> None:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f"command timed out after {timeout:g}s: {command[0]}")
        if process.returncode != 0:
            detail = stderr.decode(errors="replace")[-3000:]
            raise RuntimeError(f"command failed ({process.returncode}): {detail}")


async def run_loop() -> None:
    settings = get_settings()
    runner = NativeRenderRunner(settings=settings)
    runner_id = f"{socket.gethostname()}-{os.getpid()}"
    capabilities = detect_encoder_capabilities()
    while True:
        await publish_runner_heartbeat(
            runner_id=runner_id,
            capabilities={
                "platform": capabilities.platform,
                "encoders": sorted(capabilities.working_encoders),
            },
            ttl_seconds=settings.native_render_heartbeat_timeout_seconds,
        )
        claimed = await claim_render(timeout_seconds=settings.native_render_heartbeat_seconds)
        if not claimed:
            continue
        job_id, request = claimed
        try:
            result = await runner.process(
                job_id=job_id,
                request=request,
                capabilities=capabilities,
            )
            await complete_render(
                job_id,
                status="completed",
                output_path=result.output_path,
                encoder=result.encoder,
                metrics=result.metrics,
            )
        except Exception as exc:  # noqa: BLE001 - process boundary.
            logger.exception("Native render job failed")
            await complete_render(
                job_id,
                status="failed",
                error_code="native_render_failed",
                message=str(exc)[:1000],
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Probe local render dependencies")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, get_settings().log_level.upper(), logging.INFO))
    if args.check:
        capabilities = detect_encoder_capabilities()
        print(
            json.dumps(
                {
                    "platform": capabilities.platform,
                    "encoders": sorted(capabilities.working_encoders),
                    "node": shutil.which("node"),
                    "ffmpeg": shutil.which("ffmpeg"),
                    "ffprobe": shutil.which("ffprobe"),
                },
                indent=2,
            )
        )
        return
    asyncio.run(run_loop())


if __name__ == "__main__":
    main()
