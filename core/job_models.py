from __future__ import annotations

from enum import StrEnum


class JobAction(StrEnum):
    RUN_PIPELINE = "run_pipeline"
    CHANNEL_ANALYSIS = "channel_analysis"


class PipelineMode(StrEnum):
    PRODUCTION = "production"
    DRY_RUN = "dry_run"
    SMOKE = "smoke"


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


def build_job_metadata(
    *,
    job_id: str,
    queue: str,
    action: JobAction,
    attempt: int,
    max_attempts: int,
    created_at: str,
    started_at: str = "",
    completed_at: str = "",
    failed_at: str = "",
    error: str = "",
    envelope_json: str = "",
    result_summary: str = "",
) -> dict[str, str]:
    return {
        "job_id": job_id,
        "queue": queue,
        "action": action.value,
        "status": JobStatus.QUEUED.value,
        "attempt": str(attempt),
        "max_attempts": str(max_attempts),
        "created_at": created_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "failed_at": failed_at,
        "error": error,
        "envelope_json": envelope_json,
        "result_summary": result_summary,
    }
