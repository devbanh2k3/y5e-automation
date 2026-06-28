from pathlib import Path
from unittest.mock import AsyncMock

import pytest


def test_optional_int_rejects_values_outside_postgres_int32() -> None:
    from scripts.process_youtube_upload_job import _optional_int

    assert _optional_int("9") == 9
    assert _optional_int("20260628163852189216") is None
    assert _optional_int(None) is None


@pytest.mark.asyncio
async def test_worker_persists_youtube_id_before_notification(monkeypatch, tmp_path: Path) -> None:
    from scripts import process_youtube_upload_job as worker
    from services.youtube_upload_client import UploadResult

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    thumbnail = tmp_path / "thumbnail.jpg"
    thumbnail.write_bytes(b"thumbnail")
    events = []
    context = {
        "upload_job_id": "upload-1",
        "review_id": "review-1",
        "owner_telegram_user_id": 111,
        "youtube_channel_id": "channel-1",
        "encrypted_refresh_token": "ciphertext",
        "language": "en",
        "video_path": str(video),
        "youtube_video_id": "",
    }
    client = type(
        "Client",
        (),
        {
            "refresh_access_token": AsyncMock(return_value="access-1"),
            "upload_video": AsyncMock(
                return_value=UploadResult("yt-123", "https://youtube.com/watch?v=yt-123")
            ),
            "upload_thumbnail": AsyncMock(side_effect=lambda **kwargs: events.append("thumbnail")),
        },
    )()
    monkeypatch.setattr(worker.youtube_upload_jobs, "load_job_context", AsyncMock(return_value=context))
    monkeypatch.setattr(
        worker,
        "get_review",
        AsyncMock(
            return_value={
                "status": "approved",
                "video": {"file_path": str(video), "video_id": 9},
                "youtube": {"title": "Title", "description": "Body", "tags": ["tag"]},
                "thumbnail": {"status": "ready", "file_path": str(thumbnail)},
            }
        ),
    )
    monkeypatch.setattr(
        worker.youtube_upload_jobs,
        "mark_uploaded",
        AsyncMock(side_effect=lambda **kwargs: events.append("stored")),
    )
    monkeypatch.setattr(
        worker.youtube_upload_jobs,
        "mark_published",
        AsyncMock(side_effect=lambda **kwargs: events.append("published")),
    )
    monkeypatch.setattr(
        worker,
        "notify_owner",
        AsyncMock(side_effect=lambda **kwargs: events.append("notified")),
    )

    await worker.process_job({"upload_job_id": "upload-1"}, client=client)

    assert events == ["stored", "thumbnail", "published", "notified"]


@pytest.mark.asyncio
async def test_worker_skips_legacy_large_video_id_when_marking_published(monkeypatch, tmp_path: Path) -> None:
    from scripts import process_youtube_upload_job as worker
    from services.youtube_upload_client import UploadResult

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    context = {
        "upload_job_id": "upload-1",
        "review_id": "review-1",
        "owner_telegram_user_id": 111,
        "youtube_channel_id": "channel-1",
        "encrypted_refresh_token": "ciphertext",
        "language": "en",
        "video_path": str(video),
        "youtube_video_id": "",
    }
    client = type(
        "Client",
        (),
        {
            "refresh_access_token": AsyncMock(return_value="access-1"),
            "upload_video": AsyncMock(
                return_value=UploadResult("yt-123", "https://youtube.com/watch?v=yt-123")
            ),
        },
    )()
    monkeypatch.setattr(worker.youtube_upload_jobs, "load_job_context", AsyncMock(return_value=context))
    monkeypatch.setattr(
        worker,
        "get_review",
        AsyncMock(
            return_value={
                "status": "approved",
                "video": {
                    "file_path": str(video),
                    "video_id": 20260628163852189216,
                },
                "youtube": {"title": "Title", "description": "Body", "tags": []},
            }
        ),
    )
    mark_published = AsyncMock()
    monkeypatch.setattr(worker.youtube_upload_jobs, "mark_uploaded", AsyncMock())
    monkeypatch.setattr(worker.youtube_upload_jobs, "mark_published", mark_published)
    monkeypatch.setattr(worker, "notify_owner", AsyncMock())

    await worker.process_job({"upload_job_id": "upload-1"}, client=client)

    assert mark_published.await_args.kwargs["video_id"] is None


@pytest.mark.asyncio
async def test_auth_failure_marks_channel_and_job_without_retry(monkeypatch) -> None:
    from scripts import process_youtube_upload_job as worker
    from services.youtube_upload_client import YouTubeAuthRequired

    context = {
        "upload_job_id": "upload-1",
        "review_id": "review-1",
        "owner_telegram_user_id": 111,
        "youtube_channel_id": "channel-1",
        "encrypted_refresh_token": "ciphertext",
        "language": "en",
        "video_path": "/tmp/video.mp4",
        "youtube_video_id": "",
    }
    client = type(
        "Client",
        (),
        {"refresh_access_token": AsyncMock(side_effect=YouTubeAuthRequired("renew"))},
    )()
    monkeypatch.setattr(worker.youtube_upload_jobs, "load_job_context", AsyncMock(return_value=context))
    monkeypatch.setattr(
        worker,
        "get_review",
        AsyncMock(
            return_value={
                "status": "approved",
                "video": {"file_path": "/tmp/video.mp4"},
                "youtube": {"title": "Title", "description": "Body", "tags": []},
            }
        ),
    )
    auth_required = AsyncMock()
    retry = AsyncMock()
    monkeypatch.setattr(worker.youtube_upload_jobs, "mark_job_auth_required", auth_required)
    monkeypatch.setattr(worker.youtube_upload_jobs, "reschedule_job", retry)
    monkeypatch.setattr(worker.youtube_channels, "mark_auth_required", AsyncMock())
    monkeypatch.setattr(worker, "notify_owner", AsyncMock())

    await worker.process_job({"upload_job_id": "upload-1"}, client=client)

    assert auth_required.await_count == 1
    assert retry.await_count == 0
