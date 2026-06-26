# Production Control Plane v1 Design

## Purpose

Build the operational foundation that makes the YouTube automation system usable as a real product. This work does not add new creative agents. It makes the existing API, Redis queue, and worker observable, controllable, and predictable enough to run long-lived automation jobs.

## Goals

- Fail fast when required production configuration is missing.
- Separate lightweight health checks from readiness checks that verify dependencies.
- Expose stable job management APIs for listing, inspecting, retrying, and measuring queue work.
- Harden worker behavior for bad payloads, unsupported actions, retries, and structured job logging.
- Keep the implementation small and testable, using the existing FastAPI, Redis queue, and pytest patterns.

## Non-Goals

- Build a web dashboard.
- Replace Redis with a full workflow engine.
- Add new YouTube growth intelligence agents.
- Implement OAuth setup or production deployment automation.
- Persist job history in PostgreSQL. Redis remains the job metadata store for v1.

## Architecture

The API remains the control surface. It validates startup readiness, accepts pipeline requests, exposes job operations, and reports queue metrics. Redis remains the job queue and metadata store. The worker remains a separate process that consumes queue envelopes and updates job metadata.

New logic should be placed in focused modules:

- `core/config.py` owns settings and production validation.
- `core/health.py` owns health/readiness dependency checks.
- `core/queue.py` owns queue operations, job metadata, listing, retry enqueueing, and queue stats.
- `workers/pipeline_worker.py` owns job execution behavior and metadata transitions.
- `api/main.py` exposes stable HTTP contracts.

## Configuration Validation

The system should support two modes:

- `development`: permits placeholder credentials so local tests and demos remain easy.
- `production`: rejects placeholder or missing required values at startup/readiness.

Add `app_env` to settings with default `development`. Production validation should report missing or unsafe values for:

- `primary_api_key`
- `youtube_api_key`
- `database_url`
- `redis_url`

The validation result should be structured and testable. The API should not expose secret values.

## Health and Readiness

Keep `/api/health` as a lightweight liveness-style check. It should return service status and timestamp.

Add `/api/ready` for dependency readiness. It should check:

- Database connectivity with `SELECT 1`.
- Redis connectivity with `PING`.
- Storage path creation/access.
- Production configuration validation.

Readiness should return HTTP 200 when all checks pass and HTTP 503 when any required check fails. The response should include component names and statuses without secrets.

## Job Management APIs

Keep `GET /api/jobs/{job_id}` and make its response contract explicit.

Add:

- `GET /api/jobs`: list recent jobs, optionally filtered by status and queue.
- `POST /api/jobs/{job_id}/retry`: retry a failed job by requeueing the original payload.
- `GET /api/queues`: return queue lengths and job status counts.

Redis metadata should store enough data to support these endpoints:

- `job_id`
- `queue`
- `action`
- `status`
- `attempt`
- `max_attempts`
- `created_at`
- `started_at`
- `completed_at`
- `failed_at`
- `error`
- serialized original envelope or payload needed for retry

Job listing can be implemented with a Redis sorted set keyed by creation timestamp. This avoids scanning all Redis keys.

## Worker Hardening

The worker should treat malformed work as a failed job with a clear error instead of crashing the loop.

Required behavior:

- Missing `job_id`, `queue`, or `data` should be handled defensively.
- Missing required pipeline field `category` should fail the job with a readable error.
- Unsupported actions should fail the job and record the unsupported action.
- Retryable exceptions should move the job to `retrying` or `queued` with incremented attempt.
- Final failures should record `failed_at` and a truncated error message.
- Successful jobs should record `completed_at` and clear `error`.

Logs should include `job_id`, `queue`, `action`, and `attempt` where available.

## Error Handling

HTTP endpoints should return:

- `404` for unknown jobs.
- `409` when retry is requested for a job that is not failed.
- `503` for failed readiness.
- `422` for invalid request bodies through FastAPI/Pydantic.

Internal exception details should be logged but API responses should stay stable and avoid secrets.

## Testing

Add focused tests for:

- Production config validation.
- `/api/ready` success and failure responses.
- Job listing and queue stats.
- Retry API behavior for unknown, non-failed, and failed jobs.
- Worker handling for malformed payloads and missing category.

Existing tests for queue, API jobs, worker, and video contract must keep passing.

## Product Outcome

After this work, the system can be operated like a real service:

- A user can know if it is ready before starting jobs.
- A scheduler such as n8n can start jobs and poll status.
- Failed jobs can be inspected and retried through API.
- Operators can see queue pressure and job outcomes.
- Configuration mistakes are visible before wasting long AI/video runs.
