from pathlib import Path
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_approval_requires_explicit_channel_then_publish(monkeypatch, tmp_path: Path) -> None:
    from scripts import process_youtube_upload_job as worker
    from services import telegram_channels, telegram_review_actions
    from services.youtube_upload_client import UploadResult

    select = AsyncMock(
        return_value={"youtube_channel_id": "channel-alice", "title": "Alice Channel"}
    )
    monkeypatch.setattr(telegram_channels.youtube_channels, "select_owned_channel", select)
    selected = await telegram_channels.handle_channel_callback(
        telegram_user_id=111,
        data="yt:select:channel-alice",
    )
    assert selected.text == "Selected channel: Alice Channel"
    assert select.await_args.kwargs["owner_telegram_user_id"] == 111

    monkeypatch.setattr(
        telegram_review_actions.production_tasks,
        "get_authorized_user",
        AsyncMock(return_value={"telegram_user_id": 111, "is_active": True}),
    )
    monkeypatch.setattr(
        telegram_review_actions.youtube_channels,
        "list_owned_channels",
        AsyncMock(
            return_value=[
                {"youtube_channel_id": "channel-alice", "title": "Alice Channel", "status": "active"}
            ]
        ),
    )
    enqueue = AsyncMock(return_value={"upload_job_id": "upload-1", "status": "queued"})
    monkeypatch.setattr(
        telegram_review_actions.youtube_upload_jobs,
        "approve_and_enqueue",
        enqueue,
    )
    approval = await telegram_review_actions.handle_review_callback(
        telegram_user_id=111,
        data="rv:ok:review-1",
    )
    assert approval.reply_markup["inline_keyboard"][0][0]["callback_data"] == "rv:ch:1:review-1"
    enqueue.assert_not_awaited()

    approval = await telegram_review_actions.handle_review_callback(
        telegram_user_id=111,
        data="rv:ch:1:review-1",
    )
    assert "upload-1" not in approval
    assert "alice channel" in approval.lower()
    assert enqueue.await_args.kwargs["owner_telegram_user_id"] == 111
    assert enqueue.await_args.kwargs["youtube_channel_id"] == "channel-alice"

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    context = {
        "upload_job_id": "upload-1",
        "review_id": "review-1",
        "owner_telegram_user_id": 111,
        "youtube_channel_id": "channel-alice",
        "channel_title": "Alice Channel",
        "encrypted_refresh_token": "ciphertext",
        "language": "en",
        "video_path": str(video),
        "youtube_video_id": "",
        "youtube_url": "",
        "resumable_session_url": "",
    }
    monkeypatch.setattr(worker.youtube_upload_jobs, "load_job_context", AsyncMock(return_value=context))
    monkeypatch.setattr(
        worker,
        "get_review",
        AsyncMock(
            return_value={
                "status": "approved",
                "video": {"file_path": str(video), "video_id": 9},
                "youtube": {"title": "Approved", "description": "Body", "tags": []},
            }
        ),
    )
    mark_uploaded = AsyncMock()
    mark_published = AsyncMock()
    monkeypatch.setattr(worker.youtube_upload_jobs, "mark_uploaded", mark_uploaded)
    monkeypatch.setattr(worker.youtube_upload_jobs, "mark_published", mark_published)
    monkeypatch.setattr(worker.youtube_upload_jobs, "save_resumable_session", AsyncMock())
    monkeypatch.setattr(worker, "notify_owner", AsyncMock())
    client = type(
        "Client",
        (),
        {
            "refresh_access_token": AsyncMock(return_value="access-1"),
            "upload_video": AsyncMock(
                return_value=UploadResult("yt-1", "https://youtube.com/watch?v=yt-1")
            ),
        },
    )()

    await worker.process_job({"upload_job_id": "upload-1"}, client=client)

    assert mark_uploaded.await_args.kwargs["youtube_video_id"] == "yt-1"
    assert mark_published.await_args.kwargs["youtube_video_id"] == "yt-1"
