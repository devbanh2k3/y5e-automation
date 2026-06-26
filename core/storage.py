"""File storage manager for topic assets and rendered videos."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from core.config import get_settings

logger = logging.getLogger(__name__)

# File extensions considered "final" deliverables (kept during cleanup)
_FINAL_EXTENSIONS: set[str] = {".mp4", ".mkv", ".webm", ".srt", ".json"}


def get_topic_dir(topic_id: int) -> Path:
    """Return the directory for a specific topic, creating it if needed.

    Args:
        topic_id: The numeric topic ID.

    Returns:
        An absolute ``Path`` to ``<storage>/topic_<id>/``.
    """
    settings = get_settings()
    topic_dir = settings.storage_dir / f"topic_{topic_id}"
    topic_dir.mkdir(parents=True, exist_ok=True)
    return topic_dir


def get_asset_path(topic_id: int, filename: str) -> Path:
    """Return the full path for an asset file inside a topic directory.

    The parent directory is created automatically.

    Args:
        topic_id: The numeric topic ID.
        filename: The desired filename (e.g. ``thumbnail.png``).

    Returns:
        Absolute ``Path`` to the asset file.
    """
    topic_dir = get_topic_dir(topic_id)
    asset_path = topic_dir / filename
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    return asset_path


def cleanup_topic(topic_id: int, keep_final: bool = True) -> int:
    """Delete temporary files for a topic.

    Args:
        topic_id: The numeric topic ID.
        keep_final: When ``True``, files whose extension is in
            ``_FINAL_EXTENSIONS`` are preserved.  When ``False``,
            the entire topic directory is removed.

    Returns:
        The number of files deleted.
    """
    topic_dir = get_topic_dir(topic_id)

    if not topic_dir.exists():
        logger.warning("Topic directory does not exist: %s", topic_dir)
        return 0

    if not keep_final:
        count = sum(1 for _ in topic_dir.rglob("*") if _.is_file())
        shutil.rmtree(topic_dir)
        logger.info("Removed entire topic directory %s (%d files)", topic_dir, count)
        return count

    deleted = 0
    for file_path in topic_dir.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() not in _FINAL_EXTENSIONS:
            file_path.unlink()
            deleted += 1

    logger.info("Cleaned up %d temporary files in %s", deleted, topic_dir)
    return deleted


def get_storage_usage() -> dict[str, Any]:
    """Return disk-usage statistics for the storage directory.

    Returns:
        A dict with keys ``total_bytes``, ``total_files``,
        ``total_topics``, and ``per_topic`` breakdown.
    """
    settings = get_settings()
    root = settings.storage_dir

    total_bytes: int = 0
    total_files: int = 0
    per_topic: dict[str, dict[str, int]] = {}

    for item in root.iterdir():
        if item.is_dir() and item.name.startswith("topic_"):
            topic_bytes = 0
            topic_files = 0
            for f in item.rglob("*"):
                if f.is_file():
                    size = f.stat().st_size
                    topic_bytes += size
                    topic_files += 1
            per_topic[item.name] = {
                "bytes": topic_bytes,
                "files": topic_files,
            }
            total_bytes += topic_bytes
            total_files += topic_files

    # Include disk-level free space
    disk_usage = shutil.disk_usage(root)

    return {
        "total_bytes": total_bytes,
        "total_files": total_files,
        "total_topics": len(per_topic),
        "per_topic": per_topic,
        "disk_total_bytes": disk_usage.total,
        "disk_free_bytes": disk_usage.free,
    }
