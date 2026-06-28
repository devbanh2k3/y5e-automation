"""Approval and durable YouTube upload job lifecycle."""

from __future__ import annotations

from typing import Any

from core.config import get_settings
from core.database import execute, fetch, fetchrow, transaction
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


async def claim_next_upload_job() -> dict[str, Any] | None:
    """Claim one due upload job without allowing concurrent workers to share it."""
    return await fetchrow(
        """
        UPDATE youtube_upload_jobs
        SET status = 'uploading',
            attempt_count = attempt_count + 1,
            started_at = COALESCE(started_at, NOW()),
            updated_at = NOW()
        WHERE upload_job_id = (
            SELECT upload_job_id
            FROM youtube_upload_jobs
            WHERE (
                status IN ('queued', 'failed_retryable')
                AND next_attempt_at <= NOW()
                AND attempt_count < max_attempts
            ) OR (
                status IN ('uploading', 'processing')
                AND updated_at < NOW() - INTERVAL '15 minutes'
            )
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING upload_job_id::text, review_id, owner_telegram_user_id,
                  youtube_channel_id::text, status, attempt_count, max_attempts
        """
    )


async def load_job_context(upload_job_id: str) -> dict[str, Any] | None:
    """Load all non-secret and encrypted inputs needed by one worker execution."""
    return await fetchrow(
        """
        SELECT j.upload_job_id::text, j.review_id, j.owner_telegram_user_id,
               j.youtube_channel_id::text, j.youtube_video_id, j.youtube_url,
               j.resumable_session_url, j.attempt_count, j.max_attempts,
               c.encrypted_refresh_token, c.title AS channel_title, c.status AS channel_status,
               b.language, t.video_path
        FROM youtube_upload_jobs j
        JOIN production_tasks t ON t.task_id = j.task_id
        JOIN production_batches b ON b.batch_id = t.batch_id
        JOIN youtube_channels c ON c.youtube_channel_id = j.youtube_channel_id
        WHERE j.upload_job_id = $1::uuid
          AND c.owner_telegram_user_id = j.owner_telegram_user_id
        """,
        upload_job_id,
    )


async def mark_uploaded(
    *, upload_job_id: str, youtube_video_id: str, youtube_url: str
) -> None:
    """Persist provider identity immediately after upload completion."""
    await execute(
        """
        UPDATE youtube_upload_jobs
        SET status = 'processing', youtube_video_id = $2, youtube_url = $3,
            error_code = '', error_message = '', updated_at = NOW()
        WHERE upload_job_id = $1::uuid
        """,
        upload_job_id,
        youtube_video_id,
        youtube_url,
    )


async def save_resumable_session(*, upload_job_id: str, session_url: str) -> None:
    """Persist the opaque provider session URL for retry recovery."""
    await execute(
        """
        UPDATE youtube_upload_jobs
        SET resumable_session_url = $2, updated_at = NOW()
        WHERE upload_job_id = $1::uuid
        """,
        upload_job_id,
        session_url,
    )


async def mark_published(
    *,
    upload_job_id: str,
    video_id: int | None,
    youtube_video_id: str,
    youtube_url: str,
) -> None:
    """Finalize job, production task, and rendered video state atomically."""
    async with transaction() as connection:
        await connection.execute(
            """
            UPDATE youtube_upload_jobs
            SET status = 'published', youtube_video_id = $2, youtube_url = $3,
                published_at = NOW(), updated_at = NOW()
            WHERE upload_job_id = $1::uuid
            """,
            upload_job_id,
            youtube_video_id,
            youtube_url,
        )
        await connection.execute(
            """
            UPDATE production_tasks
            SET status = 'published', updated_at = NOW()
            WHERE task_id = (
                SELECT task_id FROM youtube_upload_jobs WHERE upload_job_id = $1::uuid
            )
            """,
            upload_job_id,
        )
        if video_id is not None:
            await connection.execute(
                """
                UPDATE videos
                SET youtube_id = $2, status = 'published', published_at = NOW()
                WHERE id = $1
                """,
                video_id,
                youtube_video_id,
            )


async def reschedule_job(*, upload_job_id: str, error_code: str, error_message: str) -> None:
    """Retry with bounded exponential backoff, or become permanently failed."""
    await execute(
        """
        UPDATE youtube_upload_jobs
        SET status = CASE
                WHEN attempt_count >= max_attempts THEN 'failed_permanent'
                ELSE 'failed_retryable'
            END,
            next_attempt_at = NOW() + (
                LEAST(900, 15 * POWER(2, GREATEST(attempt_count - 1, 0)))
                * INTERVAL '1 second'
            ),
            error_code = $2,
            error_message = LEFT($3, 1000),
            updated_at = NOW()
        WHERE upload_job_id = $1::uuid
        """,
        upload_job_id,
        error_code,
        error_message,
    )


async def mark_job_auth_required(
    *, upload_job_id: str, error_message: str
) -> None:
    """Stop retries until the channel reconnects."""
    await execute(
        """
        UPDATE youtube_upload_jobs
        SET status = 'auth_required', error_code = 'auth_required',
            error_message = LEFT($2, 1000), updated_at = NOW()
        WHERE upload_job_id = $1::uuid
        """,
        upload_job_id,
        error_message,
    )


async def mark_job_permanent_failure(
    *, upload_job_id: str, error_code: str, error_message: str
) -> None:
    """Record a sanitized terminal upload failure."""
    await execute(
        """
        UPDATE youtube_upload_jobs
        SET status = 'failed_permanent', error_code = $2,
            error_message = LEFT($3, 1000), updated_at = NOW()
        WHERE upload_job_id = $1::uuid
        """,
        upload_job_id,
        error_code,
        error_message,
    )
