# Hybrid Native Render Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut long-form 1920x1080 Full HD landscape render time by moving rendering to a resumable native macOS/Windows runner with normalized assets, static card snapshots, bounded chunk parallelism, and VideoToolbox/NVENC encoding with CPU fallback.

**Architecture:** Docker remains the control plane and enqueues versioned render contracts in Redis. A host-native Python runner validates the contract, builds render derivatives, snapshots static card layers, renders deterministic frame chunks with Remotion, concatenates and encodes them with the best verified host encoder, validates the final MP4, and reports completion through Redis. The existing in-container renderer remains the rollout fallback.

**Tech Stack:** Python 3.12+, Pydantic Settings, Redis, Pillow, Remotion 4/React/TypeScript, Chromium, FFmpeg/ffprobe, pytest, Vitest, Bash, PowerShell.

---

## File Structure

- Create `core/render_contract.py`: versioned native render request/result models, path confinement, and deterministic idempotency key.
- Create `core/render_queue.py`: render queue, result polling, heartbeat, cancellation-safe status updates, and idempotent enqueue.
- Create `services/render_assets.py`: image normalization, baked blurred backgrounds, derivative manifest, and cache fingerprints.
- Create `services/render_chunks.py`: card-safe frame ranges, checkpoint hashes, chunk validation, concat list generation, and bounded concurrency decisions.
- Create `services/render_encoder.py`: FFmpeg capability probing, VideoToolbox/NVENC/CPU selection, encode command construction, and ffprobe validation.
- Create `scripts/native_render_runner.py`: native job claim, staged execution, retries, resume, metrics, and final status reporting.
- Create `scripts/benchmark_native_render.py`: repeatable old-vs-native benchmark report.
- Create `scripts/setup_native_render_macos.sh`: dependency checks and LaunchAgent installation guidance.
- Create `scripts/setup_native_render_windows.ps1`: dependency/NVIDIA checks and Windows service installation guidance.
- Create `video_engine/src/snapshot.tsx`: deterministic static card snapshot composition.
- Modify `video_engine/src/components/Card.tsx`: use pre-baked blur/snapshot assets when present while preserving current fallback.
- Modify `video_engine/src/types/video-data.ts`: optional derivative and snapshot fields.
- Modify `video_engine/src/index.tsx`: register snapshot composition.
- Modify `agents/pipeline.py`: select native enqueue/wait path or existing Docker fallback.
- Modify `core/config.py`, `.env.example`, and `docker-compose.yml`: render feature flags, shared-root settings, queue settings, and host Redis reachability.
- Modify `scripts/process_production_task.py`: report native render stages without exposing internal IDs.
- Modify `docs/production-server-setup-full.md`: Mac/Windows runner operations, benchmark, fallback, and recovery.
- Add focused tests under `tests/` and `video_engine/src/` for every unit above.

### Task 1: Versioned Render Contract and Configuration

**Files:**
- Create: `core/render_contract.py`
- Modify: `core/config.py`
- Modify: `.env.example`
- Test: `tests/test_render_contract.py`
- Test: `tests/test_config_validation.py`

- [ ] **Step 1: Write failing contract and configuration tests**

```python
def test_render_request_confines_artifacts_to_output_root(tmp_path):
    root = tmp_path / "output"
    request = NativeRenderRequest.create(
        task_id="task-1",
        topic_id="42",
        output_root=root,
        video_data_path=root / "topics/42/video_data.json",
        output_path=root / "topics/42/final_video.mp4",
        composition_id="ComparisonVideo",
        target_duration=300,
    )
    assert request.contract_version == 1
    assert request.target_duration == 300
    assert request.idempotency_key

    with pytest.raises(RenderContractError, match="outside output root"):
        NativeRenderRequest.create(
            task_id="task-1",
            topic_id="42",
            output_root=root,
            video_data_path=tmp_path / "secret.json",
            output_path=root / "topics/42/final_video.mp4",
            composition_id="ComparisonVideo",
            target_duration=300,
        )


def test_native_render_settings_are_bounded(monkeypatch):
    monkeypatch.setenv("NATIVE_RENDER_ENABLED", "true")
    monkeypatch.setenv("NATIVE_RENDER_CHUNK_SECONDS", "5")
    monkeypatch.setenv("NATIVE_RENDER_MAX_PARALLEL_CHUNKS", "99")
    settings = Settings(_env_file=None)
    assert settings.native_render_enabled is True
    assert settings.native_render_chunk_seconds == 30
    assert settings.native_render_max_parallel_chunks == 4
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest tests/test_render_contract.py tests/test_config_validation.py -q`

