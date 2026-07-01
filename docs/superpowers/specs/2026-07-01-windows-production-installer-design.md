# Windows Production Installer Design

## Objective

Provide one idempotent PowerShell entry point for preparing a new Windows NVIDIA production server without requiring the operator to install Python, Node.js, FFmpeg, Git, or Docker manually.

The installer runs the Docker control plane and native render runner from the same Windows checkout so both processes share the same `output` and Remotion asset paths.

## Entry Point

The supported command is:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\install_windows_production.ps1 -InstallTools
```

Optional switches support skipping application startup and registering the native runner as a scheduled task after validation.

## Tool Installation

The script requires Administrator privileges and `winget`. With `-InstallTools`, it installs or upgrades:

- Git for Windows;
- Docker Desktop;
- Python 3.12;
- Node.js 20 LTS;
- FFmpeg;
- NVIDIA driver tooling remains an operator-installed prerequisite because unattended GPU driver replacement can require model-specific choices and reboot.

After installation, the script refreshes command discovery from known installation paths where possible. If Docker Desktop, PATH changes, or Windows features require a reboot or a new terminal, it stops with a precise rerun instruction rather than continuing in a partial state.

## Project Setup

The script can operate from an existing checkout or clone `main` from the configured repository URL into a requested destination. It then:

1. verifies the checkout and branch;
2. creates `.env` from `.env.example` only when absent;
3. stops before startup when required secrets are missing;
4. creates a Python virtual environment at `.venv` and installs `requirements.txt`;
5. runs `npm ci` in `video_engine`;
6. verifies `ffmpeg`, `ffprobe`, Docker Compose, NVIDIA visibility, and `h264_nvenc`;
7. builds and starts the Docker control-plane services;
8. validates API readiness;
9. runs the native runner check and optionally registers its scheduled task.

The installer never writes secrets, overwrites `.env`, rotates tokens, or commits local files.

## Media Assets

Because MP3 files are intentionally ignored by Git, the installer checks `assets/audio/bgm` and warns clearly when no supported tracks exist. It prints the exact directory where the operator must copy licensed music before production.

The installer does not download music or include third-party media licenses.

## Runtime Architecture

Docker Desktop runs PostgreSQL, Redis, API, Telegram, production workers, uploader, and Cloudflare Tunnel. The native runner executes directly on Windows using the repository virtual environment and host NVIDIA NVENC.

Docker exposes Redis on `localhost:6380`. The host `.env` uses `REDIS_URL=redis://localhost:6380/0`, while Compose continues overriding container Redis URLs with `redis://redis:6379/0`.

Native rendering is required:

```dotenv
NATIVE_RENDER_ENABLED=true
NATIVE_RENDER_FALLBACK=error
NATIVE_RENDER_ENCODER=auto
```

## Failure Handling

- Missing Administrator access or `winget`: stop before modifying the machine.
- Tool installation requiring restart: report the exact next command and exit successfully without starting production.
- Docker daemon unavailable: start Docker Desktop, wait with a bounded timeout, then fail with diagnostics.
- Missing `.env` values: create the template if needed and stop with the missing variable names.
- NVIDIA/NVENC unavailable: stop native-runner setup; never silently configure Docker rendering.
- Dependency or health-check failure: preserve command output and return a nonzero exit code.
- Existing scheduled task: update it idempotently instead of creating duplicates.

## Verification

Automated contract tests verify that the installer includes every required package ID, strict PowerShell error handling, `.env` guards, virtual environment setup, npm setup, Docker startup, NVIDIA/NVENC checks, native-runner installation, API readiness, and music-folder warning.

Acceptance requires:

1. repeated execution does not overwrite secrets or duplicate services;
2. a clean Windows machine can install all non-driver prerequisites through one command;
3. Docker control-plane services become healthy;
4. native runner check succeeds with NVIDIA NVENC;
5. missing music is reported before the first production run;
6. setup documentation uses the unified installer as the primary Windows path.
