"""Strict real-image agent for celebrity content."""

from __future__ import annotations

import html
import re
from io import BytesIO
from typing import Any
from urllib.parse import quote_plus

import httpx
from PIL import Image

from agents.base_agent import BaseAgent
from core.config import get_settings
from core.video_contract import (
    build_image_verification_contract_v1,
    validate_image_verification_contract_v1,
)

_ALLOWED_LICENSE_PARTS = (
    "cc0",
    "public domain",
    "cc by",
    "cc-by",
    "creative commons attribution",
    "creative commons attribution-sharealike",
)
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
_MIN_IMAGE_WIDTH = 200
_MIN_IMAGE_HEIGHT = 200


class RealImageAgent(BaseAgent):
    """Find and verify real sourced images for celebrity render cards."""

    WIKIMEDIA_USER_AGENT = (
        "Y5E-Automation/1.0 "
        "(https://github.com/devbanh2k3/y5e-automation; devbanh@example.com)"
    )

    def __init__(self) -> None:
        super().__init__(name="real_image_agent")

    async def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        """Run the real image agent with explicit keyword arguments."""
        return await self.run_for_content_contract(*args, **kwargs)

    async def run_for_content_contract(
        self,
        *,
        topic_id: int,
        content_contract: dict[str, Any],
        strict: bool = True,
    ) -> dict[str, Any]:
        scenes = content_contract.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("content_contract.scenes must contain at least one scene")

        items: list[dict[str, Any]] = []
        for scene_index, scene in enumerate(scenes):
            expected_title = str(scene.get("title", "")).strip()
            person_name = self.extract_person_name(expected_title)
            if not person_name:
                items.append(
                    self.build_missing_item(
                        scene_index=scene_index,
                        person_name="",
                        expected_title=expected_title,
                        reason="scene title does not contain a person name",
                    )
                )
                continue

            item = await self._find_verified_image(
                topic_id=topic_id,
                scene_index=scene_index,
                person_name=person_name,
                expected_title=expected_title,
            )
            if item is None:
                item = self.build_missing_item(
                    scene_index=scene_index,
                    person_name=person_name,
                    expected_title=expected_title,
                    reason="no verified Wikimedia image found",
                )
            items.append(item)

        contract = build_image_verification_contract_v1(topic_id=topic_id, items=items)
        validate_image_verification_contract_v1(contract)
        if strict and contract["status"] != "verified":
            missing = [
                item["person_name"]
                for item in contract["items"]
                if item["status"] != "verified"
            ]
            raise ValueError(f"missing verified real images: {', '.join(missing)}")
        return contract

    async def _find_verified_image(
        self,
        *,
        topic_id: int,
        scene_index: int,
        person_name: str,
        expected_title: str,
    ) -> dict[str, Any] | None:
        query = quote_plus(f"{person_name} portrait")
        url = (
            "https://commons.wikimedia.org/w/api.php"
            f"?action=query&generator=search"
            f"&gsrsearch={query}"
            f"&gsrnamespace=6"
            f"&gsrlimit=10"
            f"&prop=imageinfo"
            f"&iiprop=url|extmetadata"
            f"&format=json"
        )
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": self.WIKIMEDIA_USER_AGENT})
            response.raise_for_status()
            data = response.json()

        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            candidate = self.extract_wikimedia_candidate(person_name, page)
            if candidate is None:
                continue
            try:
                return await self._process_verified_candidate(
                    topic_id=topic_id,
                    scene_index=scene_index,
                    person_name=person_name,
                    expected_title=expected_title,
                    candidate=candidate,
                )
            except Exception:
                self.logger.exception("Failed to process verified image candidate for %s", person_name)
                continue
        return None

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

    @staticmethod
    def clean_metadata(value: Any) -> str:
        return re.sub(r"<[^>]+>", "", html.unescape(str(value or ""))).strip()

    @classmethod
    def extract_wikimedia_candidate(
        cls,
        person_name: str,
        page: dict[str, Any],
    ) -> dict[str, str] | None:
        image_info_list = page.get("imageinfo")
        if not image_info_list:
            return None
        info = image_info_list[0]
        image_url = str(info.get("url", "")).strip()
        source_url = str(info.get("descriptionurl", "")).strip()
        metadata = info.get("extmetadata") or {}
        license_text = cls.clean_metadata(metadata.get("LicenseShortName", {}).get("value", ""))
        attribution = cls.clean_metadata(metadata.get("Artist", {}).get("value", ""))
        description = cls.clean_metadata(metadata.get("ImageDescription", {}).get("value", ""))
        title = cls.clean_metadata(page.get("title", ""))
        metadata_text = " ".join(
            part for part in (title, license_text, attribution, description) if part
        )

        if not image_url or not source_url:
            return None
        if not cls.is_allowed_license(license_text):
            return None
        if not cls.metadata_matches_person(person_name, metadata_text):
            return None
        return {
            "image_url": image_url,
            "source_url": source_url,
            "license": license_text,
            "attribution": attribution or "Wikimedia Commons contributor",
            "metadata_text": metadata_text,
        }

    async def _download_image_bytes(self, image_url: str) -> bytes:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                image_url,
                headers={"User-Agent": self.WIKIMEDIA_USER_AGENT},
            )
            response.raise_for_status()
            return response.content

    async def _process_verified_candidate(
        self,
        *,
        topic_id: int,
        scene_index: int,
        person_name: str,
        expected_title: str,
        candidate: dict[str, str],
    ) -> dict[str, Any]:
        raw_bytes = await self._download_image_bytes(candidate["image_url"])
        with Image.open(BytesIO(raw_bytes)) as image:
            image = image.convert("RGB")
            if image.width < _MIN_IMAGE_WIDTH or image.height < _MIN_IMAGE_HEIGHT:
                raise ValueError("image is too small")
            settings = get_settings()
            image_dir = settings.storage_dir / "topics" / str(topic_id) / "images"
            image_dir.mkdir(parents=True, exist_ok=True)
            local_path = image_dir / f"real_{scene_index}.webp"
            image.save(local_path, format="WEBP", quality=90)

        return {
            "scene_index": scene_index,
            "person_name": person_name,
            "expected_title": expected_title,
            "status": "verified",
            "confidence": 0.9,
            "local_path": str(local_path),
            "render_image_path": f"images/real_{scene_index}.webp",
            "source_url": candidate["source_url"],
            "image_url": candidate["image_url"],
            "license": candidate["license"],
            "attribution": candidate["attribution"],
            "reject_reason": "",
        }