Expected: FAIL because `NativeRenderRequest` and native render settings do not exist.

- [ ] **Step 3: Implement the minimal models and bounded settings**

Implement immutable request/result models with explicit fields for contract version, paths, composition, dimensions, fps, target duration, chunk policy, quality policy, preferred encoder, attempts, timestamps, and idempotency key. Use `Path.resolve()` plus `relative_to()` for confinement. Add these settings with validators:

```python
native_render_enabled: bool = False
native_render_fallback: str = "docker"
native_render_queue: str = "native_render"
native_render_heartbeat_seconds: int = 15
native_render_heartbeat_timeout_seconds: int = 60
native_render_chunk_seconds: int = 40
native_render_max_parallel_chunks: int = 2
native_render_chunk_retries: int = 2
native_render_encoder: str = "auto"
native_render_encoder_strict: bool = False
native_render_result_timeout_per_target_second: int = 6
render_image_max_width: int = 1080
render_image_max_height: int = 1350
render_image_quality: int = 88
```

Document the same keys in `.env.example`, defaulting native rendering off and Docker fallback on.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/test_render_contract.py tests/test_config_validation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/render_contract.py core/config.py .env.example tests/test_render_contract.py tests/test_config_validation.py
git commit -m "feat: define native render contract"
```

### Task 2: Redis Render Queue, Heartbeat, and Result Protocol

**Files:**
- Create: `core/render_queue.py`
- Test: `tests/test_render_queue.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing queue protocol tests**

```python
@pytest.mark.asyncio
async def test_enqueue_is_idempotent_by_render_key(fake_redis, render_request):
    first = await enqueue_render(render_request)
    second = await enqueue_render(render_request)
    assert first == second
    assert await fake_redis.llen("queue:native_render") == 1


@pytest.mark.asyncio
async def test_runner_heartbeat_expires(fake_redis, monkeypatch):
    await publish_runner_heartbeat(
        runner_id="mac-studio",
        capabilities={"encoders": ["h264_videotoolbox"]},
        ttl_seconds=1,
    )
    assert await has_live_runner() is True
    await fake_redis.delete("render:runner:mac-studio")
    assert await has_live_runner() is False


@pytest.mark.asyncio
async def test_wait_for_result_returns_structured_failure(fake_redis, render_request):
    job_id = await enqueue_render(render_request)
    await complete_render(job_id, status="failed", error_code="chunk_failed", message="chunk 2")
    result = await wait_for_render_result(job_id, timeout_seconds=1)
    assert result.status == "failed"
    assert result.error_code == "chunk_failed"
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_render_queue.py -q`

Expected: FAIL because the render queue protocol does not exist.

- [ ] **Step 3: Implement Redis keys and atomic behavior**

Use these stable keys:

```text
queue:native_render
render:idempotency:{idempotency_key}
render:job:{job_id}
render:result:{job_id}
render:runner:{runner_id}
render:runners
```

Use `SET NX` for idempotency, `LPUSH/BRPOP` for FIFO queueing, hashes for state, TTL heartbeat keys, and bounded polling for results. Store only JSON-safe contract data and sanitized diagnostics.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_render_queue.py tests/test_queue.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/render_queue.py tests/test_render_queue.py tests/conftest.py
git commit -m "feat: add native render queue protocol"
```

### Task 3: Render Asset Normalization and Baked Effects

**Files:**
- Create: `services/render_assets.py`
- Test: `tests/test_render_assets.py`
- Modify: `agents/pipeline.py`

- [ ] **Step 1: Write failing image derivative tests**

```python
def test_portrait_derivatives_preserve_full_subject_and_bake_blur(tmp_path):
    source = tmp_path / "portrait.jpg"
    Image.new("RGB", (600, 1600), "red").save(source)
    result = normalize_card_image(
        source=source,
        cache_dir=tmp_path / "cache",
        max_size=(1080, 1350),
        quality=88,
        fit="contain",
    )
    with Image.open(result.foreground_path) as foreground:
        assert foreground.width <= 1080
        assert foreground.height <= 1350
        assert foreground.width / foreground.height == pytest.approx(600 / 1600, rel=0.02)
    with Image.open(result.background_path) as background:
        assert background.size == (1080, 1350)


