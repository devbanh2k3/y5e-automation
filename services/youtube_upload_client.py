"""Per-channel YouTube OAuth refresh and resumable media upload client."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from core.config import Settings, get_settings
from core.token_crypto import decrypt_secret

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CHUNK_SIZE = 5 * 1024 * 1024


class YouTubeUploadError(RuntimeError):
    """Base sanitized publishing failure."""


class YouTubeAuthRequired(YouTubeUploadError):
    """OAuth grant can no longer refresh access."""


class YouTubeRetryableError(YouTubeUploadError):
    """Transient provider or network failure."""


class YouTubePermanentError(YouTubeUploadError):
    """Request cannot succeed without changing input or configuration."""


@dataclass(frozen=True)
class UploadResult:
    youtube_video_id: str
    youtube_url: str


class YouTubeUploadClient:
    """Upload approved artifacts using one channel's encrypted credential."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        settings: Settings | Any | None = None,
    ) -> None:
        self.http_client = http_client
        self.settings = settings or get_settings()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            if self.http_client is not None:
                return await self.http_client.request(method, url, **kwargs)
            async with httpx.AsyncClient(timeout=60.0) as client:
                return await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise YouTubeRetryableError("YouTube network request failed") from exc

    async def refresh_access_token(self, *, encrypted_refresh_token: str) -> str:
        """Exchange an encrypted long-lived grant for a short-lived access token."""
        response = await self._request(
            "POST",
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self.settings.youtube_oauth_client_id,
                "client_secret": self.settings.youtube_oauth_client_secret,
                "refresh_token": decrypt_secret(encrypted_refresh_token),
                "grant_type": "refresh_token",
            },
        )
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code == 400 and payload.get("error") == "invalid_grant":
            raise YouTubeAuthRequired("YouTube authorization must be renewed")
        self._raise_for_status(response, operation="token refresh")
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise YouTubePermanentError("YouTube token response is incomplete")
        return access_token

    async def upload_video(
        self,
        *,
        access_token: str,
        video_path: Path,
        metadata: dict[str, Any],
        language: str,
        resumable_session_url: str = "",
    ) -> UploadResult:
        """Stream one MP4 through the YouTube resumable upload protocol."""
        if not video_path.is_file():
            raise YouTubePermanentError("Video file does not exist")
        title = str(metadata.get("title") or "").strip()[:100]
        description = str(metadata.get("description") or "").strip()
        tags = [str(tag).strip() for tag in metadata.get("tags") or [] if str(tag).strip()][:15]
        if not title or not description:
            raise YouTubePermanentError("Approved YouTube metadata is incomplete")

        mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
        file_size = video_path.stat().st_size
        session_url = resumable_session_url
        if not session_url:
            initiation = await self._request(
                "POST",
                YOUTUBE_UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Upload-Content-Length": str(file_size),
                    "X-Upload-Content-Type": mime_type,
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json={
                    "snippet": {
                        "title": title,
                        "description": description,
                        "tags": tags,
                        "categoryId": str(metadata.get("category_id") or "24"),
                        "defaultLanguage": language,
                        "defaultAudioLanguage": language,
                    },
                    "status": {
                        "privacyStatus": "public",
                        "selfDeclaredMadeForKids": False,
                    },
                },
            )
            self._raise_for_status(initiation, operation="upload initiation")
            session_url = str(initiation.headers.get("Location") or "")
            if not session_url:
                raise YouTubePermanentError("YouTube upload session is missing")

        with video_path.open("rb") as video_file:
            offset = 0
            while offset < file_size:
                chunk = video_file.read(CHUNK_SIZE)
                end = offset + len(chunk) - 1
                response = await self._request(
                    "PUT",
                    session_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": mime_type,
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{file_size}",
                    },
                    content=chunk,
                )
                if response.status_code == 308:
                    offset = end + 1
                    continue
                self._raise_for_status(response, operation="video upload")
                payload = response.json()
                youtube_video_id = str(payload.get("id") or "")
                if not youtube_video_id:
                    raise YouTubePermanentError("YouTube upload response has no video ID")
                return UploadResult(
                    youtube_video_id=youtube_video_id,
                    youtube_url=f"https://youtube.com/watch?v={youtube_video_id}",
                )
        raise YouTubeRetryableError("YouTube upload ended before completion")

    async def upload_thumbnail(
        self,
        *,
        access_token: str,
        youtube_video_id: str,
        thumbnail_path: Path,
    ) -> None:
        """Upload an optional custom thumbnail after the video ID is durable."""
        if not thumbnail_path.is_file():
            return
        response = await self._request(
            "POST",
            YOUTUBE_THUMBNAIL_URL,
            params={"videoId": youtube_video_id, "uploadType": "media"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": mimetypes.guess_type(thumbnail_path.name)[0] or "image/jpeg",
            },
            content=thumbnail_path.read_bytes(),
        )
        self._raise_for_status(response, operation="thumbnail upload")

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, operation: str) -> None:
        if response.status_code < 400:
            return
        if response.status_code == 401:
            raise YouTubeAuthRequired(f"YouTube {operation} requires authorization")
        if response.status_code == 429 or response.status_code >= 500:
            raise YouTubeRetryableError(f"YouTube {operation} is temporarily unavailable")
        raise YouTubePermanentError(f"YouTube {operation} was rejected (HTTP {response.status_code})")
