"""FastAPI application — YouTube AI Automation API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
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
)
from core.cost_tracker import get_usage_summary
from core.storage import get_storage_usage

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


# ── Routes ────────────────────────────────────────────────────


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
    limit: int = 50,
) -> ReviewListResponse:
    """Return render reviews, pending first by default."""
    reviews = await list_reviews(status=status, limit=min(max(limit, 1), 100))
    return ReviewListResponse(reviews=reviews)


@app.get("/api/reviews/{review_id}", tags=["Reviews"])
async def get_review_item(review_id: str) -> dict[str, Any]:
    """Return a single review artifact."""
    try:
        return await get_review(review_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found.") from None


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
