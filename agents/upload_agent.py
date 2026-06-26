"""Upload agent — publishes rendered videos to YouTube via Data API v3.

Handles OAuth2 token management, resumable video upload, thumbnail upload,
AI-generated SEO metadata with chapter timestamps, and Telegram notifications.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from agents.base_agent import BaseAgent
from core.config import get_settings
from core import database as db

logger = logging.getLogger(__name__)

# ── YouTube API constants ────────────────────────────────────

_YT_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_YT_THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Resumable upload chunk size: 5 MiB (must be multiple of 256 KiB)
_CHUNK_SIZE = 5 * 1024 * 1024

# Timing constants for chapter calculation (matching Remotion render)
_INTRO_SECONDS = 3       # 90 frames @ 30fps
_HOLD_SECONDS = 4        # 120 frames @ 30fps
_TRANSITION_SECONDS = 0.5  # 15 frames @ 30fps


class UploadError(Exception):
    """Raised when a YouTube upload operation fails."""


class UploadAgent(BaseAgent):
    """Uploads rendered videos to YouTube with SEO-optimised metadata.

    Workflow:
        1. Fetch video, topic, script, and thumbnail data from the database.
        2. Generate SEO metadata (title, description, tags) via AI.
        3. Calculate chapter timestamps from script sections.
        4. Upload video using YouTube resumable upload protocol.
        5. Upload custom thumbnail.
        6. Update the ``videos`` table with the YouTube ID.
        7. Send a Telegram success notification.
    """

    def __init__(self) -> None:
        super().__init__(name="upload_agent")

    # ── Public entry point ───────────────────────────────────

    async def run(self, video_id: int) -> dict[str, Any]:
        """Upload a rendered video to YouTube.

        Args:
            video_id: Primary key of the ``videos`` row to upload.

        Returns:
            A dict with ``youtube_id``, ``title``, and ``url`` keys.

        Raises:
            UploadError: If any step of the upload process fails.
        """
        await self.log(None, "running")

        try:
            # ── Step 1: Fetch all required data ──────────────
            video = await db.fetchrow(
                "SELECT * FROM videos WHERE id = $1", video_id
            )
            if not video:
                raise UploadError(f"Video row {video_id} not found in database")

            topic_id: int = video["topic_id"]

            topic = await db.fetchrow(
                "SELECT * FROM topics WHERE id = $1", topic_id
            )
            if not topic:
                raise UploadError(f"Topic {topic_id} not found for video {video_id}")

            script = await db.fetchrow(
                "SELECT * FROM scripts WHERE topic_id = $1 ORDER BY created_at DESC LIMIT 1",
                topic_id,
            )
            if not script:
                raise UploadError(f"No script found for topic {topic_id}")

            thumbnail_asset = await db.fetchrow(
                "SELECT * FROM assets WHERE topic_id = $1 AND asset_type = 'thumbnail' "
                "ORDER BY created_at DESC LIMIT 1",
                topic_id,
            )

            video_file = Path(video["file_path"])
            if not video_file.exists():
                raise UploadError(f"Video file not found: {video_file}")

            # ── Step 2: Parse sections & generate timestamps ─
            sections: list[dict[str, Any]] = (
                json.loads(script["sections"])
                if isinstance(script["sections"], str)
                else script["sections"]
            )

            timestamps = self._calculate_timestamps(sections)
            timestamp_text = self._format_timestamps(timestamps)

            # ── Step 3: Generate SEO metadata via AI ─────────
            section_headers = [s.get("header", s.get("title", "")) for s in sections]
            seo_metadata = await self._generate_seo_metadata(
                topic_title=topic["title"],
                category=topic["category"],
                language=topic.get("language", "vi"),
                section_headers=section_headers,
                timestamp_text=timestamp_text,
            )

            # Inject timestamps into description
            description = seo_metadata["description"]
            if timestamp_text and timestamp_text not in description:
                description = f"{description}\n\n📑 Chapters:\n{timestamp_text}"

            title = seo_metadata["title"][:100]
            tags = seo_metadata.get("tags", [])[:15]
            category_id = str(seo_metadata.get("category_id", 22))

            # ── Step 4: Upload video (resumable) ─────────────
            access_token = await self._get_access_token()

            youtube_id = await self._upload_video(
                access_token=access_token,
                video_path=video_file,
                title=title,
                description=description,
                tags=tags,
                category_id=category_id,
                language=topic.get("language", "vi"),
            )

            # ── Step 5: Upload thumbnail ─────────────────────
            if thumbnail_asset and thumbnail_asset["file_path"]:
                thumbnail_path = Path(thumbnail_asset["file_path"])
                if thumbnail_path.exists():
                    await self._upload_thumbnail(
                        access_token=access_token,
                        youtube_id=youtube_id,
                        thumbnail_path=thumbnail_path,
                    )
                else:
                    self.logger.warning(
                        "Thumbnail file not found at %s, skipping upload",
                        thumbnail_path,
                    )

            # ── Step 6: Update database ──────────────────────
            published_at = datetime.now(timezone.utc)
            await db.execute(
                "UPDATE videos SET youtube_id = $1, status = 'published', published_at = $2 "
                "WHERE id = $3",
                youtube_id,
                published_at,
                video_id,
            )
            await db.execute(
                "UPDATE topics SET status = 'published' WHERE id = $1",
                topic_id,
            )

            # ── Step 7: Notify ───────────────────────────────
            video_url = f"https://youtube.com/watch?v={youtube_id}"
            await self.notify(
                f"✅ Video '<b>{title}</b>' uploaded!\n"
                f"🔗 {video_url}"
            )

            await self.log(topic_id, "completed")

            return {
                "youtube_id": youtube_id,
                "title": title,
                "url": video_url,
            }

        except Exception as exc:
            error_msg = f"Upload failed for video {video_id}: {exc}"
            self.logger.error(error_msg, exc_info=True)
            await self.log(None, "failed", error=str(exc)[:500])
            await self.notify(f"❌ Upload failed: {exc}")
            raise UploadError(error_msg) from exc

    # ── Chapter timestamp calculation ────────────────────────

    @staticmethod
    def _calculate_timestamps(
        sections: list[dict[str, Any]],
    ) -> list[tuple[float, str]]:
        """Calculate chapter timestamps from script sections.

        Uses fixed timing that matches the Remotion video render:
        - Intro: 3 seconds (90 frames at 30fps)
        - Each section hold: 4 seconds (120 frames at 30fps)
        - Transition between sections: 0.5 seconds (15 frames at 30fps)

        Args:
            sections: List of script section dicts with ``header`` keys.

        Returns:
            List of ``(seconds, header)`` tuples.
        """
        timestamps: list[tuple[float, str]] = [(0.0, "Giới thiệu")]
        current = float(_INTRO_SECONDS)

        for section in sections:
            header = section.get("header", section.get("title", "Section"))
            timestamps.append((current, header))
            current += _HOLD_SECONDS + _TRANSITION_SECONDS

        return timestamps

    @staticmethod
    def _format_timestamps(timestamps: list[tuple[float, str]]) -> str:
        """Format timestamps into YouTube chapter format.

        Args:
            timestamps: List of ``(seconds, header)`` tuples.

        Returns:
            Multi-line string like ``00:00 - Giới thiệu\\n00:03 - Section 1``.
        """
        lines: list[str] = []
        for seconds, header in timestamps:
            total_secs = int(seconds)
            minutes = total_secs // 60
            secs = total_secs % 60
            lines.append(f"{minutes:02d}:{secs:02d} - {header}")
        return "\n".join(lines)

    # ── AI SEO metadata generation ───────────────────────────

    async def _generate_seo_metadata(
        self,
        topic_title: str,
        category: str,
        language: str,
        section_headers: list[str],
        timestamp_text: str,
    ) -> dict[str, Any]:
        """Generate YouTube SEO metadata using AI.

        Args:
            topic_title: The topic title.
            category: Content category.
            language: Target language code.
            section_headers: List of script section headers.
            timestamp_text: Pre-formatted chapter timestamps.

        Returns:
            A dict with ``title``, ``description``, ``tags``, and
            ``category_id`` keys.
        """
        headers_str = "\n".join(f"  - {h}" for h in section_headers)

        prompt = f"""Generate YouTube SEO metadata for this video:
