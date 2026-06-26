"""
Professional Image Search & Download Module
Primary: DuckDuckGo Image Search (no API key, search-based)
Fallback: Unsplash → Pexels → Pixabay → Picsum

Features:
- Search-based results (ảnh đúng chủ đề)
- Automatic retry on failed downloads
- PIL validation + smart resize (object-fit: cover)
- Rate limiting between requests
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

log = logging.getLogger("image_search")

# ── Config ──────────────────────────────────────────────────

UNSPLASH_KEY = os.getenv("UNSPLASH_API_KEY", "")
PEXELS_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")

MIN_IMAGE_BYTES = 10_000      # Reject files < 10KB
MIN_SOURCE_DIM = 200           # Reject images smaller than 200x200
TARGET_WIDTH = 640             # Resize to this width
TARGET_HEIGHT = 400            # Resize to this height
JPEG_QUALITY = 90

# Domains that return irrelevant images (tourism, social, stock previews)
BLACKLISTED_DOMAINS = {
    "tripadvisor.com", "booking.com", "airbnb.com",
    "pinterest.com", "pinterest.co", "pinimg.com",
    "facebook.com", "instagram.com", "twitter.com",
    "tiktok.com", "linkedin.com",
    "aliexpress.com", "amazon.com", "ebay.com",
    "etsy.com", "wish.com", "shopee.com",
    "getty.com", "gettyimages.com",  # watermarked
    "yelp.com", "foursquare.com",
    "maps.google.com", "google.com/maps",
}

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


# ── Main Public API ─────────────────────────────────────────

async def search_and_download(
    query: str,
    save_path: Path,
    timeout: float = 15.0,
) -> dict:
    """
    Search for a real photo matching `query` and save it.
    Returns: {source, url, path, width, height, size_kb, success}
    """
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": BROWSER_UA},
    ) as client:

        # ── Source 1: DuckDuckGo (best: search-based, no key) ──
        try:
            urls = _search_ddg(query)
            for url in urls[:5]:
                result = await _download_and_validate(client, url, save_path, "DDG")
                if result:
                    return result
        except Exception as e:
            log.debug(f"  DDG failed: {e}")

        # ── Source 2: Unsplash API (if key available) ──
        if UNSPLASH_KEY and UNSPLASH_KEY != "CHANGE_ME":
            try:
                urls = await _search_unsplash(client, query)
                for url in urls[:3]:
                    result = await _download_and_validate(client, url, save_path, "Unsplash")
                    if result:
                        return result
            except Exception as e:
                log.debug(f"  Unsplash failed: {e}")

        # ── Source 3: Pexels API (if key available) ──
        if PEXELS_KEY and PEXELS_KEY != "CHANGE_ME":
            try:
                urls = await _search_pexels(client, query)
                for url in urls[:3]:
                    result = await _download_and_validate(client, url, save_path, "Pexels")
                    if result:
                        return result
            except Exception as e:
                log.debug(f"  Pexels failed: {e}")

        # ── Source 4: Pixabay API (if key available) ──
        if PIXABAY_KEY and PIXABAY_KEY != "CHANGE_ME":
            try:
                urls = await _search_pixabay(client, query)
                for url in urls[:3]:
                    result = await _download_and_validate(client, url, save_path, "Pixabay")
                    if result:
                        return result
            except Exception as e:
                log.debug(f"  Pixabay failed: {e}")

        # ── Source 5: Picsum (random HD, always works) ──
        try:
            result = await _download_picsum(client, query, save_path)
            if result:
                return result
        except Exception as e:
            log.debug(f"  Picsum failed: {e}")

    # Last resort
    return _create_styled_placeholder(save_path, query)


async def download_all_images(
    sections: list[dict],
    output_dir: Path,
    delay: float = 1.0,
) -> list[dict]:
    """
    Download images for all sections.
    Tries primary query first, then alt queries as fallback.
    Returns list of result dicts.
    """
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    results = []
    total = len(sections)

    for i, section in enumerate(sections):
        queries = [
            section.get("image_query", section.get("title", f"section {i}")),
        ]
        if section.get("image_query_alt1"):
            queries.append(section["image_query_alt1"])
        if section.get("image_query_alt2"):
            queries.append(section["image_query_alt2"])

        file_path = images_dir / f"section_{i}.jpg"
        result = None

        for qi, query in enumerate(queries):
            label = f"[{i+1}/{total}]" if qi == 0 else f"[{i+1}/{total} alt{qi}]"
            log.info(f"  {label} Searching: {query[:50]}...")

            result = await search_and_download(query, file_path)
            result["index"] = i
            result["query"] = query

            if result.get("success"):
                log.info(
                    f"  ✅ {label} {result['source']:8s} "
                    f"| {result.get('size_kb', 0):5.1f}KB | {query[:40]}"
                )
                break
            else:
                if qi < len(queries) - 1:
                    log.info(f"  🔄 {label} No good result, trying alt query...")

        if not result or not result.get("success"):
            log.warning(f"  ⚠️  [{i+1}/{total}] Placeholder after {len(queries)} queries")

        results.append(result)

        if i < total - 1:
            await asyncio.sleep(delay)

    success_count = sum(1 for r in results if r.get("success"))
    log.info(f"  📊 Images: {success_count}/{total} real photos downloaded")

    return results


# ── Source 1: DuckDuckGo (synchronous, no key) ──────────────

def _search_ddg(query: str) -> list[str]:
    """
    Search DuckDuckGo Images — returns list of direct image URLs.
    Uses ddgs package (synchronous). No API key needed.
    Filters out blacklisted domains.
    """
    from ddgs import DDGS

    simple = _simplify_query(query)

    with DDGS() as ddgs:
        results = list(ddgs.images(simple, max_results=15))

    urls = []
    for r in results:
        url = r.get("image", "")
        if not url:
            continue
        # Filter out blacklisted domains
        if _is_blacklisted(url):
            log.debug(f"  ⛔ Blacklisted: {url[:60]}")
            continue
        urls.append(url)

    return urls[:10]  # Return up to 10 filtered URLs


def _is_blacklisted(url: str) -> bool:
    """Check if URL belongs to a blacklisted domain."""
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
        return any(domain in host for domain in BLACKLISTED_DOMAINS)
    except Exception:
        return False


# ── Source 2: Unsplash API ──────────────────────────────────

async def _search_unsplash(client: httpx.AsyncClient, query: str) -> list[str]:
    resp = await client.get(
        "https://api.unsplash.com/search/photos",
        params={
            "query": _simplify_query(query),
            "per_page": "5",
            "orientation": "landscape",
        },
        headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"},
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [r["urls"]["regular"] for r in data.get("results", []) if "urls" in r]


# ── Source 3: Pexels API ────────────────────────────────────

async def _search_pexels(client: httpx.AsyncClient, query: str) -> list[str]:
    resp = await client.get(
        "https://api.pexels.com/v1/search",
        params={
            "query": _simplify_query(query),
            "per_page": "5",
            "orientation": "landscape",
        },
        headers={"Authorization": PEXELS_KEY},
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [p["src"]["large"] for p in data.get("photos", []) if "src" in p]


# ── Source 4: Pixabay API ───────────────────────────────────

async def _search_pixabay(client: httpx.AsyncClient, query: str) -> list[str]:
    resp = await client.get(
        "https://pixabay.com/api/",
        params={
            "key": PIXABAY_KEY,
            "q": _simplify_query(query),
            "image_type": "photo",
            "orientation": "horizontal",
            "per_page": "5",
            "safesearch": "true",
        },
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return [
        h.get("largeImageURL") or h.get("webformatURL")
        for h in data.get("hits", [])
        if h.get("largeImageURL") or h.get("webformatURL")
    ]


# ── Source 5: Picsum (random HD, seeded) ────────────────────

async def _download_picsum(
    client: httpx.AsyncClient, query: str, save_path: Path,
) -> dict | None:
    """Download a seeded random HD photo from Lorem Picsum."""
    seed = hashlib.md5(query.encode()).hexdigest()[:12]
    url = f"https://picsum.photos/seed/{seed}/{TARGET_WIDTH}/{TARGET_HEIGHT}"

    resp = await client.get(url)
    if resp.status_code != 200 or len(resp.content) < MIN_IMAGE_BYTES:
        return None

    save_path.write_bytes(resp.content)
    try:
        img = Image.open(save_path)
        img.verify()
        return {
            "success": True,
            "source": "Picsum",
            "url": url,
            "path": str(save_path),
            "width": TARGET_WIDTH,
            "height": TARGET_HEIGHT,
            "size_kb": round(save_path.stat().st_size / 1024, 1),
        }
    except Exception:
        return None


# ── Download & Validate ─────────────────────────────────────

async def _download_and_validate(
    client: httpx.AsyncClient,
    url: str,
    save_path: Path,
    source: str,
) -> dict | None:
    """Download image, validate, resize to target dimensions."""
    try:
        resp = await client.get(url)
    except Exception:
        return None

    if resp.status_code != 200:
        return None

    raw_bytes = resp.content

    if len(raw_bytes) < MIN_IMAGE_BYTES:
        return None

    content_type = resp.headers.get("content-type", "")
    if content_type and "html" in content_type:
        return None

    temp_path = save_path.with_suffix(".tmp")
    temp_path.write_bytes(raw_bytes)

    try:
        img = Image.open(temp_path)
        img.verify()

        img = Image.open(temp_path)
        orig_w, orig_h = img.size

        # Reject tiny images (icons, thumbnails, avatars)
        if orig_w < MIN_SOURCE_DIM or orig_h < MIN_SOURCE_DIM:
            log.debug(f"  ⛔ Too small: {orig_w}x{orig_h} < {MIN_SOURCE_DIM}")
            if temp_path.exists():
                temp_path.unlink()
            return None

        # Reject extreme aspect ratios (banners, strips)
        aspect = orig_w / max(orig_h, 1)
        if aspect > 4.0 or aspect < 0.2:
            log.debug(f"  ⛔ Extreme aspect ratio: {aspect:.1f}")
            if temp_path.exists():
                temp_path.unlink()
            return None

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        img = _smart_resize(img, TARGET_WIDTH, TARGET_HEIGHT)
        img.save(save_path, "JPEG", quality=JPEG_QUALITY, optimize=True)

        width, height = img.size
        img.close()

        if temp_path.exists():
            temp_path.unlink()

        return {
            "success": True,
            "source": source,
            "url": url,
            "path": str(save_path),
            "width": width,
            "height": height,
            "size_kb": round(save_path.stat().st_size / 1024, 1),
        }

    except Exception as e:
        log.debug(f"  Validation failed: {e}")
        if temp_path.exists():
            temp_path.unlink()
        return None


def _smart_resize(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Crop to aspect ratio then resize (CSS object-fit: cover)."""
    orig_w, orig_h = img.size
    target_ratio = target_w / target_h
    orig_ratio = orig_w / orig_h

    if orig_ratio > target_ratio:
        new_w = int(orig_h * target_ratio)
        offset = (orig_w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, orig_h))
    else:
        new_h = int(orig_w / target_ratio)
        offset = (orig_h - new_h) // 2
        img = img.crop((0, offset, orig_w, offset + new_h))

    return img.resize((target_w, target_h), Image.Resampling.LANCZOS)


