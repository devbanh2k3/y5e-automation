"""FastAPI application — YouTube AI Automation API."""

from __future__ import annotations

import logging
from html import escape
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.config import get_settings
from core.database import init_db, close_db, fetch, fetchrow, execute
from core.health import check_readiness
from core.job_models import JobAction, PipelineMode
from core.queue import (
    init_queue,
    enqueue,
    close_queue,
    get_queue_length,
    get_job_metadata,
    get_queue_stats,
    list_jobs,
    retry_failed_job,
)
from core.reviews import (
    approve_review,
    get_review,
    list_reviews,
    reject_review,
    select_review_metadata,
)
from core.cost_tracker import get_usage_summary
from core.storage import get_storage_usage
from core.youtube_channels import OAuthStateError
from scripts.regenerate_scene import regenerate_wrong_image_scene
from services.youtube_oauth import (
    YouTubeOAuthError,
    complete_oauth as complete_youtube_oauth,
    start_oauth as start_youtube_oauth,
)

logger = logging.getLogger(__name__)

# ── Pydantic request / response models ───────────────────────


class PipelineStartRequest(BaseModel):
    """Request body for starting a pipeline run."""
    category: str = Field(..., min_length=1, description="Content category to generate for")
    language: str = Field(default="vi", description="Target language")
    count: int = Field(default=1, ge=1, le=10, description="Number of topics to generate")
    mode: PipelineMode = Field(
        default=PipelineMode.PRODUCTION,
        description="Execution mode: production, dry_run, or smoke",
    )


class PipelineStartResponse(BaseModel):
    """Response after queueing a pipeline job."""
    job_id: str
    message: str


class JobMetadataResponse(BaseModel):
    """Stable response shape for job metadata."""
    job_id: str = ""
    queue: str = ""
    action: str = ""
    status: str = ""
    attempt: str = ""
    max_attempts: str = ""
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    failed_at: str = ""
    error: str = ""
    envelope_json: str = ""
    result_summary: str = ""


class JobListResponse(BaseModel):
    """Response for recent job listing."""
    jobs: list[JobMetadataResponse]


class JobRetryResponse(BaseModel):
    """Response after retrying a failed job."""
    job_id: str
    status: str
    message: str


class QueueStatsResponse(BaseModel):
    """Queue length and recent job status counts."""
    queues: dict[str, dict[str, int]]
    statuses: dict[str, int]


class ReviewTransitionRequest(BaseModel):
    """Optional notes for approve/reject review transitions."""
    notes: str = ""
    reason: str = ""
    scenes: list[int] = Field(default_factory=list)


class ReviewRegenerateSceneRequest(BaseModel):
    """Request body for regenerating one review scene image and rerendering."""
    scene: int = Field(..., ge=0)
    reason: str = "wrong_image"
    rerender: bool = True


class ReviewMetadataSelectRequest(BaseModel):
    """Request body for selecting generated metadata variants."""
    title_index: int | None = Field(default=None, ge=0)
    description_index: int | None = Field(default=None, ge=0)
    thumbnail_text_index: int | None = Field(default=None, ge=0)
    tags: list[str] | None = None


class ReviewListResponse(BaseModel):
    """Response for review listing."""
    reviews: list[dict[str, Any]]


class ChannelAnalyzeRequest(BaseModel):
    """Request body for analyzing a YouTube channel."""
    channel_url: str = Field(..., min_length=5, description="YouTube channel URL")
    channel_name: str = Field(default="", description="Optional display name")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str
    database: str
    redis: str
    storage: dict[str, Any]


class ReadinessResponse(BaseModel):
    """Readiness response with dependency check details."""
    status: str
    timestamp: str
    checks: dict[str, Any]


# ── Lifespan ──────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logger.info("Starting YouTube AI Automation API …")

    # Initialise shared resources
    await init_db()
    await init_queue()
    logger.info("Database and Redis initialised.")

    yield

    # Graceful shutdown
    await close_db()
    await close_queue()
    logger.info("Shutdown complete.")


# ── App instance ──────────────────────────────────────────────

