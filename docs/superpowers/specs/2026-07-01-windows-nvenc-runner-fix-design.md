# Windows NVENC Runner Fix Design

## Goal

Make the Windows production renderer reliably detect and use NVIDIA NVENC, keep the native render runner active, and prove the selected render path with one real local render.

## Scope

- Replace the encoder capability probe's `64x64` source with a production-valid `1920x1080` source. The current small source is rejected by this NVIDIA GPU and incorrectly removes `h264_nvenc` from the working encoder set.
- Add a regression test that simulates an encoder requiring Full HD probe dimensions and fails when the probe remains `64x64`.
- Start the native render runner as a hidden Windows process for this session and verify its Redis heartbeat.
- Submit one real local-render job through the existing API/worker path.
- Verify the completed native render result and manifest report `h264_nvenc`, and verify the output is a valid 1920x1080 H.264 MP4.

## Out of Scope

- Telegram polling changes: the recent observation window contains no new `409 Conflict` errors.
- Installing the startup Scheduled Task: the current shell is not elevated. The runner can be registered at startup later from Administrator PowerShell.
- Dependency upgrades or npm vulnerability remediation.

## Implementation

The fix remains inside `services/render_encoder.py`; no renderer routing contract changes. The probe keeps its short duration but uses the same dimensions as production output. Tests will patch process execution at the FFmpeg boundary, inspect the generated probe command, and prove the dimensions are accepted.

After tests pass, the host runner will be launched with the repository virtual environment. Existing `NATIVE_RENDER_ENABLED=true` and `NATIVE_RENDER_FALLBACK=error` settings ensure a successful render cannot silently fall back to Docker.

## Verification

1. Run the focused encoder tests and the native-render test suite.
2. Run `native_render_runner.py --check`; expect `h264_nvenc` in `encoders`.
3. Start the runner and verify a fresh heartbeat advertises Windows and `h264_nvenc`.
4. Submit one `local_render` API job and wait for completion.
5. Inspect the render result/manifest for `encoder: h264_nvenc` and probe the MP4 for 1920x1080 H.264 at 30 fps.

## Failure Handling

If NVENC detection still fails, stop before rendering and report the FFmpeg probe error. If the runner heartbeat is absent, do not enqueue a native render. If the render fails, preserve logs and output cache for diagnosis; do not enable Docker fallback.
