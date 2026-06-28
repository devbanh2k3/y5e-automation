from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio
async def test_refresh_uses_decrypted_channel_token(monkeypatch) -> None:
    from services import youtube_upload_client

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "access-1", "expires_in": 3600})

    monkeypatch.setattr(youtube_upload_client, "decrypt_secret", lambda value: "refresh-plain")
    settings = type(
        "S",
        (),
        {"youtube_oauth_client_id": "client", "youtube_oauth_client_secret": "secret"},
    )()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = youtube_upload_client.YouTubeUploadClient(http_client=http, settings=settings)
        token = await client.refresh_access_token(encrypted_refresh_token="ciphertext")

    assert token == "access-1"
    assert "refresh-plain" in captured["body"]


@pytest.mark.asyncio
async def test_upload_uses_public_status_and_approved_metadata(tmp_path: Path) -> None:
    from services.youtube_upload_client import YouTubeUploadClient

    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video-bytes")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            import json

            captured["metadata"] = json.loads(request.content)
            return httpx.Response(200, headers={"Location": "https://upload.test/session"})
        captured["content_range"] = request.headers["Content-Range"]
        return httpx.Response(200, json={"id": "yt-123"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = YouTubeUploadClient(http_client=http)
        result = await client.upload_video(
            access_token="access-1",
            video_path=video_path,
            metadata={
                "title": "Approved",
                "description": "Approved body",
                "tags": ["celebrity"],
            },
            language="en",
        )

    assert result.youtube_video_id == "yt-123"
    assert captured["metadata"]["status"]["privacyStatus"] == "public"
    assert captured["metadata"]["snippet"]["title"] == "Approved"
    assert captured["content_range"] == "bytes 0-10/11"


@pytest.mark.asyncio
async def test_invalid_grant_requires_reauthorization(monkeypatch) -> None:
    from services import youtube_upload_client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    monkeypatch.setattr(youtube_upload_client, "decrypt_secret", lambda value: "refresh")
    settings = type(
        "S",
        (),
        {"youtube_oauth_client_id": "client", "youtube_oauth_client_secret": "secret"},
    )()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = youtube_upload_client.YouTubeUploadClient(http_client=http, settings=settings)
        with pytest.raises(youtube_upload_client.YouTubeAuthRequired):
            await client.refresh_access_token(encrypted_refresh_token="ciphertext")