def test_asset_manifest_reuses_unchanged_derivative(tmp_path):
    source = make_image(tmp_path / "person.jpg", size=(1200, 1600))
    first = build_render_asset_manifest([source], cache_dir=tmp_path / "cache")
    second = build_render_asset_manifest([source], cache_dir=tmp_path / "cache")
    assert second.items[0].fingerprint == first.items[0].fingerprint
    assert second.items[0].cache_hit is True
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_render_assets.py -q`

Expected: FAIL because normalization and manifests do not exist.

- [ ] **Step 3: Implement deterministic derivatives**

Apply EXIF transpose, RGB conversion, maximum dimensions, Lanczos resize, foreground `contain`, and one-time blurred cover background. Hash source bytes plus policy version. Save atomically under `output/topics/{topic_id}/render-cache/assets/`. Update render-only `video_data` with `normalizedImagePath` and `backgroundImagePath`; do not alter verified originals or attribution.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_render_assets.py tests/test_pipeline_local_render.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/render_assets.py agents/pipeline.py tests/test_render_assets.py tests/test_pipeline_local_render.py
git commit -m "perf: normalize render image assets"
```

### Task 4: Static Card Snapshot Path and CSS Cost Reduction

**Files:**
- Create: `video_engine/src/snapshot.tsx`
- Create: `video_engine/src/components/card-render-mode.test.ts`
- Modify: `video_engine/src/components/Card.tsx`
- Modify: `video_engine/src/types/video-data.ts`
- Modify: `video_engine/src/index.tsx`
- Modify: `video_engine/package.json`

- [ ] **Step 1: Write failing Vitest tests for derivative preference and fallback**

```typescript
import {describe, expect, it} from 'vitest';
import {resolveCardMedia} from './Card';

describe('resolveCardMedia', () => {
  it('uses snapshot and pre-baked background when supplied', () => {
    expect(resolveCardMedia({
      imagePath: 'images/original.webp',
      snapshotPath: 'render-cache/card-1.png',
      backgroundImagePath: 'render-cache/card-1-bg.webp',
    })).toEqual({
      foreground: 'render-cache/card-1.png',
      background: 'render-cache/card-1-bg.webp',
      needsCssBlur: false,
    });
  });

  it('keeps the current dynamic card fallback', () => {
    expect(resolveCardMedia({imagePath: 'images/original.webp'}).needsCssBlur).toBe(true);
  });
});
```

- [ ] **Step 2: Run and verify RED**

Run: `cd video_engine && npm test -- --run src/components/card-render-mode.test.ts`

Expected: FAIL because snapshot media resolution does not exist.

- [ ] **Step 3: Implement snapshot composition and cheap runtime path**

Add a `CardSnapshot` composition that renders one fully settled static card at its exact card dimensions. Add an npm command that invokes `remotion still` for a card index. The Python runner will call it once per unique card fingerprint and write PNG snapshots to the job cache. In normal video rendering, animate the snapshot container for scrolling/entrance while keeping only truly dynamic overlays in React. When no snapshot exists, retain current card rendering.

Replace per-frame `blur(18px)` backgrounds with `backgroundImagePath` when present. Keep text/layout semantics unchanged and do not remove transition animations.

Add these package scripts so the documented verification commands are executable:

```json
{
  "test": "vitest",
  "snapshot:card": "remotion still src/index.tsx CardSnapshot"
}
```

- [ ] **Step 4: Run TypeScript tests and build**

Run: `cd video_engine && npm test -- --run && npm run build`

Expected: PASS with no TypeScript errors.

- [ ] **Step 5: Render before/after stills for visual comparison**

Run: `cd video_engine && npx remotion still src/index.tsx CardSnapshot /tmp/card-snapshot.png --props=public/test_props.json`

Expected: a nonblank card image with readable text, complete subject, correct flag, and no clipping.

- [ ] **Step 6: Commit**

```bash
git add video_engine/src video_engine/package.json video_engine/package-lock.json
git commit -m "perf: add static card render path"
```

### Task 5: Chunk Planning, Checkpoints, and Resume

**Files:**
- Create: `services/render_chunks.py`
- Test: `tests/test_render_chunks.py`

- [ ] **Step 1: Write failing chunk boundary and checkpoint tests**

