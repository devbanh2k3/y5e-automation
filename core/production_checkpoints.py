"""Atomic filesystem checkpoints for resumable production runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CheckpointStore:
    """Persist run artifacts without exposing partially written JSON files."""

    def __init__(self, storage_dir: Path, *, run_id: str) -> None:
        self.run_dir = storage_dir / "production_runs" / run_id

    def save(self, name: str, payload: Any) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        destination = self.run_dir / f"{name}.json"
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(destination)
        return destination

    def load(self, name: str, *, default: Any = None) -> Any:
        path = self.run_dir / f"{name}.json"
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def append_error(self, payload: dict[str, Any]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "errors.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
