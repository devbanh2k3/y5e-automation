"""Image sourcing agent — searches free image APIs in waterfall order."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
from PIL import Image

from agents.base_agent import BaseAgent
from core import database as db
from core.config import get_settings
from core.storage import get_asset_path

logger = logging.getLogger(__name__)

# Target dimensions for card images
TARGET_WIDTH = 640
TARGET_HEIGHT = 400

# Wikimedia license whitelist (case-insensitive substrings)
_ALLOWED_LICENSES: set[str] = {
    "cc0",
    "public domain",
    "cc-by-",
    "cc-by-sa-",
    "creative commons attribution",
    "creative commons attribution-sharealike",
}

# HTTP timeout for image search and download
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


class ImageAgent(BaseAgent):
    """Finds, downloads, and processes images for each script section.

    Uses a waterfall strategy across Wikimedia Commons, Unsplash, Pexels,
    and Pixabay — falling through to the next provider when one fails.
    """

    def __init__(self) -> None:
        super().__init__(name="image_agent")
        self._settings = get_settings()

    # ── Public entry point ────────────────────────────────────

    async def run(self, topic_id: int) -> list[dict[str, Any]]:  # type: ignore[override]
        """Fetch images for every script section of the given topic.

        Args:
            topic_id: The topic whose script sections need images.

        Returns:
            A list of dicts, each containing ``section_index``,
            ``file_path``, ``source``, and ``license``.
        """
        await self.log(topic_id, "running")

        try:
            sections = await self._load_sections(topic_id)
            if not sections:
                raise ValueError(f"No script sections found for topic {topic_id}")

            results: list[dict[str, Any]] = []

            async with httpx.AsyncClient(
                timeout=_HTTP_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "YouTubeAIBot/1.0"},
            ) as client:
                for idx, section in enumerate(sections):
                    query: str = section.get("image_query", "")
                    if not query:
                        self.logger.warning(
                            "Section %d has no image_query — skipping", idx
                        )
                        continue

                    result = await self._process_section(
                        client=client,
                        topic_id=topic_id,
                        section_index=idx,
                        query=query,
                    )
                    if result is not None:
                        results.append(result)

            await self.log(topic_id, "completed")
            await self.notify(
                f"✅ Images ready for topic <b>{topic_id}</b> — "
                f"{len(results)}/{len(sections)} sections covered."
            )
            return results

        except Exception as exc:
            await self.log(topic_id, "failed", error=str(exc))
            raise

    # ── Section processing ────────────────────────────────────

    async def _process_section(
        self,
        client: httpx.AsyncClient,
        topic_id: int,
        section_index: int,
        query: str,
    ) -> dict[str, Any] | None:
        """Search, download, process, and store an image for one section.

        Returns:
            A result dict or ``None`` if every source failed.
        """
        # Waterfall: try each source in order
        sources = [
            ("wikimedia", self._search_wikimedia),
            ("unsplash", self._search_unsplash),
            ("pexels", self._search_pexels),
            ("pixabay", self._search_pixabay),
        ]

        for source_name, search_fn in sources:
            try:
                hit = await search_fn(client, query)
                if hit is None:
                    continue

                image_url: str = hit["url"]
                license_type: str = hit.get("license", "unknown")

                # Download
                raw_bytes = await self._download_image(client, image_url)
                if raw_bytes is None:
                    continue

                # Process with PIL
                filename = f"section_{section_index}.webp"
                out_path = get_asset_path(topic_id, f"images/{filename}")
                self._process_image(raw_bytes, out_path)

                # Persist asset record
                await self.save_asset(
                    topic_id=topic_id,
                    asset_type="image",
                    file_path=str(out_path),
                    source_url=image_url,
                    license_type=license_type,
                    section_index=section_index,
                    source=source_name,
                    query=query,
                )

                self.logger.info(
                    "Section %d: got image from %s (%s)",
                    section_index,
                    source_name,
                    license_type,
                )
                return {
                    "section_index": section_index,
                    "file_path": str(out_path),
                    "source": source_name,
                    "license": license_type,
                }

            except Exception:
                self.logger.exception(
                    "Section %d: %s search/download failed — trying next",
                    section_index,
                    source_name,
                )
                continue

        self.logger.warning(
            "Section %d: all image sources exhausted for query '%s'",
            section_index,
            query,
        )
        return None

    # ── Image search providers ────────────────────────────────

    async def _search_wikimedia(
        self, client: httpx.AsyncClient, query: str
    ) -> dict[str, str] | None:
        """Search Wikimedia Commons for a freely-licensed image.

        Args:
            client: Shared HTTP client.
            query: Search keywords.

        Returns:
            ``{"url": ..., "license": ...}`` or ``None``.
        """
        url = (
            "https://commons.wikimedia.org/w/api.php"
            f"?action=query&generator=search"
            f"&gsrsearch={quote_plus(query)}"
            f"&gsrnamespace=6"
            f"&gsrlimit=10"
            f"&prop=imageinfo"
            f"&iiprop=url|extmetadata"
            f"&format=json"
        )

        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        pages: dict[str, Any] = data.get("query", {}).get("pages", {})
        for page in pages.values():
            image_info_list = page.get("imageinfo")
            if not image_info_list:
                continue

            info = image_info_list[0]
            image_url: str = info.get("url", "")
            if not image_url:
                continue

            # Check license from extmetadata
            ext = info.get("extmetadata", {})
            license_short: str = ext.get("LicenseShortName", {}).get("value", "")
            license_url_val: str = ext.get("LicenseUrl", {}).get("value", "")
            combined = f"{license_short} {license_url_val}".lower()

            if any(allowed in combined for allowed in _ALLOWED_LICENSES):
                # Skip SVG and very small images
                if image_url.lower().endswith(".svg"):
                    continue
                return {"url": image_url, "license": license_short or "Wikimedia"}

        return None

    async def _search_unsplash(
        self, client: httpx.AsyncClient, query: str
    ) -> dict[str, str] | None:
        """Search Unsplash for a photo.

        Args:
            client: Shared HTTP client.
            query: Search keywords.

        Returns:
            ``{"url": ..., "license": ...}`` or ``None``.
        """
        api_key = self._settings.unsplash_api_key if hasattr(self._settings, "unsplash_api_key") else ""
        if not api_key:
            return None

        resp = await client.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 5, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return None

        # Pick the first result
        photo = results[0]
        image_url = photo.get("urls", {}).get("regular", "")
        if not image_url:
            return None

        return {"url": image_url, "license": "Unsplash"}

    async def _search_pexels(
        self, client: httpx.AsyncClient, query: str
    ) -> dict[str, str] | None:
        """Search Pexels for a photo.

        Args:
            client: Shared HTTP client.
            query: Search keywords.

        Returns:
            ``{"url": ..., "license": ...}`` or ``None``.
        """
        api_key = self._settings.pexels_api_key if hasattr(self._settings, "pexels_api_key") else ""
        if not api_key:
            return None

        resp = await client.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 5, "orientation": "landscape"},
            headers={"Authorization": api_key},
        )
        resp.raise_for_status()
        data = resp.json()

        photos = data.get("photos", [])
        if not photos:
            return None

        image_url = photos[0].get("src", {}).get("large", "")
        if not image_url:
            return None

        return {"url": image_url, "license": "Pexels"}

    async def _search_pixabay(
        self, client: httpx.AsyncClient, query: str
    ) -> dict[str, str] | None:
        """Search Pixabay for a photo.

        Args:
            client: Shared HTTP client.
            query: Search keywords.

        Returns:
            ``{"url": ..., "license": ...}`` or ``None``.
        """
        api_key = self._settings.pixabay_api_key if hasattr(self._settings, "pixabay_api_key") else ""
        if not api_key:
            return None

        resp = await client.get(
            "https://pixabay.com/api/",
            params={
                "key": api_key,
                "q": query,
                "image_type": "photo",
                "per_page": 5,
                "orientation": "horizontal",
                "safesearch": "true",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", [])
        if not hits:
            return None

        image_url = hits[0].get("largeImageURL", "")
        if not image_url:
            return None

        return {"url": image_url, "license": "Pixabay"}

    # ── Download & process ────────────────────────────────────

    async def _download_image(
        self, client: httpx.AsyncClient, url: str
    ) -> bytes | None:
        """Download an image and return raw bytes.

        Args:
            client: Shared HTTP client.
            url: Image URL.

        Returns:
            Raw image bytes, or ``None`` on failure.
        """
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "image" not in content_type and "octet-stream" not in content_type:
                self.logger.warning("Unexpected content-type '%s' for %s", content_type, url)
                # Still try — some servers set wrong content-type
            return resp.content
        except httpx.HTTPError:
            self.logger.exception("Failed to download image: %s", url)
            return None

    @staticmethod
    def _process_image(raw_bytes: bytes, output_path: Path) -> None:
        """Resize and crop an image to the target card dimensions.

        The image is centre-cropped to fill 640×400 and saved as WebP
        at quality 90.

        Args:
            raw_bytes: Raw image data.
            output_path: Destination file path.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(BytesIO(raw_bytes)) as img:
            # Convert to RGB if necessary (handles RGBA, P, L, etc.)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            elif img.mode == "RGBA":
                # Composite onto white background
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background

            # Centre-crop to target aspect ratio, then resize
            src_w, src_h = img.size
            target_ratio = TARGET_WIDTH / TARGET_HEIGHT
            src_ratio = src_w / src_h

            if src_ratio > target_ratio:
                # Source is wider — crop horizontally
                new_w = int(src_h * target_ratio)
                offset = (src_w - new_w) // 2
                img = img.crop((offset, 0, offset + new_w, src_h))
            elif src_ratio < target_ratio:
                # Source is taller — crop vertically
                new_h = int(src_w / target_ratio)
                offset = (src_h - new_h) // 2
                img = img.crop((0, offset, src_w, offset + new_h))

            img = img.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.LANCZOS)
            img.save(str(output_path), format="WEBP", quality=90, method=6)

    # ── DB helpers ────────────────────────────────────────────

    @staticmethod
    async def _load_sections(topic_id: int) -> list[dict[str, Any]]:
        """Load script sections from the database.

        Args:
            topic_id: The topic ID.

        Returns:
            A list of section dicts parsed from the ``scripts.sections``
            JSONB column.
        """
        import json as _json

        row = await db.fetchrow(
            "SELECT sections FROM scripts WHERE topic_id = $1 ORDER BY id DESC LIMIT 1",
            topic_id,
        )
        if row is None:
            return []

        sections_raw = row["sections"]
        if isinstance(sections_raw, str):
            return _json.loads(sections_raw)  # type: ignore[no-any-return]
        if isinstance(sections_raw, list):
            return sections_raw  # type: ignore[return-value]
        return []
