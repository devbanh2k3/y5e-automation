# Windows NVENC Runner Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correctly detect NVIDIA NVENC on Windows, run the host-native renderer, and prove a real production-path render uses `h264_nvenc` without Docker fallback.

**Architecture:** Keep the existing native-render queue and runner architecture unchanged. Fix only the FFmpeg capability probe dimensions, protect the behavior with a focused unit test, then validate the complete API-to-Redis-to-Windows-runner path with runtime evidence.

**Tech Stack:** Python 3.12, pytest, FFmpeg/NVENC, Redis, Docker Compose, Remotion, PowerShell

---

### Task 1: Add the NVENC probe regression test

**Files:**
- Modify: `tests/test_render_encoder.py`
- Test: `tests/test_render_encoder.py`

- [ ] **Step 1: Add a failing test that requires production dimensions**

Add a test around `_test_encoder` using a fake `subprocess.run`. The fake must inspect the lavfi input and return success only when it contains `s=1920x1080`; it must also create a non-empty output file so the test exercises the complete success condition.

```python
def test_encoder_probe_uses_production_dimensions(monkeypatch, tmp_path):
    def fake_run(command, **_kwargs):
        source = command[command.index("-i") + 1]
        output = Path(command[-1])
        if "s=1920x1080" in source:
            output.write_bytes(b"probe")
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(render_encoder.subprocess, "run", fake_run)

    assert render_encoder._test_encoder("ffmpeg", "h264_nvenc") is True
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_render_encoder.py::test_encoder_probe_uses_production_dimensions -v
```

Expected: FAIL because the current command contains `s=64x64`.

### Task 2: Fix the encoder probe

**Files:**
- Modify: `services/render_encoder.py:89`
- Test: `tests/test_render_encoder.py`

- [ ] **Step 1: Make the minimal production change**

Change only the lavfi source in `_test_encoder`:

```python
"color=c=black:s=1920x1080:r=30:d=0.2"
```

- [ ] **Step 2: Confirm GREEN on the focused test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_render_encoder.py::test_encoder_probe_uses_production_dimensions -v
```

Expected: PASS.

- [ ] **Step 3: Run the encoder and native-render suites**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_render_encoder.py tests\test_native_render_runner.py tests\test_native_render_installers.py -v
```

Expected: all tests PASS.

- [ ] **Step 4: Verify real hardware detection**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\native_render_runner.py --check
```

Expected JSON contains both `h264_nvenc` and `libx264` in `encoders`.

### Task 3: Start and verify the Windows native runner

**Files:**
- Runtime only; no repository files changed

- [ ] **Step 1: Ensure no duplicate native runner exists**

Query Windows processes whose command line contains `native_render_runner.py`. Continue only when zero runners exist; if one exists, reuse it rather than starting another.

- [ ] **Step 2: Launch the runner hidden for this session**

Run the repository virtual-environment Python with `scripts\native_render_runner.py` using `Start-Process -WindowStyle Hidden` from the repository root.

- [ ] **Step 3: Verify process and heartbeat**

Confirm the Windows process remains alive for at least 20 seconds. Query the existing render heartbeat through the application Redis helpers and verify the advertised capabilities contain:

```json
{"platform": "windows", "encoders": ["h264_nvenc", "libx264"]}
```

If the heartbeat is absent, stop before enqueueing a render and inspect runner stderr/logging.

### Task 4: Run one real render and prove the execution path

**Files:**
- Runtime output: `output/topics/<topic_id>/video.mp4`
- Runtime manifest: `output/topics/<topic_id>/render-cache/<key>/render-manifest.json`

- [ ] **Step 1: Submit one local-render job**

POST to `http://localhost:8000/api/pipeline/start`:

```json
{"category": "Science", "language": "vi", "count": 1, "mode": "local_render"}
```

Record the returned job ID.

- [ ] **Step 2: Poll to a terminal state**

Poll `GET /api/jobs/<job_id>` until `completed` or `failed`, using the configured render timeout. On failure, preserve and report the job error plus API, worker, production-worker, and native-runner evidence.

- [ ] **Step 3: Verify native NVENC result**

Inspect the native render result and `render-manifest.json`. Require:

```json
{"encoder": "h264_nvenc"}
```

Because `.env` has `NATIVE_RENDER_FALLBACK=error`, completion with this manifest proves the render ran on the Windows runner rather than Docker fallback.

- [ ] **Step 4: Probe the produced MP4**

Run `ffprobe` and require H.264 video, 1920x1080 dimensions, 30 fps, a positive duration, and a non-zero file size.

- [ ] **Step 5: Recheck service health**

Require `/api/ready` to return `ready`, all long-lived Compose services to remain up, and no new Telegram `409 Conflict` during the final observation window.

### Task 5: Final repository verification

**Files:**
- Modify: `services/render_encoder.py`
- Modify: `tests/test_render_encoder.py`

- [ ] **Step 1: Run the full Python test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: exit code 0 with zero failures.

- [ ] **Step 2: Review the diff**

Run `git diff --check` and inspect `git diff -- services/render_encoder.py tests/test_render_encoder.py`. The only production behavior change must be the probe dimensions.

- [ ] **Step 3: Commit when Git identity is available**

Stage only `services/render_encoder.py`, `tests/test_render_encoder.py`, the approved spec, and this plan. Commit with:

```text
fix: detect Windows NVENC with production probe
```

If Git author identity remains unset, leave the files staged and report that blocker without changing global Git configuration.