```python
def test_chunks_respect_hook_card_and_outro_boundaries():
    plan = plan_chunks(
        total_frames=9000,
        fps=30,
        target_chunk_seconds=40,
        protected_ranges=[(0, 360), (8760, 9000)],
        card_boundaries=list(range(360, 8761, 150)),
    )
    assert plan[0].start_frame == 0
    assert plan[-1].end_frame == 8999
    assert all(chunk.end_frame + 1 == following.start_frame for chunk, following in pairwise(plan))
    assert not any(boundary_splits_range(chunk.end_frame, (0, 360)) for chunk in plan)


def test_valid_checkpoint_is_reused_but_changed_assets_invalidate_it(tmp_path):
    first = checkpoint_key(video_hash="v1", asset_hash="a1", start_frame=0, end_frame=1199)
    same = checkpoint_key(video_hash="v1", asset_hash="a1", start_frame=0, end_frame=1199)
    changed = checkpoint_key(video_hash="v1", asset_hash="a2", start_frame=0, end_frame=1199)
    assert same == first
    assert changed != first
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_render_chunks.py -q`

Expected: FAIL because chunk planning does not exist.

- [ ] **Step 3: Implement deterministic card-safe plans**

Calculate frame ranges from the existing hook/card/outro timeline. Choose the nearest legal card boundary to 30-45 seconds. Fingerprint contract version, video data, asset manifest, source revision, quality, and frame range. Validate checkpoint existence with ffprobe metadata before reuse. Provide a semaphore-based concurrency helper bounded to `1..4` and available memory policy.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_render_chunks.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/render_chunks.py tests/test_render_chunks.py
git commit -m "feat: add resumable chunk render planning"
```

### Task 6: Hardware Encoder Detection and Final Validation

**Files:**
- Create: `services/render_encoder.py`
- Test: `tests/test_render_encoder.py`

- [ ] **Step 1: Write failing encoder selection tests**

```python
def test_macos_auto_prefers_verified_videotoolbox():
    probe = FakeProbe(platform="darwin", working={"h264_videotoolbox"})
    assert select_encoder("auto", probe).name == "h264_videotoolbox"


def test_windows_auto_prefers_verified_nvenc():
    probe = FakeProbe(platform="win32", working={"h264_nvenc"})
    assert select_encoder("auto", probe).name == "h264_nvenc"


def test_failed_hardware_probe_falls_back_to_x264():
    probe = FakeProbe(platform="win32", working={"libx264"})
    assert select_encoder("auto", probe).name == "libx264"


def test_validation_rejects_wrong_dimensions():
    with pytest.raises(OutputValidationError, match="1920x1080"):
        validate_probe_payload(make_probe(width=720, height=1280), expected_duration=300)
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_render_encoder.py -q`

Expected: FAIL because encoder probing and output validation do not exist.

- [ ] **Step 3: Implement real capability test and command profiles**

Probe `ffmpeg -encoders`, then run a one-second generated test encode before accepting hardware support. Build profiles for:

```text
VideoToolbox: -c:v h264_videotoolbox -profile:v high -b:v 12M -maxrate 18M -bufsize 24M
NVENC:        -c:v h264_nvenc -preset p5 -tune hq -rc vbr -cq 20 -b:v 10M -maxrate 18M
CPU:          -c:v libx264 -preset medium -crf 20
Common:       -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k -movflags +faststart -map_metadata -1
```

Parse `ffprobe -show_streams -show_format -of json` and require H.264, 1920x1080, 30 fps tolerance, expected duration tolerance, valid timestamps, and audio when configured.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_render_encoder.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/render_encoder.py tests/test_render_encoder.py
git commit -m "feat: select and validate hardware encoders"
```

### Task 7: Native Runner Orchestration

**Files:**
- Create: `scripts/native_render_runner.py`
- Test: `tests/test_native_render_runner.py`

- [ ] **Step 1: Write failing orchestration tests**

```python
@pytest.mark.asyncio
async def test_runner_reuses_completed_chunks_after_restart(runner_fixture):
    runner_fixture.complete_chunk(0)
    result = await runner_fixture.runner.process(runner_fixture.request)
    assert result.status == "completed"
    assert runner_fixture.rendered_chunk_indexes == [1, 2]
    assert result.metrics["reused_chunks"] == 1


@pytest.mark.asyncio
async def test_runner_retries_only_failed_chunk(runner_fixture):
    runner_fixture.fail_chunk_once(1)
    result = await runner_fixture.runner.process(runner_fixture.request)
    assert result.status == "completed"
    assert runner_fixture.attempts == {0: 1, 1: 2, 2: 1}


@pytest.mark.asyncio
async def test_runner_falls_back_when_hardware_encode_fails(runner_fixture):
    runner_fixture.fail_encoder("h264_nvenc")
    result = await runner_fixture.runner.process(runner_fixture.request)
    assert result.encoder == "libx264"
    assert result.status == "completed"
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_native_render_runner.py -q`

