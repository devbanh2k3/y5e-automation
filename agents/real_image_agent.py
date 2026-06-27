"""Strict real-image agent for celebrity content."""

from __future__ import annotations

import html
import os
import re
import unicodedata
from io import BytesIO
from typing import Any
from urllib.parse import quote_plus, unquote

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
_QUERY_HINTS_BY_PERSON = {
    "jay-z": ("Jay-Z rapper", "Jay Z rapper", "Shawn Carter Jay-Z"),
    "lionel messi": ("Lionel Messi footballer", "Lionel Messi Argentina"),
}


class RealImageAgent(BaseAgent):
    """Find and verify real sourced images for celebrity render cards."""

    WIKIMEDIA_USER_AGENT = (
        "Y5E-AutomationBot/1.0 "
        "(https://github.com/devbanh2k3/y5e-automation; contact: configure WIKIMEDIA_USER_AGENT)"
    )

    def __init__(self) -> None:
        super().__init__(name="real_image_agent")

    async def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        """Run the real image agent with explicit keyword arguments."""
        return await self.run_for_content_contract(*args, **kwargs)

    def wikimedia_headers(self, *, accept: str | None = None) -> dict[str, str]:
        """Build Wikimedia policy-aware headers for API and CDN requests."""
        user_agent = os.getenv("WIKIMEDIA_USER_AGENT", self.WIKIMEDIA_USER_AGENT).strip()
        contact_email = os.getenv("WIKIMEDIA_CONTACT_EMAIL", "").strip()
        if "example.com" in user_agent.lower():
            raise ValueError(
                "WIKIMEDIA_USER_AGENT must not use placeholder contact; "
                "set a real project URL or contact address"
            )

        headers = {
            "User-Agent": user_agent,
            "Api-User-Agent": user_agent,
            "Accept-Encoding": "gzip",
        }
        if contact_email:
            headers["From"] = contact_email
        if accept:
            headers["Accept"] = accept
        return headers

    @staticmethod
    def wikimedia_search_queries(person_name: str) -> list[str]:
        """Return strict Commons search queries from broad to disambiguated."""
        cleaned_name = person_name.strip()
        ascii_name = RealImageAgent.strip_accents(cleaned_name)
        queries = [f"{cleaned_name} portrait"]
        if ascii_name and ascii_name != cleaned_name:
            queries.append(f"{ascii_name} portrait")
        queries.extend(_QUERY_HINTS_BY_PERSON.get(cleaned_name.lower(), ()))
        queries.extend(_QUERY_HINTS_BY_PERSON.get(ascii_name.lower(), ()))
        if cleaned_name.lower() not in _QUERY_HINTS_BY_PERSON:
            queries.extend(
                (
                    f"{cleaned_name} celebrity",
                    f"{cleaned_name} actor",
                    f"{cleaned_name} musician",
                    f"{cleaned_name} footballer",
                    cleaned_name,
                )
            )
        if (
            ascii_name
            and ascii_name != cleaned_name
            and ascii_name.lower() not in _QUERY_HINTS_BY_PERSON
        ):
            queries.extend(
                (
                    f"{ascii_name} celebrity",
                    f"{ascii_name} actor",
                    f"{ascii_name} musician",
                    f"{ascii_name} footballer",
                    ascii_name,
                )
            )
        return list(dict.fromkeys(query for query in queries if query.strip()))

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
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            for search_query in self.wikimedia_search_queries(person_name):
                query = quote_plus(search_query)
                url = (
                    "https://commons.wikimedia.org/w/api.php"
                    f"?action=query&generator=search"
                    f"&gsrsearch={query}"
                    f"&gsrnamespace=6"
                    f"&gsrlimit=10"
                    f"&prop=imageinfo"
                    f"&iiprop=url|extmetadata|mime|thumbmime"
                    f"&iiurlwidth=1200"
                    f"&format=json"
                )
                response = await client.get(
                    url,
                    headers=self.wikimedia_headers(accept="application/json"),
                )
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
                        self.logger.exception(
                            "Failed to process verified image candidate for %s",
                            person_name,
                        )
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
    def normalize_identity_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", RealImageAgent.strip_accents(value).lower()).strip()

    @staticmethod
    def strip_accents(value: str) -> str:
        """Return ASCII-ish text for matching names such as Khloé/Khloe."""
        normalized = unicodedata.normalize("NFKD", value)
        return "".join(char for char in normalized if not unicodedata.combining(char))

    @classmethod
    def evaluate_identity_match(cls, person_name: str, metadata_text: str) -> dict[str, Any]:
        normalized_name = cls.normalize_identity_text(person_name)
        normalized_metadata = cls.normalize_identity_text(metadata_text)
        compact_name = normalized_name.replace(" ", "")
        compact_metadata = normalized_metadata.replace(" ", "")
        if normalized_name and normalized_name in normalized_metadata:
            return {"identity_check_status": "passed", "identity_confidence": 0.95}
        if compact_name and compact_name in compact_metadata:
            return {"identity_check_status": "passed", "identity_confidence": 0.9}
        return {"identity_check_status": "failed", "identity_confidence": 0.0}

    @classmethod
    def evaluate_content_match(cls, metadata_text: str, source_url: str) -> dict[str, Any]:
        combined = unquote(f"{metadata_text} {source_url}").lower()
        blocked_terms = (
            "pdf",
            "book",
            "archive",
            "painting",
            "madonna and child",
            "madonna dell",
            "madonna_dell",
            "dell'orto",
            "dell orto",
            "beato leone bembo",
            "tattoo",
            "titian",
            "diagram",
            "logo",
            "fan art",
            "meme",
            "poster",
            "quote",
            "qr code",
            "wiki loves women",
            "#shesaid",
            "shesaid",
            "social media",
            "campaign",
            "people au défilé",
            "people au defile",
            "défilé channel",
            "defile channel",
        )
        if any(term in combined for term in blocked_terms):
            return {
                "content_match_status": "failed",
                "content_match_reason": "metadata indicates non-photo or unrelated media",
                "is_group_photo": False,
                "needs_human_review": True,
            }
        is_group_photo = any(
            term in combined
            for term in (
                "group",
                "with other",
                "honorees",
                " and ",
                "_and_",
                " e jay-z",
                "beyoncé e jay-z",
                "beyonce e jay-z",
            )
        )
        if is_group_photo:
            return {
                "content_match_status": "uncertain",
                "content_match_reason": "metadata indicates group photo",
                "is_group_photo": True,
                "needs_human_review": True,
            }
        return {
            "content_match_status": "passed",
            "content_match_reason": "metadata matches acceptable celebrity photo context",
            "is_group_photo": False,
            "needs_human_review": False,
        }

    @classmethod
    def identity_in_file_context(cls, person_name: str, title: str, source_url: str) -> bool:
        """Require the Commons file title or source URL to carry the celebrity identity."""
        identity = cls.evaluate_identity_match(person_name, f"{title} {unquote(source_url)}")
        return identity["identity_check_status"] == "passed"

    @classmethod
    def ambiguous_stage_name_has_person_context(
        cls,
        person_name: str,
        metadata_text: str,
        source_url: str,
    ) -> bool:
        """Reject ambiguous one-word stage names unless metadata has person/photo context."""
        if cls.normalize_identity_text(person_name) != "madonna":
            return True
        combined = unquote(f"{metadata_text} {source_url}").lower()
        person_context_terms = (
            "singer",
            "perform",
            "concert",
            "entertainer",
            "artist",
            "music",
            "stage",
            "live",
            "red carpet",
            "grammy",
            "mtv",
        )
        return any(term in combined for term in person_context_terms)

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
        download_url = str(info.get("thumburl") or image_url).strip()
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
        mime = str(info.get("mime", "")).strip()
        thumbmime = str(info.get("thumbmime", "")).strip()
        if mime and not mime.lower().startswith("image/"):
            return None
        if thumbmime and not thumbmime.lower().startswith("image/"):
            return None
        if not cls.is_allowed_license(license_text):
            return None
        identity = cls.evaluate_identity_match(person_name, metadata_text)
        content = cls.evaluate_content_match(metadata_text, source_url)
        if identity["identity_check_status"] != "passed":
            return None
        if not cls.identity_in_file_context(person_name, title, source_url):
            return None
        if not cls.ambiguous_stage_name_has_person_context(
            person_name,
            metadata_text,
            source_url,
        ):
            return None
        if content["content_match_status"] != "passed":
            return None
        return {
            "download_url": download_url,
            "image_url": image_url,
            "source_url": source_url,
            "license": license_text,
            "attribution": attribution or "Wikimedia Commons contributor",
            "metadata_text": metadata_text,
            "mime": mime,
            "thumbmime": thumbmime,
            "source_adapter": "commons_search_thumbnail",
            **identity,
            **content,
        }

    async def _download_image_bytes(self, image_url: str) -> tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                image_url,
                headers=self.wikimedia_headers(
                    accept="image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
                ),
            )
            response.raise_for_status()
            return response.content, response.headers.get("content-type", "")

    async def _process_verified_candidate(
        self,
        *,
        topic_id: int,
        scene_index: int,
        person_name: str,
        expected_title: str,
        candidate: dict[str, str],
    ) -> dict[str, Any]:
        download_url = candidate.get("download_url") or candidate["image_url"]
        raw_bytes, content_type = await self._download_image_bytes(download_url)
        if "image/" not in content_type.lower():
            raise ValueError("downloaded content is not an image")
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