# ── Styled Placeholder ──────────────────────────────────────

def _create_styled_placeholder(save_path: Path, text: str) -> dict:
    """Create a professional dark placeholder."""
    from PIL import ImageDraw

    img = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), color=(18, 18, 24))
    draw = ImageDraw.Draw(img)

    for y in range(0, TARGET_HEIGHT, 2):
        shade = int(18 + (y / TARGET_HEIGHT) * 15)
        draw.line([(0, y), (TARGET_WIDTH, y)], fill=(shade, shade, shade + 8))

    draw.rectangle([0, TARGET_HEIGHT - 6, TARGET_WIDTH, TARGET_HEIGHT], fill=(229, 45, 39))
    draw.rectangle([0, 0, TARGET_WIDTH, 3], fill=(229, 45, 39))

    for x in range(40, TARGET_WIDTH, 80):
        for y in range(40, TARGET_HEIGHT, 80):
            draw.ellipse([x-1, y-1, x+1, y+1], fill=(40, 40, 50))

    img.save(save_path, "JPEG", quality=JPEG_QUALITY)

    return {
        "success": False,
        "source": "placeholder",
        "url": "",
        "path": str(save_path),
        "width": TARGET_WIDTH,
        "height": TARGET_HEIGHT,
        "size_kb": round(save_path.stat().st_size / 1024, 1),
    }


# ── Helpers ─────────────────────────────────────────────────

def _simplify_query(query: str) -> str:
    """Simplify AI-generated queries for better search results."""
    q = query.split(",")[0].strip()

    stop_words = {
        "with", "and", "the", "a", "an", "of", "in", "on", "at", "to",
        "for", "is", "are", "was", "were", "no", "not", "very", "few",
        "showing", "depicting", "featuring", "looking", "like",
    }
    words = q.split()
    filtered = [w for w in words if w.lower() not in stop_words]

    result = " ".join(filtered[:5])
    return result if result else query[:50]
