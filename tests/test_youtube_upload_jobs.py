from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest


class FakeConnection:
    def __init__(self, *, owner_matches: bool = True) -> None:
        self.owner_matches = owner_matches
        self.insert_count = 0
        self.insert_query = ""
        self.executed = []

    async def fetchrow(self, query, *args):
        if "FROM production_tasks" in query:
            if not self.owner_matches:
                return None
            return {
                "task_id": "task-1",
                "status": "pending_review",
                "youtube_channel_id": "channel-1",
            }
        if "INSERT INTO youtube_upload_jobs" in query:
            self.insert_count += 1
            self.insert_query = query
            return {"upload_job_id": "upload-1", "status": "queued"}
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_approve_and_enqueue_uses_unique_review_job(monkeypatch) -> None:
    from core import youtube_upload_jobs

    connection = FakeConnection()

    @asynccontextmanager
    async def fake_transaction():
        yield connection

    monkeypatch.setattr(youtube_upload_jobs, "transaction", fake_transaction)
    monkeypatch.setattr(
        youtube_upload_jobs,
        "get_review",
        AsyncMock(return_value={"status": "pending_review"}),
    )
    monkeypatch.setattr(
        youtube_upload_jobs,
        "approve_review",
        AsyncMock(return_value={"status": "approved"}),
    )

    result = await youtube_upload_jobs.approve_and_enqueue(
        review_id="review-1",
        owner_telegram_user_id=111,
        youtube_channel_id="channel-1",
    )

    assert result == {"upload_job_id": "upload-1", "status": "queued"}
    assert connection.insert_count == 1
    assert "ON CONFLICT (review_id)" in connection.insert_query


@pytest.mark.asyncio
async def test_approve_cannot_enqueue_another_users_review(monkeypatch) -> None:
    from core import youtube_upload_jobs

    @asynccontextmanager
    async def fake_transaction():
        yield FakeConnection(owner_matches=False)

    monkeypatch.setattr(youtube_upload_jobs, "transaction", fake_transaction)

    with pytest.raises(PermissionError):
        await youtube_upload_jobs.approve_and_enqueue(
            review_id="review-user-222",
            owner_telegram_user_id=111,
            youtube_channel_id="channel-user-222",
        )


@pytest.mark.asyncio
async def test_claim_next_upload_job_uses_skip_locked(monkeypatch) -> None:
    from core import youtube_upload_jobs

    fetchrow = AsyncMock(return_value={"upload_job_id": "upload-1", "status": "uploading"})
    monkeypatch.setattr(youtube_upload_jobs, "fetchrow", fetchrow)

    job = await youtube_upload_jobs.claim_next_upload_job()

    assert job["upload_job_id"] == "upload-1"
    query = fetchrow.await_args.args[0]
    assert "FOR UPDATE SKIP LOCKED" in query
    assert "failed_retryable" in query
    assert "status IN ('uploading', 'processing')" in query
    assert "INTERVAL '15 minutes'" in query
