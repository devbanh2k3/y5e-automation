"""Durable reservation history for autonomous Celebrity topics."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class TopicHistoryError(RuntimeError):
    """Raised when topic history cannot be read or updated safely."""


class TopicHistoryRepository:
    """Persist topic reservations with an inter-process file lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(f"{path.suffix}.lock")

    def load(self) -> list[dict[str, Any]]:
        with self._lock(exclusive=False):
            return self._read_unlocked()

    def reserve_many(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        with self._lock(exclusive=True):
            records = self._read_unlocked()
            reservation_ids = {
                str(record.get("reservation_id", "")) for record in records
            }
            normalized_titles = {
                str(record.get("normalized_title", "")) for record in records
            }
            accepted: list[dict[str, Any]] = []
            now = datetime.now(timezone.utc).isoformat()

            for candidate in candidates:
                reservation_id = str(candidate.get("reservation_id", ""))
                normalized_title = str(candidate.get("normalized_title", ""))
                if not reservation_id or not normalized_title:
                    raise TopicHistoryError(
                        "reservation_id and normalized_title are required"
                    )
                if (
                    reservation_id in reservation_ids
                    or normalized_title in normalized_titles
                ):
                    continue
                record = dict(candidate)
                record["status"] = "reserved"
                record["reserved_at"] = now
                accepted.append(record)
                records.append(record)
                reservation_ids.add(reservation_id)
                normalized_titles.add(normalized_title)

            if accepted:
                self._write_unlocked(records)
            return accepted

    def mark_produced(
        self,
        reservation_id: str,
        *,
        topic_id: str,
    ) -> dict[str, Any]:
        return self._transition(
            reservation_id,
            status="produced",
            topic_id=topic_id,
        )

    def mark_failed(
        self,
        reservation_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return self._transition(
            reservation_id,
            status="failed",
            failure_reason=reason,
        )

    def _transition(
        self,
        reservation_id: str,
        *,
        status: str,
        **updates: Any,
    ) -> dict[str, Any]:
        with self._lock(exclusive=True):
            records = self._read_unlocked()
            for record in records:
                if record.get("reservation_id") != reservation_id:
                    continue
                record.update(updates)
                record["status"] = status
                record[f"{status}_at"] = datetime.now(timezone.utc).isoformat()
                self._write_unlocked(records)
                return dict(record)
        raise TopicHistoryError(f"unknown topic reservation: {reservation_id}")

    @contextmanager
    def _lock(self, *, exclusive: bool) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        with self.lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), operation)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TopicHistoryError(f"topic history is corrupt: {exc}") from exc
        if not isinstance(payload, list) or not all(
            isinstance(record, dict) for record in payload
        ):
            raise TopicHistoryError("topic history is corrupt: expected a list of objects")
        return payload

    def _write_unlocked(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(records, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise TopicHistoryError(f"could not write topic history: {exc}") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
