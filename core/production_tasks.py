"""Telegram-owned production task queue with fair user scheduling."""

from __future__ import annotations

from typing import Any

from core.database import execute, fetch, fetchrow, fetchval

DEFAULT_CATEGORY = "celebrity"
DEFAULT_LANGUAGE = "en"
DEFAULT_CARD_LAYOUT = "flag_hero"
DEFAULT_TARGET_DURATION = 60


async def get_authorized_user(telegram_user_id: int) -> dict[str, Any] | None:
    """Return an active Telegram user record, or None when unauthorized."""
    return await fetchrow(
        """
        SELECT telegram_user_id, chat_id, username, role, is_active
        FROM telegram_users
        WHERE telegram_user_id = $1 AND is_active = TRUE
        """,
        telegram_user_id,
    )


async def update_user_chat_id(*, telegram_user_id: int, chat_id: int) -> None:
    """Remember the latest chat id for an authorized Telegram user."""
    await execute(
        """
        UPDATE telegram_users
        SET chat_id = $2,
            updated_at = NOW()
        WHERE telegram_user_id = $1 AND is_active = TRUE
        """,
        telegram_user_id,
        chat_id,
    )


async def get_notification_chat_id(telegram_user_id: int) -> int | None:
    """Return the chat id used for production notifications."""
    row = await fetchrow(
        """
        SELECT chat_id
        FROM telegram_users
        WHERE telegram_user_id = $1 AND is_active = TRUE
        """,
        telegram_user_id,
    )
    if not row or row.get("chat_id") is None:
        return None
    return int(row["chat_id"])


async def create_production_batch(
    *,
    owner_telegram_user_id: int,
    requested_count: int,
    language: str = DEFAULT_LANGUAGE,
    card_layout: str = DEFAULT_CARD_LAYOUT,
    category: str = DEFAULT_CATEGORY,
    target_duration: int = DEFAULT_TARGET_DURATION,
) -> dict[str, Any]:
    """Create a production batch and one queued task per requested video."""
    if requested_count < 1:
        raise ValueError("requested_count must be at least 1")
    if target_duration < 15:
        raise ValueError("target_duration must be at least 15 seconds")

    batch_id = await fetchval(
        """
        INSERT INTO production_batches (
            owner_telegram_user_id,
            requested_count,
            language,
            card_layout,
            category,
            target_duration
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING batch_id::text
        """,
        owner_telegram_user_id,
        requested_count,
        language,
        card_layout,
        category,
        target_duration,
    )

    await execute(
        """
        INSERT INTO production_user_scheduling (owner_telegram_user_id)
        VALUES ($1)
        ON CONFLICT (owner_telegram_user_id) DO NOTHING
        """,
        owner_telegram_user_id,
    )

    for slot_index in range(1, requested_count + 1):
        await execute(
            """
            INSERT INTO production_tasks (
                batch_id,
                owner_telegram_user_id,
                slot_index,
                status
            )
            VALUES ($1::uuid, $2, $3, 'queued')
            """,
            str(batch_id),
            owner_telegram_user_id,
            slot_index,
        )

    return {
        "batch_id": str(batch_id),
        "owner_telegram_user_id": owner_telegram_user_id,
        "requested_count": requested_count,
        "language": language,
        "card_layout": card_layout,
        "category": category,
        "target_duration": target_duration,
        "status": "queued",
    }


async def claim_next_fair_task() -> dict[str, Any] | None:
    """Claim the next queued task using round-robin fairness by Telegram user."""
    candidates = await fetch(
        """
        SELECT
            t.owner_telegram_user_id,
            s.last_served_at,
            MIN(t.created_at) AS oldest_task_created_at
        FROM production_tasks t
        LEFT JOIN production_user_scheduling s
            ON s.owner_telegram_user_id = t.owner_telegram_user_id
        WHERE t.status = 'queued'
        GROUP BY t.owner_telegram_user_id, s.last_served_at
        ORDER BY s.last_served_at NULLS FIRST, oldest_task_created_at ASC
        """
    )
    if not candidates:
        return None

    owner_id = int(candidates[0]["owner_telegram_user_id"])
    task = await fetchrow(
        """
        UPDATE production_tasks
        SET status = 'running',
            started_at = NOW(),
            updated_at = NOW(),
            attempt_count = attempt_count + 1
        WHERE task_id = (
            SELECT task_id
            FROM production_tasks
            WHERE status = 'queued' AND owner_telegram_user_id = $1
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING task_id::text, batch_id::text, owner_telegram_user_id, slot_index, status
        """,
        owner_id,
    )
    if not task:
        return None

    batch = await fetchrow(
        """
        SELECT category, language, card_layout, target_duration
        FROM production_batches
        WHERE batch_id = $1::uuid
        """,
        str(task["batch_id"]),
    )
    if batch:
        task.update(batch)

    await execute(
        """
        INSERT INTO production_user_scheduling (owner_telegram_user_id, last_served_at)
        VALUES ($1, NOW())
        ON CONFLICT (owner_telegram_user_id)
        DO UPDATE SET last_served_at = EXCLUDED.last_served_at
        """,
        owner_id,
    )
    return task


async def list_user_batches(telegram_user_id: int, *, limit: int = 10) -> list[dict[str, Any]]:
    """Return recent production batches for one Telegram user."""
    return await fetch(
        """
        SELECT
            batch_id::text,
            owner_telegram_user_id,
            requested_count,
            completed_count,
            failed_count,
            status,
            language,
            card_layout,
            category,
            target_duration,
            created_at
        FROM production_batches
        WHERE owner_telegram_user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        telegram_user_id,
        max(1, limit),
    )


async def user_queue_summary(telegram_user_id: int) -> dict[str, Any]:
    """Return task counts grouped by status for a Telegram user."""
    rows = await fetch(
        """
        SELECT status, COUNT(*)::int AS count
        FROM production_tasks
        WHERE owner_telegram_user_id = $1
        GROUP BY status
        """,
        telegram_user_id,
    )
    counts = {str(row["status"]): int(row["count"]) for row in rows}
    return {
        "owner_telegram_user_id": telegram_user_id,
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "pending_review": counts.get("pending_review", 0),
        "failed": counts.get("failed", 0),
    }


async def mark_task_pending_review(
    *,
    task_id: str,
    batch_id: str,
    review_id: str,
    topic_id: str,
    video_path: str,
) -> None:
    """Mark a running production task as ready for review."""
    await execute(
        """
        UPDATE production_tasks
        SET status = 'pending_review',
            review_id = $2,
            topic_id = $3,
            video_path = $4,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE task_id = $1::uuid
        """,
        task_id,
        review_id,
        topic_id,
        video_path,
    )
    await execute(
        """
        UPDATE production_batches
        SET completed_count = completed_count + 1,
            status = CASE
                WHEN completed_count + 1 + failed_count >= requested_count THEN 'pending_review'
                ELSE 'running'
            END,
            updated_at = NOW()
        WHERE batch_id = $1::uuid
        """,
        batch_id,
    )


async def mark_task_failed(*, task_id: str, batch_id: str, error: str) -> None:
    """Mark a running production task as failed."""
    await execute(
        """
        UPDATE production_tasks
        SET status = 'failed',
            error = $2,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE task_id = $1::uuid
        """,
        task_id,
        error[:2000],
    )
    await execute(
        """
        UPDATE production_batches
        SET failed_count = failed_count + 1,
            status = CASE
                WHEN completed_count + failed_count + 1 >= requested_count THEN 'completed_with_failures'
                ELSE 'running'
            END,
            updated_at = NOW()
        WHERE batch_id = $1::uuid
        """,
        batch_id,
    )
