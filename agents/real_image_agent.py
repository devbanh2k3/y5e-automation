"""Strict real-image agent for celebrity content."""

from __future__ import annotations

import re
from typing import Any

from agents.base_agent import BaseAgent

_ALLOWED_LICENSE_PARTS = (
    "cc0",
    "public domain",
    "cc by",
    "cc-by",
    "creative commons attribution",
    "creative commons attribution-sharealike",
)


class RealImageAgent(BaseAgent):
    """Find and verify real sourced images for celebrity render cards."""

    def __init__(self) -> None:
        super().__init__(name="real_image_agent")

    @staticmethod
    def extract_person_name(scene_title: str) -> str:
        cleaned = re.sub(r"^#\d+\s+", "", scene_title.strip())
        return cleaned.strip()

    @staticmethod
    def is_allowed_license(license_text: str) -> bool:
        normalized = license_text.strip().lower()
        return any(part in normalized for part in _ALLOWED_LICENSE_PARTS)

    @staticmethod
    def metadata_matches_person(person_name: str, metadata_text: str) -> bool:
        name_tokens = [
            token.lower()
            for token in re.findall(r"[A-Za-z0-9]+", person_name)
            if len(token) > 1
        ]
        normalized_metadata = metadata_text.lower()
        return bool(name_tokens) and all(token in normalized_metadata for token in name_tokens)

    @staticmethod
    def build_missing_item(
        *,
        scene_index: int,
        person_name: str,
        expected_title: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "scene_index": scene_index,
            "person_name": person_name,
            "expected_title": expected_title,
            "status": "missing_image",
            "confidence": 0.0,
            "local_path": "",
            "render_image_path": "",
            "source_url": "",
            "image_url": "",
            "license": "",
            "attribution": "",
            "reject_reason": reason,
        }
