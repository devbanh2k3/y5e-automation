"""Deterministic frame chunk planning and checkpoint identities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RenderChunk:
    index: int
    start_frame: int
    end_frame: int

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame + 1


def _is_legal_boundary(boundary: int, protected_ranges: Iterable[tuple[int, int]]) -> bool:
    return not any(start < boundary < end for start, end in protected_ranges)


def plan_chunks(
    *,
    total_frames: int,
    fps: int,
    target_chunk_seconds: int,
    protected_ranges: Iterable[tuple[int, int]],
    card_boundaries: Iterable[int],
) -> list[RenderChunk]:
    """Split a timeline at the legal boundary nearest each target duration."""
    if total_frames <= 0 or fps <= 0 or target_chunk_seconds <= 0:
        raise ValueError("frame count, fps, and target duration must be positive")
    protected = tuple(protected_ranges)
    boundaries = sorted(
        {
            int(boundary)
            for boundary in (*card_boundaries, total_frames)
            if 0 < int(boundary) <= total_frames
            and _is_legal_boundary(int(boundary), protected)
        }
    )
    if not boundaries or boundaries[-1] != total_frames:
        raise ValueError("total frame boundary is protected or missing")

    target_frames = fps * target_chunk_seconds
    chunks: list[RenderChunk] = []
    start = 0
    while start < total_frames:
        candidates = [boundary for boundary in boundaries if boundary > start]
        if not candidates:
            raise ValueError(f"no legal chunk boundary after frame {start}")
        target = min(total_frames, start + target_frames)
        boundary = min(candidates, key=lambda value: (abs(value - target), value))
        chunks.append(
            RenderChunk(
                index=len(chunks),
                start_frame=start,
                end_frame=boundary - 1,
            )
        )
        start = boundary
    return chunks


def checkpoint_key(
    *,
    video_hash: str,
    asset_hash: str,
    start_frame: int,
    end_frame: int,
    contract_version: int = 1,
    quality: str = "h264-crf20",
) -> str:
    """Return a stable cache key for one exact rendered frame range."""
    payload = {
        "contract_version": contract_version,
        "video_hash": video_hash,
        "asset_hash": asset_hash,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "quality": quality,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def write_concat_list(paths: Iterable[Path], destination: Path) -> Path:
    """Write an FFmpeg concat manifest with safely quoted absolute paths."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for path in paths:
        escaped = str(path.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination
