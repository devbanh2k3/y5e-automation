"""Telegram callback handlers for review approval and rejection."""

from __future__ import annotations

from core import production_tasks, youtube_upload_jobs
from core.reviews import reject_review


async def handle_review_callback(*, telegram_user_id: int, data: str) -> str:
    """Handle one Telegram inline review action."""
    user = await production_tasks.get_authorized_user(telegram_user_id)
    if not user:
        return "You are not authorized to review videos."

    parsed = parse_review_callback(data)
    if parsed is None:
        return "Unsupported review action."

    action, reason, review_id = parsed
    try:
        if action == "approve":
            job = await youtube_upload_jobs.approve_and_enqueue(
                review_id=review_id,
                owner_telegram_user_id=telegram_user_id,
            )
            return f"Approved and queued upload {job['upload_job_id']}."
        await reject_review(review_id, reason=reason, notes=f"rejected from Telegram: {reason}")
        await production_tasks.mark_task_review_decision(review_id=review_id, status="rejected")
        return f"Rejected review {review_id}: {reason}."
    except KeyError:
        return f"Review {review_id} not found."
    except ValueError as exc:
        return str(exc)


def parse_review_callback(data: str) -> tuple[str, str, str] | None:
    """Parse compact Telegram callback data."""
    if data.startswith("rv:ok:"):
        return "approve", "", data.removeprefix("rv:ok:")
    if data.startswith("rv:rej:"):
        parts = data.split(":", 3)
        if len(parts) != 4:
            return None
        _, _, reason, review_id = parts
        if not reason or not review_id:
            return None
        return "reject", reason, review_id
    return None
