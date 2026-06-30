"""Versioned contract shared by the Docker control plane and native renderer."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RenderContractError(ValueError):
    """Raised when a native render request is unsafe or unsupported."""


class NativeRenderRequest(BaseModel):
    """Immutable, JSON-safe description of one native render operation."""

    model_config = ConfigDict(frozen=True)

    contract_version: int = 1
    task_id: str
    topic_id: str
    output_root: str
    video_data_path: str
    output_path: str
    composition_id: str
    target_duration: int = Field(gt=0)
    width: int = 1920
    height: int = 1080
    fps: int = 30
    chunk_seconds: int = 40
    max_parallel_chunks: int = 2
    preferred_encoder: Literal["auto", "videotoolbox", "nvenc", "cpu"] = "auto"
    encoder_strict: bool = False
    crf: int = 20
    attempt: int = 0
    created_at: datetime
    idempotency_key: str

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        topic_id: str | int,
        output_root: str | Path,
        video_data_path: str | Path,
        output_path: str | Path,
        composition_id: str,
        target_duration: int,
        **options: Any,
    ) -> "NativeRenderRequest":
        root = Path(output_root).resolve()
        data_path = cls._confined_path(root, video_data_path)
        final_path = cls._confined_path(root, output_path)
        identity = {
            "contract_version": 1,
            "task_id": str(task_id),
            "topic_id": str(topic_id),
            "video_data_path": str(data_path),
            "output_path": str(final_path),
            "composition_id": composition_id,
            "target_duration": int(target_duration),
            **options,
        }
        key = hashlib.sha256(
            json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return cls(
            task_id=str(task_id),
            topic_id=str(topic_id),
            output_root=str(root),
            video_data_path=str(data_path),
            output_path=str(final_path),
            composition_id=composition_id,
            target_duration=target_duration,
            created_at=datetime.now(timezone.utc),
            idempotency_key=key,
            **options,
        )

    @staticmethod
    def _confined_path(root: Path, candidate: str | Path) -> Path:
        path = Path(candidate).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise RenderContractError(f"path is outside output root: {path}") from exc
        return path


class NativeRenderResult(BaseModel):
    """Terminal or intermediate result reported by a native runner."""

    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    output_path: str = ""
    encoder: str = ""
    error_code: str = ""
    message: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