Title: {topic_title}
Category: {category}
Language: {language}
Sections:
{headers_str}

Chapter Timestamps:
{timestamp_text}

Return JSON with exactly these keys:
- title: SEO-optimized title with primary keyword in first 60 chars, max 100 chars total. \
Must be compelling and click-worthy.
- description: 200-500 words with:
  - Lines 1-2: compelling hook that makes viewers want to watch
  - The chapter timestamps provided above
  - Source references and credits
  - Subscribe CTA (call to action) with emoji
  - 3-5 relevant hashtags at the end
- tags: array of 10-15 tags ordered from broad to narrow to competitor terms. \
Mix of single words and multi-word phrases.
- category_id: YouTube category ID number (integer). Common ones: \
22=People & Blogs, 27=Education, 28=Science & Technology, 24=Entertainment, 25=News & Politics

Return ONLY valid JSON, no markdown fences."""

        system = (
            "You are a YouTube SEO expert who specialises in creating metadata that "
            "maximises click-through rate and discoverability. Always return valid JSON."
        )

        result = await self.ai_json(prompt, system=system)

        # Validate required keys with sensible defaults
        if "title" not in result or not result["title"]:
            result["title"] = topic_title[:100]
        if "description" not in result or not result["description"]:
            result["description"] = f"{topic_title}\n\n{timestamp_text}"
        if "tags" not in result or not isinstance(result["tags"], list):
            result["tags"] = [category, topic_title]
        if "category_id" not in result:
            result["category_id"] = 22  # People & Blogs (safe default)

        return result

    # ── OAuth2 token management ──────────────────────────────

    async def _get_access_token(self) -> str:
        """Read the OAuth2 access token, refreshing it if expired.

        The token file is stored at ``<storage_path>/youtube_token.json``
        and must contain: ``access_token``, ``refresh_token``,
        ``client_id``, ``client_secret``, and ``expires_at`` (epoch).

        Returns:
            A valid access token string.

        Raises:
            UploadError: If the token file is missing or refresh fails.
        """
        settings = get_settings()
        token_path = Path(settings.storage_path) / "youtube_token.json"

        if not token_path.exists():
            raise UploadError(
                f"YouTube token file not found at {token_path}. "
                "Run the OAuth2 setup flow first to generate youtube_token.json."
            )

        token_data = json.loads(token_path.read_text(encoding="utf-8"))

        required_keys = {"access_token", "refresh_token", "client_id", "client_secret"}
        missing = required_keys - set(token_data.keys())
        if missing:
            raise UploadError(
                f"Token file missing required keys: {missing}. "
                "Re-run OAuth2 setup to generate a complete token file."
            )

        # Check if token has expired (with 5-minute buffer)
        expires_at = token_data.get("expires_at", 0)
        if time.time() >= (expires_at - 300):
            self.logger.info("Access token expired or near expiry, refreshing…")
            token_data = await self._refresh_access_token(token_data, token_path)

        return token_data["access_token"]

    async def _refresh_access_token(
        self,
        token_data: dict[str, Any],
        token_path: Path,
    ) -> dict[str, Any]:
        """Refresh an expired OAuth2 access token.

        Args:
            token_data: Current token data dict.
            token_path: Path to the token JSON file for persistence.

        Returns:
            Updated token data dict with a fresh access token.

        Raises:
            UploadError: If the refresh request fails.
        """
        payload = {
            "client_id": token_data["client_id"],
            "client_secret": token_data["client_secret"],
            "refresh_token": token_data["refresh_token"],
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_GOOGLE_TOKEN_URL, data=payload)

            if resp.status_code != 200:
                error_body = resp.text
                raise UploadError(
                    f"Token refresh failed (HTTP {resp.status_code}): {error_body}"
                )

            refresh_result = resp.json()

        token_data["access_token"] = refresh_result["access_token"]
        token_data["expires_at"] = int(time.time()) + refresh_result.get(
            "expires_in", 3600
        )

        # Persist updated token
        token_path.write_text(
            json.dumps(token_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.logger.info("Access token refreshed and saved to %s", token_path)

        return token_data

    # ── Resumable video upload ───────────────────────────────

    async def _upload_video(
        self,
        access_token: str,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
        language: str = "vi",
    ) -> str:
        """Upload a video file using the YouTube resumable upload protocol.

        Steps:
            1. Initiate a resumable upload session and get the upload URI.
            2. Send the video file in chunks.
            3. Extract the YouTube video ID from the final response.

        Args:
            access_token: Valid OAuth2 access token.
            video_path: Path to the video file.
            title: Video title.
            description: Video description.
            tags: List of video tags.
            category_id: YouTube category ID.
            language: Default language code.

        Returns:
            The YouTube video ID string.

        Raises:
            UploadError: If the upload fails at any stage.
        """
        file_size = video_path.stat().st_size
        self.logger.info(
            "Starting upload: %s (%.1f MiB)", video_path.name, file_size / (1024 * 1024)
        )

        # Build the video resource body
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
                "defaultLanguage": language,
                "defaultAudioLanguage": language,
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        # Step 1: Initiate resumable upload session
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": "video/*",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            init_resp = await client.post(
                f"{_YT_UPLOAD_URL}?uploadType=resumable&part=snippet,status",
                headers=headers,
                content=json.dumps(body),
            )

            if init_resp.status_code not in (200, 308):
                raise UploadError(
                    f"Resumable upload initiation failed "
                    f"(HTTP {init_resp.status_code}): {init_resp.text}"
                )

            upload_uri = init_resp.headers.get("location")
            if not upload_uri:
                raise UploadError(
                    "No upload URI returned in resumable upload initiation response"
                )

            self.logger.info("Upload URI obtained, sending video data…")

            # Step 2: Upload the file in chunks
            youtube_id = await self._send_chunks(
                client=client,
                upload_uri=upload_uri,
                video_path=video_path,
                file_size=file_size,
                access_token=access_token,
            )

        self.logger.info("Video uploaded successfully: youtube_id=%s", youtube_id)
        return youtube_id

    async def _send_chunks(
        self,
        client: httpx.AsyncClient,
        upload_uri: str,
        video_path: Path,
        file_size: int,
        access_token: str,
    ) -> str:
        """Send video data in chunks via the resumable upload URI.

        Args:
            client: Active httpx async client.
            upload_uri: The resumable upload URI.
            video_path: Path to the video file.
            file_size: Total file size in bytes.
            access_token: OAuth2 access token.

        Returns:
            The YouTube video ID extracted from the final response.

        Raises:
            UploadError: If any chunk upload fails.
        """
        bytes_sent = 0
        max_retries_per_chunk = 3

        with open(video_path, "rb") as fh:
            while bytes_sent < file_size:
                chunk = fh.read(_CHUNK_SIZE)
                chunk_len = len(chunk)
                range_end = bytes_sent + chunk_len - 1

                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Length": str(chunk_len),
                    "Content-Range": f"bytes {bytes_sent}-{range_end}/{file_size}",
                    "Content-Type": "video/*",
                }

                # Retry logic for individual chunks
                last_error: Exception | None = None
                for attempt in range(max_retries_per_chunk):
                    try:
                        resp = await client.put(
                            upload_uri,
                            headers=headers,
                            content=chunk,
                            timeout=300.0,  # 5 minutes per chunk
                        )

                        if resp.status_code in (200, 201):
                            # Final chunk — upload complete
                            result = resp.json()
                            youtube_id = result.get("id", "")
                            if not youtube_id:
                                raise UploadError(
                                    "Upload completed but no video ID in response"
                                )
                            return youtube_id

                        if resp.status_code == 308:
                            # Chunk accepted, continue
                            bytes_sent += chunk_len
                            progress = (bytes_sent / file_size) * 100
                            self.logger.info(
                                "Upload progress: %.1f%% (%d / %d bytes)",
                                progress, bytes_sent, file_size,
                            )
                            last_error = None
                            break

                        raise UploadError(
                            f"Chunk upload failed (HTTP {resp.status_code}): "
                            f"{resp.text[:500]}"
                        )

                    except httpx.HTTPError as exc:
                        last_error = exc
                        self.logger.warning(
                            "Chunk upload attempt %d/%d failed: %s",
                            attempt + 1, max_retries_per_chunk, exc,
                        )
                        if attempt < max_retries_per_chunk - 1:
                            import asyncio
                            await asyncio.sleep(2 ** attempt)

                if last_error is not None:
                    raise UploadError(
                        f"Failed to upload chunk after {max_retries_per_chunk} attempts"
                    ) from last_error

        raise UploadError(
            "Upload loop completed without receiving a final response from YouTube"
        )

    # ── Thumbnail upload ─────────────────────────────────────

    async def _upload_thumbnail(
        self,
        access_token: str,
        youtube_id: str,
        thumbnail_path: Path,
    ) -> None:
        """Upload a custom thumbnail for an uploaded video.

        Args:
            access_token: Valid OAuth2 access token.
            youtube_id: The YouTube video ID.
            thumbnail_path: Path to the thumbnail image file.

        Raises:
            UploadError: If the thumbnail upload fails.
        """
        self.logger.info("Uploading thumbnail for video %s…", youtube_id)

        image_data = thumbnail_path.read_bytes()

        # Determine content type from extension
        suffix = thumbnail_path.suffix.lower()
        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        content_type = content_types.get(suffix, "image/png")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": content_type,
            "Content-Length": str(len(image_data)),
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{_YT_THUMBNAIL_URL}?videoId={youtube_id}",
                headers=headers,
                content=image_data,
            )

            if resp.status_code not in (200, 201):
                self.logger.error(
                    "Thumbnail upload failed (HTTP %d): %s",
                    resp.status_code, resp.text[:500],
                )
                raise UploadError(
                    f"Thumbnail upload failed (HTTP {resp.status_code}): "
                    f"{resp.text[:500]}"
                )

        self.logger.info("Thumbnail uploaded successfully for video %s", youtube_id)
