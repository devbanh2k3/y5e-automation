"""Strict real-image agent for celebrity content."""

from __future__ import annotations

import asyncio
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
_DEFAULT_REAL_IMAGE_CONCURRENCY = 4
_MAX_REAL_IMAGE_CONCURRENCY = 8
_QUERY_HINTS_BY_PERSON = {
    "drake": ("Drake rapper", "Aubrey Graham Drake", "Drake musician"),
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

    @staticmethod
    def person_search_names(person_name: str) -> list[str]:
        """Return canonical and fallback person names for image search."""
        cleaned = person_name.strip()
        names: list[str] = []
        coen_match = re.match(r"^Coen Brothers\s+\((Joel|Ethan)\)$", cleaned, re.IGNORECASE)
        if coen_match:
            names.append(f"{coen_match.group(1).title()} Coen")
        names.append(cleaned)
        without_parenthetical = re.sub(r"\s+\([^)]*\)\s*$", "", cleaned).strip()
        if without_parenthetical and without_parenthetical != cleaned:
            names.append(without_parenthetical)
        return list(dict.fromkeys(name for name in names if name))

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

        semaphore = asyncio.Semaphore(self.real_image_concurrency())

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            tasks = [
                self._verify_scene_image(
                    client=client,
                    semaphore=semaphore,
                    topic_id=topic_id,
                    scene_index=scene_index,
                    scene=scene,
                )
                for scene_index, scene in enumerate(scenes)
            ]
            items = sorted(await asyncio.gather(*tasks), key=lambda item: item["scene_index"])

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

    async def verify_scene(
        self,
        *,
        topic_id: int,
        scene_index: int,
        scene: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify one scene and return a missing item instead of raising."""

        semaphore = asyncio.Semaphore(1)
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            return await self._verify_scene_image(
                client=client,
                semaphore=semaphore,
                topic_id=topic_id,
                scene_index=scene_index,
                scene=scene,
            )

    @staticmethod
    def real_image_concurrency() -> int:
        """Return bounded per-video image lookup concurrency."""
        try:
            value = int(os.getenv("REAL_IMAGE_CONCURRENCY", str(_DEFAULT_REAL_IMAGE_CONCURRENCY)))
        except ValueError:
            value = _DEFAULT_REAL_IMAGE_CONCURRENCY
        return max(1, min(_MAX_REAL_IMAGE_CONCURRENCY, value))

    async def _verify_scene_image(
        self,
        *,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        topic_id: int,
        scene_index: int,
        scene: dict[str, Any],
    ) -> dict[str, Any]:
        expected_title = str(scene.get("title", "")).strip()
        person_name = self.extract_person_name(expected_title)
        if not person_name:
            return self.build_missing_item(
                scene_index=scene_index,
                person_name="",
                expected_title=expected_title,
                reason="scene title does not contain a person name",
            )

        async with semaphore:
            item = await self._find_verified_image(
                client=client,
                topic_id=topic_id,
                scene_index=scene_index,
                person_name=person_name,
                expected_title=expected_title,
            )
        if item is None:
            return self.build_missing_item(
                scene_index=scene_index,
                person_name=person_name,
                expected_title=expected_title,
                reason="no verified Wikimedia image found",
            )
        return item

    async def _find_verified_image(
        self,
        *,
        topic_id: int,
        scene_index: int,
        person_name: str,
        expected_title: str,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any] | None:
        if client is None:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as owned_client:
                return await self._find_verified_image(
                    client=owned_client,
                    topic_id=topic_id,
                    scene_index=scene_index,
                    person_name=person_name,
                    expected_title=expected_title,
                )

        for search_name in self.person_search_names(person_name):
            result = await self._process_direct_candidates(
                candidates=await self._wikidata_p18_candidates(client, search_name),
                topic_id=topic_id,
                scene_index=scene_index,
                person_name=search_name,
                expected_title=expected_title,
            )
            if result is not None:
                return result
            result = await self._process_direct_candidates(
                candidates=await self._wikipedia_pageimage_candidates(client, search_name),
                topic_id=topic_id,
                scene_index=scene_index,
                person_name=search_name,
                expected_title=expected_title,
            )
            if result is not None:
                return result

        for search_name in self.person_search_names(person_name):
            for search_query in self.wikimedia_search_queries(search_name):
                result = await self._find_commons_search_image(
                    client=client,
                    topic_id=topic_id,
                    scene_index=scene_index,
                    person_name=search_name,
                    expected_title=expected_title,
                    search_query=search_query,
                )
                if result is not None:
                    return result
        return None

    async def _process_direct_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        topic_id: int,
        scene_index: int,
        person_name: str,
        expected_title: str,
    ) -> dict[str, Any] | None:
        for candidate in candidates:
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
                    "Failed to process direct image candidate for %s",
                    person_name,
                )
                continue
        return None

    async def _find_commons_search_image(
        self,
        *,
        client: httpx.AsyncClient,
        topic_id: int,
        scene_index: int,
        person_name: str,
        expected_title: str,
        search_query: str,
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
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
            candidates.append(candidate)

        candidates.sort(
            key=lambda candidate: float(candidate.get("quality_score", 0.0)),
            reverse=True,
        )
        for candidate in candidates:
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

    async def _wikidata_p18_candidates(
        self,
        client: httpx.AsyncClient,
        person_name: str,
    ) -> list[dict[str, Any]]:
        search_url = (
            "https://www.wikidata.org/w/api.php"
            "?action=wbsearchentities"
            f"&search={quote_plus(person_name)}"
            "&language=en&format=json&limit=3"
        )
        response = await client.get(search_url, headers=self.wikimedia_headers(accept="application/json"))
        response.raise_for_status()
        search_results = response.json().get("search", [])
        candidates: list[dict[str, Any]] = []
        for result in search_results:
            entity_id = str(result.get("id", "")).strip()
            label = str(result.get("label", "")).strip()
            if not entity_id or self.evaluate_identity_match(person_name, label)["identity_check_status"] != "passed":
                continue
            entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
            entity_response = await client.get(
                entity_url,
                headers=self.wikimedia_headers(accept="application/json"),
            )
            entity_response.raise_for_status()
            filename = self._extract_wikidata_p18_filename(entity_response.json(), entity_id)
            if not filename:
                continue
            candidate = await self._commons_file_candidate(
                client=client,
                person_name=person_name,
                filename=filename,
                source_adapter="wikidata_p18",
            )
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _wikipedia_pageimage_candidates(
        self,
        client: httpx.AsyncClient,
        person_name: str,
    ) -> list[dict[str, Any]]:
        url = (
            "https://en.wikipedia.org/w/api.php"
            "?action=query&generator=search"
            f"&gsrsearch={quote_plus(person_name)}"
            "&gsrlimit=1&prop=pageimages"
            "&piprop=name&pithumbsize=1200&format=json"
        )
        response = await client.get(url, headers=self.wikimedia_headers(accept="application/json"))
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
        candidates: list[dict[str, Any]] = []
        for page in pages.values():
            title = str(page.get("title", "")).strip()
            filename = str(page.get("pageimage", "")).strip()
            if not filename:
                continue
            if self.evaluate_identity_match(person_name, title)["identity_check_status"] != "passed":
                continue
            candidate = await self._commons_file_candidate(
                client=client,
                person_name=person_name,
                filename=filename,
                source_adapter="wikipedia_pageimage",
            )
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    async def _commons_file_candidate(
        self,
        *,
        client: httpx.AsyncClient,
        person_name: str,
        filename: str,
        source_adapter: str,
    ) -> dict[str, Any] | None:
        title = f"File:{filename}"
        url = (
            "https://commons.wikimedia.org/w/api.php"
            "?action=query"
            f"&titles={quote_plus(title)}"
            "&prop=imageinfo"
            "&iiprop=url|extmetadata|mime|thumbmime"
            "&iiurlwidth=1200"
            "&format=json"
        )
        response = await client.get(url, headers=self.wikimedia_headers(accept="application/json"))
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
        for page in pages.values():
            candidate = self.extract_wikimedia_candidate(person_name, page)
            if candidate is None:
                continue
            candidate["source_adapter"] = source_adapter
            return candidate
        return None

    @staticmethod
    def _extract_wikidata_p18_filename(payload: dict[str, Any], entity_id: str) -> str:
        claims = payload.get("entities", {}).get(entity_id, {}).get("claims", {})
        p18_claims = claims.get("P18")
        if not isinstance(p18_claims, list) or not p18_claims:
            return ""
        value = (
            p18_claims[0]
            .get("mainsnak", {})
            .get("datavalue", {})
            .get("value", "")
        )
        return str(value).strip()

    @staticmethod
    def extract_person_name(scene_title: str) -> str:
        cleaned = re.sub(r"^#\d+\s+", "", scene_title.strip())
        names = RealImageAgent.person_search_names(cleaned)
        if names:
            return names[0]
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
            "francis drake",
            "por un artista anonimo",
            "por un artista anónimo",
            "historical painting",
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
    def score_image_candidate(cls, candidate: dict[str, Any]) -> dict[str, Any]:
        """Score how suitable a verified real image is for a celebrity ranking card."""
        combined = cls.normalize_identity_text(
            f"{candidate.get('metadata_text', '')} {candidate.get('source_url', '')}"
        )
        reasons: list[str] = []
        score = 0.58

        hard_negative_terms = (
            "poster",
            "quote",
            "qr code",
            "wiki loves women",
            "shesaid",
            "social media",
            "campaign",
            "infographic",
            "collage",
            "logo",
            "meme",
        )
        if any(term in combined for term in hard_negative_terms):
            return {
                "quality_score": 0.15,
                "quality_reason": "metadata indicates poster, quote graphic, campaign, or infographic",
            }

        if candidate.get("content_match_status") != "passed":
            score -= 0.35
            reasons.append("content match is not passed")
        if candidate.get("needs_human_review"):
            score -= 0.3
            reasons.append("candidate needs human review")
        if candidate.get("is_group_photo"):
            score -= 0.25
            reasons.append("metadata indicates group photo")

        if any(term in combined for term in ("portrait", "close up", "closeup", "headshot")):
            score += 0.18
            reasons.append("portrait or close-up metadata")
        if any(term in combined for term in ("performing", "concert", "live", "stage", "singer")):
            score += 0.14
            reasons.append("stage or performance metadata")
        if any(
            term in combined
            for term in (
                "red carpet",
                "premiere",
                "award",
                "awards",
                "event",
                "golden globes",
                "grammy",
                "grammys",
                "oscars",
                "met gala",
            )
        ):
            score += 0.16
            reasons.append("public event metadata")
        if any(term in combined for term in ("photo", "photograph")):
            score += 0.04
            reasons.append("photo metadata")

        score = max(0.0, min(0.98, score))
        return {
            "quality_score": round(score, 2),
            "quality_reason": "; ".join(reasons) or "basic verified celebrity image metadata",
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
        quality = cls.score_image_candidate(
            {
                "metadata_text": metadata_text,
                "source_url": source_url,
                **content,
            }
        )
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
            **quality,
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
            "quality_score": float(candidate.get("quality_score", 0.0)),
            "quality_reason": candidate.get("quality_reason", ""),
            "identity_confidence": float(candidate.get("identity_confidence", 0.0)),
            "content_match_status": candidate.get("content_match_status", ""),
            "needs_human_review": bool(candidate.get("needs_human_review", False)),
            "source_adapter": candidate.get("source_adapter", ""),
            "reject_reason": "",
        }