Expected: FAIL because runner orchestration does not exist.

- [ ] **Step 3: Implement staged runner with structured metrics**

Implement `NativeRenderRunner` with dependency-injected queue, subprocess runner, asset builder, chunk planner, encoder selector, and validator. Use `asyncio.create_subprocess_exec`, semaphores, duration-scaled timeouts, bounded stderr capture, atomic temporary outputs, and signal handling that stops claiming new jobs while allowing current subprocess cleanup.

The actual Remotion chunk command must include:

```python
[
    "npx", "remotion", "render", "src/index.tsx", composition_id,
    chunk_path, f"--props={props_json}", f"--frames={start}-{end}",
    "--codec=h264", f"--crf={crf}", f"--concurrency={remotion_concurrency}",
]
```

Write `render-manifest.json` containing stage timings, chunk attempts/reuse, encoder, output probe data, and sanitized failures.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_native_render_runner.py tests/test_render_chunks.py tests/test_render_encoder.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/native_render_runner.py tests/test_native_render_runner.py
git commit -m "feat: add resumable native render runner"
```

### Task 8: Pipeline Integration and Docker Fallback

**Files:**
- Modify: `agents/pipeline.py`
- Modify: `scripts/process_production_task.py`
- Modify: `docker-compose.yml`
- Test: `tests/test_pipeline_local_render.py`
- Test: `tests/test_process_production_task.py`

- [ ] **Step 1: Write failing selection and fallback tests**

```python
@pytest.mark.asyncio
async def test_pipeline_uses_live_native_runner_when_enabled(native_queue, video_data):
    pipeline = Pipeline()
    native_queue.set_live_runner(True)
    native_queue.complete_with("/output/topics/42/final_video.mp4")
    result = await pipeline._render_video(topic_id=42, video_data=video_data)
    assert result["renderer"] == "native"


@pytest.mark.asyncio
async def test_pipeline_falls_back_to_docker_without_live_runner(native_queue, video_data):
    native_queue.set_live_runner(False)
    result = await Pipeline()._render_video(topic_id=42, video_data=video_data)
    assert result["renderer"] == "docker"
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_pipeline_local_render.py tests/test_process_production_task.py -q`

Expected: FAIL because pipeline selection does not exist.

- [ ] **Step 3: Extract renderer selection without removing the current method**

Rename the existing implementation to `_render_docker_video()` and add `_render_video()` as the policy boundary. Native mode writes final `video_data.json`, enqueues exactly one contract, reports `render_queued/rendering_chunks/final_encoding`, waits with a duration-scaled deadline, and returns the same result shape as Docker rendering. Docker fallback remains default during rollout.

Expose host Redis from Compose only through an explicit bind/configuration documented for the deployment environment; do not publish Redis broadly by default. Mount output consistently so host and container resolve the same configured root mapping.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_pipeline_local_render.py tests/test_process_production_task.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/pipeline.py scripts/process_production_task.py docker-compose.yml tests/test_pipeline_local_render.py tests/test_process_production_task.py
git commit -m "feat: route renders through native runner"
```

### Task 9: Platform Setup and Operations

**Files:**
- Create: `scripts/setup_native_render_macos.sh`
- Create: `scripts/setup_native_render_windows.ps1`
- Modify: `scripts/setup_windows_server.ps1`
- Modify: `docs/production-server-setup-full.md`
- Test: `tests/test_native_render_installers.py`

- [ ] **Step 1: Write failing installer-content tests**

```python
def test_macos_installer_checks_videotoolbox_and_runner_dependencies():
    text = (ROOT / "scripts/setup_native_render_macos.sh").read_text()
    for required in ("ffmpeg", "h264_videotoolbox", "ffprobe", "node", "python3", "native_render_runner.py"):
        assert required in text


def test_windows_installer_checks_nvenc_and_runner_dependencies():
    text = (ROOT / "scripts/setup_native_render_windows.ps1").read_text()
    for required in ("Set-StrictMode", "h264_nvenc", "nvidia-smi", "ffprobe", "node", "python", "native_render_runner.py"):
        assert required in text
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_native_render_installers.py -q`

Expected: FAIL because the scripts do not exist.

- [ ] **Step 3: Implement idempotent dependency checks and service commands**

The scripts must fail with actionable messages, never overwrite `.env`, test the encoder with a one-second generated frame, verify Redis and shared output access, install Node dependencies, and print the exact foreground runner command. Add optional LaunchAgent/Windows service registration behind explicit flags.

