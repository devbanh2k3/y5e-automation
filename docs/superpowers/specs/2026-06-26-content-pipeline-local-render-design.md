# Content Pipeline Local Render v1 Design

## Purpose

Make the system produce one real local video artifact reliably before adding YouTube upload, analytics feedback, or more advanced content intelligence.

The current system has a production control plane and smoke mode. This step turns the pipeline from "wired and testable" into "able to generate a tangible video file on disk" while avoiding irreversible external side effects such as YouTube upload.

## Goals

- Add a local render execution path that runs the pipeline through video rendering and stops before upload.
- Reuse the existing queue, worker, job metadata, pipeline, and Remotion video engine.
- Return a structured result summary containing topic/video identifiers and the rendered file path.
- Validate the Python-to-Remotion video data contract before attempting expensive rendering.
- Provide safe fallback data for local render development when upstream content is incomplete.
- Keep production behavior unchanged unless the new local render mode is explicitly requested.

## Non-Goals

- Upload to YouTube.
- Auto-publish videos.
- Build analytics learning or content intelligence.
- Build a dashboard.
- Guarantee viral creative quality.
- Replace the existing full production pipeline.
- Rewrite the Remotion templates.

## Execution Mode

Add a new pipeline mode:

- `local_render`

This mode is different from `smoke`:

- `smoke` does not render and only validates orchestration.
- `local_render` should create or reuse enough local content data to produce a real video file.

`POST /api/pipeline/start` should accept:

```json
{
  "category": "Science",
  "language": "vi",
  "count": 1,
  "mode": "local_render"
}
```

## Local Render Flow

The worker routes `mode=local_render` to a pipeline method:

```python
async def run_local_render(
    self,
    *,
    category: str,
    language: str = "vi",
) -> dict[str, Any]:
```

The method should return:

```python
{
    "mode": "local_render",
    "category": "Science",
    "language": "vi",
    "topic_id": 123,
    "video_id": 456,
    "file_path": "/absolute/path/output/topics/123/final_video.mp4",
    "duration_sec": 90,
    "status": "rendered"
}
```

## Data Strategy

The local render path should be pragmatic. Its job is to prove renderability, not final creative quality.

Preferred behavior:

1. Try to use existing normal agents and database data when available.
2. If required upstream data is missing, create minimal fallback records or payloads needed for render.
3. Keep fallback behavior explicit and visible in the result summary.

Fallback content can include:

- A generated topic title based on category and language.
- A small script structure with intro cards and sections.
- Placeholder asset references compatible with existing Remotion templates.
- Silent or absent music when no music asset is available.

The fallback must not call YouTube upload. It should also avoid paid external calls unless the operator explicitly chooses a later production mode.

## Video Data Contract

Add a focused Python-side contract builder or validator for Remotion input.

It should validate that video data contains:

- `template`
- `title`
- `language`
- `cards` or equivalent section data expected by the selected composition
- stable image/audio path fields, even if empty

The contract should be unit-tested without invoking Remotion.

## Rendering

The first implementation should support two layers:

- Unit/integration tests that mock the expensive Remotion render call.
- Optional manual verification command that can run actual Remotion render when Node, dependencies, and FFmpeg are available.

If actual render dependencies are missing, automated tests should still pass because the contract and orchestration are verified without heavy external execution.

## Job Metadata

On local render success, worker `result_summary` should include a JSON string with:

- `mode`
- `category`
- `language`
- `topic_id`
- `video_id`
- `file_path`
- `duration_sec`
- `status`
- `fallback_used`

On failure, worker should clear `result_summary` and store a readable error.

## API Behavior

Existing `/api/pipeline/start` behavior remains the same, with `local_render` added to valid modes.

Invalid modes should still return `422`.

`GET /api/jobs/{job_id}` remains the primary way to inspect local render output through `result_summary`.

## Testing

Add focused tests for:

- `PipelineMode.LOCAL_RENDER` is accepted and queued by API.
- Worker routes `local_render` jobs to `Pipeline.run_local_render`.
- Worker stores local render `result_summary`.
- Pipeline local render returns a stable summary when render dependencies are mocked.
- Remotion video data contract builder/validator accepts valid data and rejects missing required fields.
- Existing smoke, dry-run, production-control, queue, and worker tests keep passing.

## Product Outcome

After this work, the operator should be able to run:

```bash
curl -X POST http://localhost:8000/api/pipeline/start \
  -H "Content-Type: application/json" \
  -d '{"category": "Science", "language": "vi", "count": 1, "mode": "local_render"}'
```

Then inspect:

```bash
curl http://localhost:8000/api/jobs/<job_id>
```

The result summary should point to a local rendered video file or provide a clear render error. This gives the project a concrete content artifact and prepares the next phase: YouTube upload v1.