app = FastAPI(
    title="YouTube AI Automation API",
    description="Orchestration API for the YouTube AI video pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Routes ────────────────────────────────────────────────────


@app.get("/review-ui", tags=["Reviews"])
async def review_ui() -> FileResponse:
    """Serve the local review gate UI."""
    return FileResponse(STATIC_DIR / "review-ui.html", media_type="text/html")


@app.get("/api/youtube/oauth/start", tags=["YouTube"])
async def youtube_oauth_start(ticket: str) -> RedirectResponse:
    """Start a tenant-bound Google OAuth flow from a one-time Telegram ticket."""
    try:
        authorization_url = await start_youtube_oauth(ticket)
    except OAuthStateError:
        raise HTTPException(status_code=400, detail="OAuth link is invalid or expired") from None
    return RedirectResponse(authorization_url)


@app.get("/api/youtube/oauth/callback", tags=["YouTube"])
async def youtube_oauth_callback(code: str, state: str) -> HTMLResponse:
    """Complete Google OAuth and show a minimal browser result."""
    try:
        channel = await complete_youtube_oauth(code=code, state=state)
    except OAuthStateError:
        return HTMLResponse("OAuth link is invalid or already used.", status_code=400)
    except YouTubeOAuthError as exc:
        return HTMLResponse(escape(str(exc)), status_code=400)
    title = escape(str(channel.get("title") or "YouTube channel"))
    return HTMLResponse(f"<h1>Channel connected</h1><p>{title}</p>")


@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """Return service health, database connectivity, and storage stats."""
    db_status = "ok"
    redis_status = "ok"

    try:
        await fetchrow("SELECT 1 AS ok")
    except Exception:
        db_status = "error"

    try:
        from core.queue import get_redis
        r = await get_redis()
        await r.ping()
    except Exception:
        redis_status = "error"

    storage = get_storage_usage()

    return HealthResponse(
        status="healthy" if db_status == "ok" and redis_status == "ok" else "degraded",
        timestamp=datetime.now(timezone.utc).isoformat(),
        database=db_status,
        redis=redis_status,
        storage=storage,
    )


@app.get("/api/ready", response_model=ReadinessResponse, tags=["System"])
async def readiness_check() -> JSONResponse | ReadinessResponse:
    """Return readiness details for dependencies required to process jobs."""
    result = await check_readiness()
    payload = ReadinessResponse(
        status="ready" if result.ok else "not_ready",
        timestamp=datetime.now(timezone.utc).isoformat(),
        checks={name: check.model_dump() for name, check in result.checks.items()},
    )
    if result.ok:
        return payload
    return JSONResponse(status_code=503, content=payload.model_dump())


@app.post("/api/pipeline/start", response_model=PipelineStartResponse, tags=["Pipeline"])
async def start_pipeline(body: PipelineStartRequest) -> PipelineStartResponse:
    """Queue a new pipeline run for the given category."""
    job_data = {
        "category": body.category,
        "language": body.language,
        "count": body.count,
        "mode": body.mode.value,
    }
    job_id = await enqueue("pipeline", job_data, action=JobAction.RUN_PIPELINE)

    return PipelineStartResponse(
        job_id=job_id,
        message=(
            f"Pipeline queued for category '{body.category}' "
            f"({body.count} topics, mode {body.mode.value})."
        ),
    )


@app.get("/api/jobs/{job_id}", response_model=JobMetadataResponse, tags=["Jobs"])
async def get_job(job_id: str) -> JobMetadataResponse:
    """Return metadata for a queued or processed job."""
    metadata = await get_job_metadata(job_id)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return JobMetadataResponse(**metadata)


@app.get("/api/jobs", response_model=JobListResponse, tags=["Jobs"])
async def list_recent_jobs(
    status: str | None = None,
    queue: str | None = None,
    limit: int = 50,
) -> JobListResponse:
    """Return recent jobs with optional status and queue filters."""
    jobs = await list_jobs(status=status, queue=queue, limit=min(max(limit, 1), 100))
    return JobListResponse(jobs=[JobMetadataResponse(**job) for job in jobs])


@app.post("/api/jobs/{job_id}/retry", response_model=JobRetryResponse, tags=["Jobs"])
async def retry_job(job_id: str) -> JobRetryResponse:
    """Retry a failed job by requeueing its stored envelope."""
    try:
        await retry_failed_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    return JobRetryResponse(
        job_id=job_id,
        status="queued",
        message="Job requeued.",
    )


@app.get("/api/queues", response_model=QueueStatsResponse, tags=["Jobs"])
async def queue_stats() -> QueueStatsResponse:
    """Return pending queue lengths and recent job status counts."""
    stats = await get_queue_stats(["pipeline", "channel_analysis"])
    return QueueStatsResponse(**stats)


@app.get("/api/reviews", response_model=ReviewListResponse, tags=["Reviews"])
async def list_review_items(
    status: str | None = "pending_review",
    quality_status: str | None = None,
    sort: str = "newest",
    limit: int = 50,
) -> ReviewListResponse:
    """Return render reviews, pending first by default."""
    reviews = await list_reviews(
        status=status,
        quality_status=quality_status,
        sort=sort,
        limit=min(max(limit, 1), 100),
    )
    return ReviewListResponse(reviews=reviews)


@app.get("/api/reviews/{review_id}", tags=["Reviews"])
async def get_review_item(review_id: str) -> dict[str, Any]:
    """Return a single review artifact."""
    try:
        return await get_review(review_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found.") from None


@app.get("/api/reviews/{review_id}/video", tags=["Reviews"])
async def get_review_video(review_id: str) -> FileResponse:
    """Stream the MP4 referenced by a review artifact."""
    try:
        review = await get_review(review_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found.") from None

    video_path = Path(str((review.get("video") or {}).get("file_path", ""))).expanduser()
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Review video file not found.")
    return FileResponse(video_path, media_type="video/mp4", filename=video_path.name)


@app.get("/api/reviews/{review_id}/images/{scene_index}", tags=["Reviews"])
async def get_review_scene_image(review_id: str, scene_index: int) -> FileResponse:
    """Serve the verified local image for a review scene."""
    try:
        review = await get_review(review_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found.") from None

    items = (review.get("image_verification_contract") or {}).get("items") or []
    image_item = next(
        (item for item in items if int(item.get("scene_index", -1)) == scene_index),
        None,
    )
    image_path = Path(str((image_item or {}).get("local_path", ""))).expanduser()
    if not image_item or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Review scene image not found.")
    return FileResponse(image_path, filename=image_path.name)


@app.post("/api/reviews/{review_id}/approve", tags=["Reviews"])
async def approve_review_item(
    review_id: str,
    body: ReviewTransitionRequest,
) -> dict[str, Any]:
    """Approve a pending review."""
    try:
        return await approve_review(review_id, notes=body.notes)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/reviews/{review_id}/reject", tags=["Reviews"])
async def reject_review_item(
    review_id: str,
    body: ReviewTransitionRequest,
) -> dict[str, Any]:
    """Reject a pending review."""
    try:
        reason = body.reason or "other"
        return await reject_review(
            review_id,
            reason=reason,
            scenes=body.scenes,
            notes=body.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/reviews/{review_id}/metadata/select", tags=["Reviews"])
async def select_review_metadata_item(
    review_id: str,
    body: ReviewMetadataSelectRequest,
) -> dict[str, Any]:
    """Select one or more generated metadata variants for a review."""
    try:
        return await select_review_metadata(
            review_id,
            title_index=body.title_index,
            description_index=body.description_index,
            thumbnail_text_index=body.thumbnail_text_index,
            tags=body.tags,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post("/api/reviews/{review_id}/regenerate-scene", tags=["Reviews"])
async def regenerate_review_scene_item(
    review_id: str,
    body: ReviewRegenerateSceneRequest,
) -> dict[str, Any]:
    """Regenerate one wrong-image scene and rerender the review video."""
    if body.reason != "wrong_image":
        raise HTTPException(status_code=409, detail="only wrong_image regeneration is supported")
    try:
        return await regenerate_wrong_image_scene(
            review_id,
            scene_index=body.scene,
            rerender=body.rerender,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/api/pipeline/status/{topic_id}", tags=["Pipeline"])
async def get_pipeline_status(topic_id: int) -> dict[str, Any]:
    """Return the current pipeline status for a topic."""
    topic = await fetchrow("SELECT * FROM topics WHERE id = $1", topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic {topic_id} not found.")

    logs = await fetch(
        """
        SELECT agent_name, status, error_message, retry_count, started_at, completed_at
        FROM pipeline_logs
        WHERE topic_id = $1
        ORDER BY created_at DESC
        """,
        topic_id,
    )

    video = await fetchrow(
        "SELECT id, status, youtube_id, file_path FROM videos WHERE topic_id = $1 ORDER BY created_at DESC LIMIT 1",
        topic_id,
    )

    return {
        "topic": {
            "id": topic["id"],
            "title": topic["title"],
            "category": topic["category"],
            "status": topic["status"],
            "score": float(topic["score"]) if topic["score"] else 0.0,
            "created_at": topic["created_at"].isoformat() if topic["created_at"] else None,
        },
        "pipeline_logs": [
            {
                "agent": log["agent_name"],
                "status": log["status"],
                "error": log["error_message"],
                "retries": log["retry_count"],
                "started_at": log["started_at"].isoformat() if log["started_at"] else None,
                "completed_at": log["completed_at"].isoformat() if log["completed_at"] else None,
            }
            for log in logs
        ],
        "video": {
            "id": video["id"],
            "status": video["status"],
            "youtube_id": video["youtube_id"],
            "file_path": video["file_path"],
        } if video else None,
    }


@app.post("/api/channels/analyze", tags=["Channels"])
async def analyze_channel(body: ChannelAnalyzeRequest) -> dict[str, Any]:
    """Register a channel for analysis and queue the analysis job."""
    # Upsert channel
    existing = await fetchrow(
        "SELECT id FROM reference_channels WHERE channel_url = $1",
        body.channel_url,
    )

    if existing:
        channel_id = existing["id"]
        if body.channel_name:
            await execute(
                "UPDATE reference_channels SET channel_name = $1 WHERE id = $2",
                body.channel_name,
                channel_id,
            )
    else:
        row = await fetchrow(
            """
            INSERT INTO reference_channels (channel_url, channel_name, created_at)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            body.channel_url,
            body.channel_name or "Unknown",
            datetime.now(timezone.utc),
        )
        channel_id = row["id"]  # type: ignore[index]

    # Queue analysis job
    job_id = await enqueue(
        "channel_analysis",
        {
            "channel_db_id": channel_id,
            "channel_url": body.channel_url,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        },
        action=JobAction.CHANNEL_ANALYSIS,
    )

    return {
        "channel_id": channel_id,
        "job_id": job_id,
        "message": f"Channel analysis queued for '{body.channel_url}'.",
    }


@app.get("/api/channels", tags=["Channels"])
async def list_channels() -> dict[str, Any]:
    """List all reference channels."""
    rows = await fetch(
        """
        SELECT id, channel_url, channel_name, channel_id, subscriber_count,
               video_count, top_categories, last_analyzed_at, created_at
        FROM reference_channels
        ORDER BY created_at DESC
        """
    )
    channels = [
        {
            "id": row["id"],
            "channel_url": row["channel_url"],
            "channel_name": row["channel_name"],
            "channel_id": row["channel_id"],
            "subscriber_count": row["subscriber_count"],
            "video_count": row["video_count"],
            "top_categories": row["top_categories"],
            "last_analyzed_at": row["last_analyzed_at"].isoformat() if row["last_analyzed_at"] else None,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]
    return {"count": len(channels), "channels": channels}


@app.get("/api/stats", tags=["System"])
async def get_stats() -> dict[str, Any]:
    """Return system-wide statistics."""
    usage = await get_usage_summary()

    topic_count = await fetchrow("SELECT COUNT(*) AS n FROM topics")
    video_count = await fetchrow("SELECT COUNT(*) AS n FROM videos")
    pending_queue = await get_queue_length("pipeline")

    return {
        "topics": topic_count["n"] if topic_count else 0,
        "videos": video_count["n"] if video_count else 0,
        "pending_jobs": pending_queue,
        "api_usage": usage,
    }
