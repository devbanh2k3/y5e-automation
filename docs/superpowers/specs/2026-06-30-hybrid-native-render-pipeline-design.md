# Hybrid Native Render Pipeline Design

## Purpose

Reduce production render time for long 1920x1080 Full HD landscape videos while preserving the existing visual template, content pipeline, review gate, and YouTube publishing flow. The system will keep API, Telegram, queue, and upload services in Docker while moving Remotion rendering to a native macOS or Windows runner that can use host resources and hardware video encoders directly.

The production target is a 40-65% reduction in end-to-end render time for a representative five-minute video, without lowering output resolution or introducing visible layout, animation, audio, or synchronization regressions.

## Scope

This increment includes:

- Render-oriented normalization of verified real images.
- Removal or replacement of expensive CSS effects that do not materially improve the template.
- A versioned render-job contract and Redis-backed native render queue.
- One cross-platform native runner implementation for macOS and Windows.
- Automatic encoder detection for Apple VideoToolbox, NVIDIA NVENC, and CPU fallback.
- Bounded parallel chunk rendering, checkpointing, retry, resume, concatenation, and final encoding.
- Output validation with `ffprobe` before review creation.
- Benchmark tooling and setup/runbook documentation for macOS and Windows NVIDIA systems.
- A controlled rollout that preserves the current Docker render path as fallback.

This increment excludes:

- Changes to content generation, fact verification, image identity verification, metadata generation, review, or upload behavior.
- Lower-resolution intermediate or final videos.
- AMD AMF and Intel Quick Sync-specific optimization.
- Distributed rendering across multiple physical machines.
- Dynamic autoscaling or cloud render infrastructure.
- Redesigning the current card layouts or animations.

## Decisions

- Docker remains the production control plane; the host-native process owns rendering only.
- The runner uses one shared Python orchestration implementation on macOS and Windows.
- Remotion still produces 1920x1080 landscape frames. Acceleration comes from native Chromium, normalized assets, cheaper effects, bounded chunk parallelism, and hardware final encoding.
- Static card content may be pre-rendered, but scrolling, card entrance, and transition animations remain dynamic.
- The current Docker render implementation remains available until the native path passes benchmark and smoke acceptance criteria.
- Hardware encoding is an optimization, not a requirement. Unsupported or failed hardware encoders fall back to `libx264` automatically.
- Completed chunks are reusable checkpoints and are not rendered again after a runner restart.

## Architecture

### Control Plane

The production worker continues to complete content creation, fact verification, real-image verification, video contract construction, and quality gates. Instead of starting Remotion inside the Docker container when native rendering is enabled, it creates a render job and waits for its terminal result.

The render job is placed on a dedicated Redis queue and references artifacts in the existing shared output directory. The control plane stores the render job ID on the production task so retries and restarts resolve the same render operation rather than creating duplicates.

Native rendering is enabled through configuration. If no native runner heartbeat is available, production either uses the existing Docker renderer or fails with an operationally clear error according to the configured fallback policy.

### Render Job Contract

The versioned job contract contains:

- Contract version and unique render job ID.
- Production task, topic, and owner references needed for traceability.
- Absolute or configured-root-relative paths to `video_data.json`, the topic directory, and requested output.
- Composition ID, resolution, frame rate, target duration, and template.
- Chunk duration target and maximum parallel chunk count.
- Quality settings, preferred encoder policy, and fallback policy.
- Attempt count, creation time, and an idempotency key.

The contract does not embed credentials, Telegram tokens, OAuth material, or image bytes. The runner rejects unsupported contract versions and paths outside the configured render/output roots.

### Native Runner

The runner is a long-lived host process installed by platform scripts. It performs these steps:

1. Advertise a heartbeat containing OS, CPU count, available memory, Remotion/Chromium availability, FFmpeg version, and detected encoders.
2. Claim one render job atomically from Redis.
3. Validate the job contract and required artifacts.
4. Normalize render assets into a job-specific cache.
5. Partition the composition into deterministic chunks.
6. Render missing chunks with bounded concurrency.
7. Validate every chunk and retry only failed chunks.
8. Concatenate chunks without introducing timeline gaps.
9. Perform final hardware-accelerated or CPU encoding when required.
10. Remove internal metadata, apply fast-start, validate the final MP4, and publish the result atomically.
11. Persist structured timing and encoder metrics, then mark the job complete.

