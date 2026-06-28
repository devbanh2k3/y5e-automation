"""SEO-safe YouTube metadata helpers."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_HASHTAGS = [
    "CelebrityFacts",
    "DataComparison",
    "FamousPeople",
    "CelebrityRanking",
    "Entertainment",
]


def ensure_description_hashtags(
    description: str,
    tags: list[Any],
    *,
    max_hashtags: int = 12,
) -> str:
    """Append a concise hashtag block derived from tags when missing."""
    body = str(description or "").strip()
    existing = _extract_hashtags(body)
    candidates = existing + [_tag_to_hashtag(tag) for tag in tags] + DEFAULT_HASHTAGS
    hashtags = _dedupe([item for item in candidates if item])[:max_hashtags]
    if not hashtags:
        return body
    hashtag_line = " ".join(f"#{item}" for item in hashtags)
    body_without_trailing_hashtags = _strip_trailing_hashtag_block(body)
    if body_without_trailing_hashtags:
        return f"{body_without_trailing_hashtags}\n\n{hashtag_line}"
    return hashtag_line


def _extract_hashtags(value: str) -> list[str]:
    return [_normalize_hashtag(match) for match in re.findall(r"#([A-Za-z0-9_]+)", value)]


def _strip_trailing_hashtag_block(value: str) -> str:
    lines = value.rstrip().splitlines()
    while lines and _is_hashtag_only_line(lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def _is_hashtag_only_line(value: str) -> bool:
    text = value.strip()
    return bool(text) and all(part.startswith("#") for part in text.split())


def _tag_to_hashtag(value: Any) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(value or ""))
    if not words:
        return ""
    return _normalize_hashtag("".join(word.capitalize() for word in words))


def _normalize_hashtag(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", value).strip("_")[:60]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned
