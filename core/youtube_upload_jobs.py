"""Approval and durable YouTube upload job lifecycle."""

from __future__ import annotations

from typing import Any

from core.config import get_settings
from core.database import fetch, fetchrow, transaction
from core.reviews import ReviewStatus, approve_review, get_review


async def approve_and_enqueue(
    *,
    review_id: str,
    owner_telegram_user_id: int,
) -> dict[str, Any]:
    """Approve one owned review and idempotently queue its assigned upload."""
    async with transaction() as connection:
        task = await connection.fetchrow(
            """
            SELECT t.task_id, t.status, b.youtube_channel_id
            FROM production_tasks t
            JOIN production_batches b ON b.batch_id = t.batch_id
            JOIN youtube_channels c ON c.youtube_channel_id = b.youtube_channel_id
            WHERE t.review_id = $1
              AND t.owner_telegram_user_id = $2
              AND c.owner_telegram_user_id = $2
              AND c.status = 'active'
            FOR UPDATE OF t
            """,
            review_id,
            owner_telegram_user_id,
        )
        if not task:
            raise PermissionError("Review is unavailable")

        review = await get_review(review_id)
        review_status = str(review.get("status") or "")
        if review_status == ReviewStatus.PENDING.value:
            await approve_review(review_id, notes="approved from Telegram")
        elif review_status != ReviewStatus.APPROVED.value:
            raise ValueError("review is not pending or approved")

        job = await connection.fetchrow(
            """
            INSERT INTO youtube_upload_jobs (
                review_id, task_id, owner_telegram_user_id,
                youtube_channel_id, max_attempts
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (review_id)
            DO UPDATE SET review_id = EXCLUDED.review_id
            RETURNING upload_job_id::text, status
            """,
            review_id,
            task["task_id"],
            owner_telegram_user_id,
            task["youtube_channel_id"],
            max(1, get_settings().youtube_upload_max_attempts),
        )
        await connection.execute(
            """
            UPDATE production_tasks
            SET status = 'approved', updated_at = NOW()
            WHERE task_id = $1
            """,
            task["task_id"],
        )
    if not job:
        raise RuntimeError("Upload job could not be queued")
    return dict(job)


async def list_owner_jobs(
    owner_telegram_user_id: int,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """List recent upload jobs without exposing credentials."""
    return await fetch(
        """
        SELECT j.upload_job_id::text, j.review_id, j.status, j.youtube_url,
               j.error_code, j.created_at, j.updated_at, c.title AS channel_title
        FROM youtube_upload_jobs j
        JOIN youtube_channels c ON c.youtube_channel_id = j.youtube_channel_id
        WHERE j.owner_telegram_user_id = $1
        ORDER BY j.created_at DESC
        LIMIT $2
        """,
        owner_telegram_user_id,
        max(1, min(limit, 50)),
    )


async def get_job(upload_job_id: str) -> dict[str, Any] | None:
    """Load one upload job by internal ID for worker processing."""
    return await fetchrow(
        "SELECT * FROM youtube_upload_jobs WHERE upload_job_id = $1::uuid",
        upload_job_id,
    )
