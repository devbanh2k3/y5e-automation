# Pipeline Smoke Mode v1 Design

## Purpose

Add a safe end-to-end pipeline execution mode that proves orchestration, queueing, worker execution, and job result reporting without spending real API cost, rendering heavy video, or uploading to YouTube.

This mode is the bridge between the production control plane and the real content pipeline. It lets the operator validate that the system is wired correctly before running expensive production jobs.

## Goals

- Allow `/api/pipeline/start` to accept an execution `mode`.
- Support `production`, `dry_run`, and `smoke` modes with stable semantics.
- Let the worker pass the requested mode into the pipeline.
- Let the pipeline return a structured summary that can be stored in job metadata.
- Avoid external side effects in smoke mode: no YouTube upload, no heavy Remotion render, no paid AI calls required.
- Add tests that prove the API, queue envelope, worker, and pipeline contract handle mode and result summaries correctly.

## Non-Goals

- Replace the full agent pipeline implementation.
- Build new content intelligence or analytics learning.
- Build a dashboard.
- Mock every internal agent method in production code.
- Add a separate workflow engine.
- Guarantee final video quality. Smoke mode verifies orchestration, not creative quality.

## Execution Modes

### `production`

The normal behavior. The worker calls `Pipeline.run_full(...)`, which runs the real agent chain and can perform external calls, video rendering, and upload.

### `dry_run`

A planning mode for validating request shape and queue behavior. It should enqueue and process a job, but the pipeline should return a lightweight summary without running the full agent chain.

Use this mode when testing scheduler/API integration.

### `smoke`

A safe pipeline orchestration mode. It should exercise the pipeline boundary and produce realistic result shapes, but skip expensive or irreversible side effects.

Use this mode before production runs on a new machine, new environment, or after pipeline refactors.

## API Contract

`POST /api/pipeline/start` should accept:

```json
{
  "category": "Science",
  "language": "vi",
  "count": 1,
  "mode": "smoke"
}
```

Rules:

- Default `mode` is `production` to preserve existing behavior.
- Valid modes are `production`, `dry_run`, and `smoke`.
- The queued job payload stores `category`, `language`, `count`, and `mode`.
- The response includes the queued `job_id` and mentions the selected mode in the message.

## Worker Contract

The worker should read `mode` from the job payload.

Rules:

- Missing `mode` defaults to `production`.
- Unsupported modes fail the job with a readable error.
- `production` calls `Pipeline.run_full(category=..., language=...)`.
- `dry_run` and `smoke` call a lightweight pipeline method that returns a summary.
- Successful jobs store `result_summary` in Redis job metadata.
- Failed jobs clear or omit `result_summary`.

## Pipeline Contract

Add a focused method to `Pipeline`:

```python
async def run_smoke(
    self,
    *,
    category: str,
    language: str = "vi",
    mode: str = "smoke",
) -> dict[str, Any]:
```

The method returns:

```python
{
    "mode": "smoke",
    "category": "Science",
    "language": "vi",
    "steps": [
        {"name": "topic", "status": "skipped", "reason": "smoke mode"},
        {"name": "research", "status": "skipped", "reason": "smoke mode"},
        {"name": "script", "status": "skipped", "reason": "smoke mode"},
        {"name": "render", "status": "skipped", "reason": "smoke mode"},
        {"name": "upload", "status": "skipped", "reason": "smoke mode"}
    ],
    "side_effects": {
        "ai_calls": false,
        "render": false,
        "upload": false
    }
}
```

`dry_run` can use the same method with `mode="dry_run"` and a smaller step list. The important point is that both modes produce a stable `dict[str, Any]` summary.

## Job Metadata

Add `result_summary` to job metadata responses. It should be a JSON string in Redis metadata so the current Redis hash design remains simple.

Rules:

- New jobs initialize `result_summary` as an empty string.
- Successful worker execution stores a JSON-encoded summary.
- Retry resets `result_summary` to an empty string.
- API job detail returns the raw string for now.

## Error Handling

- Invalid API mode should return FastAPI/Pydantic validation error `422`.
- Worker mode outside the known set should fail the job with `unsupported mode: <mode>`.
- Smoke mode must not hide worker validation errors such as missing `category`.
- Result summary serialization failure should fail the job, because the operator would otherwise lose the evidence that the job completed.

## Testing

Add focused tests for:

- API accepts and enqueues `mode`.
- API defaults mode to `production`.
- Invalid API mode returns `422`.
- Queue metadata includes `result_summary`.
- Worker passes production jobs to `run_full`.
- Worker routes `smoke` and `dry_run` jobs to `run_smoke`.
- Worker stores successful `result_summary`.
- Worker fails unsupported modes.
- Pipeline `run_smoke` returns a stable summary without calling external agents.

Existing production control plane tests must keep passing.

## Product Outcome

After this work, an operator can safely validate a deployment:

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "Science", "language": "vi", "count": 1, "mode": "smoke"}'
```

Then inspect:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

The job should complete quickly and include a result summary proving that the queue, worker, and pipeline boundary are functioning before any expensive production run.