The native runner does not generate content, search for images, approve reviews, or upload videos.

## Asset Normalization

Verified real images are decoded once before render and written to a job cache in WebP or JPEG using deterministic names. Normalization applies EXIF orientation, RGB conversion, bounded dimensions, and quality settings appropriate for the largest card image area.

The normalization policy preserves the current no-subject-loss behavior:

- Foreground portrait layouts use `contain` and a separately generated blurred background asset.
- Cover layouts use a controlled crop only where the existing card contract explicitly permits it.
- Images are never enlarged beyond a configured limit when the source is too small.
- The original verified image and attribution data remain unchanged; normalized files are render derivatives only.

Blurred backgrounds are generated once during normalization instead of applying a large CSS blur on every frame. Static shadows are simplified or baked into static assets where practical. Dynamic effects required for card movement remain in Remotion.

## Chunk Rendering

The runner divides the video at deterministic card-safe frame boundaries, targeting 30-45 seconds per chunk. Chunk boundaries must not split card entrance animations, the initial hook sequence, the final centered card hold, or the outro transition.

Each chunk is identified by a hash of:

- Render contract version.
- Relevant video data.
- Asset fingerprints.
- Composition and source version.
- Frame range and quality settings.

A chunk with a valid matching checkpoint is reused. Missing chunks render in parallel with a concurrency limit derived from configuration and available memory. The default is conservative: one or two Chromium render processes, independent from Remotion's per-render concurrency.

Each chunk is rendered with identical resolution, frame rate, pixel format, codec compatibility, and audio parameters. Concatenation uses FFmpeg's concat path without quality loss when streams match. A final transcode is performed only when required for hardware encoding, audio normalization, or stream compatibility.

## Encoder Selection

At startup and before the first production job, the runner probes FFmpeg's available encoders with a short test encode.

Selection order is:

- macOS: `h264_videotoolbox`, then `libx264`.
- Windows with NVIDIA: `h264_nvenc`, then `libx264`.
- Other environments: `libx264`.

Configuration can force `auto`, `videotoolbox`, `nvenc`, or `cpu`. Forced hardware mode still falls back to CPU unless strict mode is explicitly enabled.

Hardware profiles target YouTube-friendly H.264 High compatibility, `yuv420p`, 30 fps, AAC audio, and `+faststart`. Quality is controlled with encoder-appropriate settings rather than assuming x264 CRF maps directly to VideoToolbox or NVENC. The benchmark report records the exact selected encoder and arguments.

## Error Handling and Recovery

- Invalid contracts fail before rendering and return a structured non-retryable error.
- Missing or corrupt assets identify the affected card and fail before chunk execution.
- A chunk failure is retried up to two times with captured stderr and increasing delay.
- Hardware encoder failure triggers one hardware retry, then CPU fallback.
- Runner termination leaves completed chunk checkpoints intact.
- A resumed job validates checkpoints before reuse and renders only missing or invalid chunks.
- Final output is written to a temporary path and renamed atomically only after validation.
- The production task enters `pending_review` only after the native job reports a validated final MP4.
- Timeout values scale with target duration and chunk count; timeout does not falsely mark a job failed while a valid subprocess remains active.
- Logs use job and chunk display identifiers while keeping internal IDs available only in structured diagnostic fields.

If the native runner is unavailable, `NATIVE_RENDER_FALLBACK=docker` uses the current Docker path. `NATIVE_RENDER_FALLBACK=fail` leaves the task retryable and reports that no runner is available. Production defaults to Docker fallback during rollout.

## Output Validation

The runner uses `ffprobe` to require:

- A readable MP4 container.
- One H.264 video stream at 1920x1080 and 30 fps.
- Duration within a bounded tolerance of the requested timeline duration.
- A valid audio stream when background music is configured.
- No missing chunk duration or timestamp discontinuity.
- A non-trivial file size and no zero-length streams.

Validation failure prevents review creation and retains diagnostic artifacts. Successful validation writes a manifest containing timings, chunk reuse counts, encoder, output duration, dimensions, and file size.