Document startup, stop, logs, health, benchmark, checkpoint cleanup, Docker fallback, and Windows NVIDIA driver requirements in the production runbook.

- [ ] **Step 4: Validate syntax and tests**

Run: `bash -n scripts/setup_native_render_macos.sh`

Run: `pytest tests/test_native_render_installers.py tests/test_production_installers.py -q`

Expected: PASS. PowerShell syntax is additionally verified on the Windows target before production enablement.

- [ ] **Step 5: Commit**

```bash
git add scripts/setup_native_render_macos.sh scripts/setup_native_render_windows.ps1 scripts/setup_windows_server.ps1 docs/production-server-setup-full.md tests/test_native_render_installers.py
git commit -m "docs: add native render host setup"
```

### Task 10: Benchmark, Integration Smoke, and Rollout Gate

**Files:**
- Create: `scripts/benchmark_native_render.py`
- Test: `tests/test_benchmark_native_render.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing benchmark report tests**

```python
def test_benchmark_report_calculates_reproducible_speedup():
    report = build_report(
        baseline_seconds=1200,
        native_seconds=600,
        baseline_probe=valid_probe(),
        native_probe=valid_probe(),
        encoder="h264_videotoolbox",
    )
    assert report["speedup"] == 2.0
    assert report["time_reduction_percent"] == 50.0
    assert report["rollout_gate_passed"] is True
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_benchmark_native_render.py -q`

Expected: FAIL because benchmark reporting does not exist.

- [ ] **Step 3: Implement benchmark CLI and machine-readable report**

Accept one existing `video_data.json`, run baseline and native modes with the same assets/settings, validate both outputs, and write JSON plus a concise terminal table. The rollout gate requires valid output and at least 40% time reduction; it reports failure rather than silently enabling native mode.

- [ ] **Step 4: Run all automated verification**

Run: `pytest -q`

Run: `cd video_engine && npm test -- --run && npm run build`

Expected: all Python and TypeScript tests pass.

- [ ] **Step 5: Run macOS 1920x1080 smoke and benchmark**

Run: `python3 scripts/native_render_runner.py --check`

Run: `python3 scripts/benchmark_native_render.py --latest-topic --report output/benchmarks/native-render-macos.json`

Expected: validated MP4, reported encoder, no audio drift, no clipped subject, and measured baseline/native timings. Do not claim the 40% target until this command supplies evidence.

- [ ] **Step 6: Run Windows NVIDIA smoke before enabling Windows production**

Run on the Windows host:

```powershell
python scripts/native_render_runner.py --check
python scripts/benchmark_native_render.py --latest-topic --report output\benchmarks\native-render-windows.json
```

Expected: `h264_nvenc` passes the test encode, final MP4 validation passes, and the report records actual timing. If NVENC fails, CPU fallback must pass and the report must not claim NVENC verification.

- [ ] **Step 7: Commit**

```bash
git add scripts/benchmark_native_render.py tests/test_benchmark_native_render.py README.md
git commit -m "perf: add native render benchmark gate"
```

### Task 11: Final Review and Production Enablement

**Files:**
- Modify only files required by review findings.

- [ ] **Step 1: Run focused regression suites**

Run: `pytest tests/test_pipeline_local_render.py tests/test_render_contract.py tests/test_render_queue.py tests/test_render_assets.py tests/test_render_chunks.py tests/test_render_encoder.py tests/test_native_render_runner.py -q`

Expected: PASS.

- [ ] **Step 2: Run full verification again**

Run: `pytest -q`

Run: `cd video_engine && npm test -- --run && npm run build`

Run: `git diff --check`

Expected: all checks pass and no whitespace errors.

- [ ] **Step 3: Review rollout defaults**

Confirm committed defaults remain:

```dotenv
NATIVE_RENDER_ENABLED=false
NATIVE_RENDER_FALLBACK=docker
NATIVE_RENDER_ENCODER=auto
NATIVE_RENDER_MAX_PARALLEL_CHUNKS=2
```

Enable native rendering only in the deployment `.env` after the benchmark and visual review pass on that machine.

- [ ] **Step 4: Request code review and resolve findings**

Use `superpowers:requesting-code-review`. Address correctness, security, path confinement, subprocess cleanup, idempotency, checkpoint invalidation, and A/V synchronization findings before merge.

- [ ] **Step 5: Commit any review fixes**

```bash
git add -u
git commit -m "fix: harden native render rollout"
```
