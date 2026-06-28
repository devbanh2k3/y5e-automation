#!/usr/bin/env python3
"""Process durable per-channel YouTube upload jobs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core import production_tasks, youtube_channels, youtube_upload_jobs
from core.config import get_settings
from core.database import close_db, init_db
from core.reviews import get_review
from services.telegram_notifications import send_telegram_message
from services.youtube_upload_client import (
    YouTubeAuthRequired,
    YouTubePermanentError,
    YouTubeRetryableError,
    YouTubeUploadClient,
)

logger = logging.getLogger(__name__)


async def notify_owner(*, owner_telegram_user_id: int, text: str) -> None:
    """Deliver an upload lifecycle message to the owning Telegram chat."""
    chat_id = await production_tasks.get_notification_chat_id(owner_telegram_user_id)
    await send_telegram_message(chat_id=chat_id, text=text)


async def process_job(
    job: dict[str, Any],
    *,
    client: YouTubeUploadClient | Any | None = None,
) -> None:
    """Process one claimed job with explicit recovery ordering."""
    upload_job_id = str(job["upload_job_id"])
    context = await youtube_upload_jobs.load_job_context(upload_job_id)
    if not context:
        return
    owner_id = int(context["owner_telegram_user_id"])
    channel_id = str(context["youtube_channel_id"])
    upload_client = client or YouTubeUploadClient()
    try:
        review = await get_review(str(context["review_id"]))
        if review.get("status") != "approved":
            raise YouTubePermanentError("Review is not approved")
        video = review.get("video") or {}
        youtube = review.get("youtube") or {}
        existing_id = str(context.get("youtube_video_id") or "")
        existing_url = str(context.get("youtube_url") or "")
        if existing_id:
            await youtube_upload_jobs.mark_published(
                upload_job_id=upload_job_id,
                video_id=_optional_int(video.get("video_id")),
                youtube_video_id=existing_id,
                youtube_url=existing_url or f"https://youtube.com/watch?v={existing_id}",
            )
            return

        access_token = await upload_client.refresh_access_token(
            encrypted_refresh_token=str(context["encrypted_refresh_token"])
        )
        result = await upload_client.upload_video(
            access_token=access_token,
            video_path=Path(str(video.get("file_path") or context.get("video_path") or "")),
            metadata=youtube,
            language=str(context.get("language") or "en"),
            resumable_session_url=str(context.get("resumable_session_url") or ""),
            on_session_created=lambda session_url: youtube_upload_jobs.save_resumable_session(
                upload_job_id=upload_job_id,
                session_url=session_url,
            ),
        )
        await youtube_upload_jobs.mark_uploaded(
            upload_job_id=upload_job_id,
            youtube_video_id=result.youtube_video_id,
            youtube_url=result.youtube_url,
        )
        await youtube_upload_jobs.mark_published(
            upload_job_id=upload_job_id,
            video_id=_optional_int(video.get("video_id")),
            youtube_video_id=result.youtube_video_id,
            youtube_url=result.youtube_url,
        )
        await notify_owner(
            owner_telegram_user_id=owner_id,
            text=f"Published on {context.get('channel_title', 'YouTube')}: {result.youtube_url}",
        )
    except YouTubeAuthRequired as exc:
        await youtube_channels.mark_auth_required(
            owner_telegram_user_id=owner_id,
            channel_id=channel_id,
        )
        await youtube_upload_jobs.mark_job_auth_required(
            upload_job_id=upload_job_id,
            error_message=str(exc),
        )
        await notify_owner(
            owner_telegram_user_id=owner_id,
            text=f"YouTube authorization expired for {context.get('channel_title', 'channel')}. Reconnect it with /channels.",
        )
    except YouTubeRetryableError as exc:
        await youtube_upload_jobs.reschedule_job(
            upload_job_id=upload_job_id,
            error_code="youtube_retryable",
            error_message=str(exc),
        )
    except (YouTubePermanentError, KeyError, ValueError) as exc:
        await youtube_upload_jobs.mark_job_permanent_failure(
            upload_job_id=upload_job_id,
            error_code="youtube_permanent",
            error_message=str(exc),
        )
        await notify_owner(
            owner_telegram_user_id=owner_id,
            text=f"YouTube upload failed permanently: {exc}",
        )
    except Exception:
        logger.exception("Unexpected upload worker failure for job %s", upload_job_id)
        await youtube_upload_jobs.reschedule_job(
            upload_job_id=upload_job_id,
            error_code="worker_unexpected",
            error_message="Unexpected upload worker failure",
        )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def run(*, loop: bool, idle_sleep: float) -> None:
    """Poll and process jobs until one completes or the service stops."""
    settings = get_settings()
    await init_db()
    try:
        while True:
            if not settings.youtube_upload_enabled:
                if not loop:
                    return
                await asyncio.sleep(idle_sleep)
                continue
            job = await youtube_upload_jobs.claim_next_upload_job()
            if job:
                await process_job(job)
            elif not loop:
                return
            else:
                await asyncio.sleep(idle_sleep)
            if not loop:
                return
    finally:
        await close_db()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--idle-sleep", type=float, default=5.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, get_settings().log_level.upper(), logging.INFO))
    asyncio.run(run(loop=args.loop, idle_sleep=max(0.1, args.idle_sleep)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