## Configuration

The render control plane adds settings for:

- Native render enablement and fallback policy.
- Native render queue and heartbeat keys.
- Shared output root.
- Chunk target duration and maximum parallel chunks.
- Remotion concurrency per chunk.
- Preferred hardware encoder and strictness.
- Image normalization dimensions and quality.
- Chunk retry count, heartbeat timeout, and duration-scaled render timeout.
- Checkpoint retention and benchmark output paths.

Secrets remain in the Docker `.env`; the native runner receives only Redis connectivity and render-specific paths/settings. Setup documentation must explain the security implications of a Redis endpoint accessible from the host.

## Platform Setup

### macOS

The setup script verifies Node.js, Remotion dependencies, Chromium, Python, FFmpeg with VideoToolbox support, Redis connectivity, and output-directory permissions. It installs the runner as a LaunchAgent or provides an explicit foreground command for development.

### Windows NVIDIA

The PowerShell setup script verifies Node.js, Python, FFmpeg, NVIDIA driver availability, `h264_nvenc` test encoding, Redis connectivity, and output-directory permissions. It can register the runner as a Windows service or provide an explicit foreground command for initial testing.

The runner does not require NVIDIA Container Toolkit because rendering runs directly on the Windows host.

## Benchmark and Rollout

The benchmark command renders a representative fixture through both the existing Docker path and the native path. It records:

- Content-independent render wall time.
- Asset normalization time.
- Per-chunk render times and parallelism.
- Concatenation and final encode time.
- Peak process memory when available.
- Output duration, dimensions, encoder, bitrate, and size.

The native path is accepted when:

- The output passes all structural validation.
- Visual spot checks show no clipped subjects, broken flags, text overflow, missing animation, or audio drift.
- A representative five-minute render is at least 40% faster than the current measured baseline on the same machine, or the report explains a hardware-bound exception.
- Restart/resume reuses completed chunks.
- Hardware encoder failure successfully falls back to CPU.

Rollout stages are:

1. Benchmark-only with Docker remaining authoritative.
2. Native rendering for manual test jobs.
3. Native default with automatic Docker fallback.
4. Optional removal of Docker fallback only after stable production evidence.

## Testing

Unit tests cover:

- Render contract validation and path confinement.
- Platform and encoder selection.
- Hardware test failure and CPU fallback.
- Image normalization dimensions, orientation, and contain/crop policies.
- Card-safe chunk boundary calculation.
- Chunk fingerprint stability and invalidation.
- Timeout scaling and bounded concurrency.
- Checkpoint validation and resume behavior.
- Final `ffprobe` validation parsing.

Integration tests cover:

- Docker worker enqueueing and a fake native runner completing a job.
- Atomic job claiming and idempotent retries.
- Multi-chunk render, concat, and final MP4 validation using a short fixture.
- Runner restart after some chunks complete.
- Simulated NVENC/VideoToolbox failure followed by `libx264` success.
- Docker fallback when no native heartbeat exists.

Platform smoke tests render the same short 1920x1080 fixture on macOS and Windows NVIDIA. Windows hardware behavior cannot be claimed verified until the smoke test runs on the target NVIDIA machine.

## Acceptance Criteria

- Existing content, image verification, visual layouts, review, and upload workflows remain behaviorally compatible.
- The native runner processes render jobs without requiring the API, Telegram bot, or upload worker to run outside Docker.
- macOS selects working VideoToolbox when available and falls back to `libx264` when unavailable.
- Windows NVIDIA selects working NVENC when available and falls back to `libx264` when unavailable.
- Verified images are normalized once and rendered without losing the intended subject.
- Long videos render in reusable card-safe chunks with bounded parallelism.
- Restarting the runner does not re-render valid completed chunks.
- A failed chunk is retried independently and does not regenerate content, images, or successful chunks.
- Final MP4 output is 1920x1080, 30 fps, YouTube-compatible, duration-correct, and validated before review.
- The current Docker renderer remains a functional rollout fallback.
- Benchmark reports make speed claims reproducible on the same hardware.
- The representative five-minute benchmark meets the 40% improvement target before native rendering becomes the production default.
