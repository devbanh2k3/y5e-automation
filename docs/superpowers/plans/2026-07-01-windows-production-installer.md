# Windows Production Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one idempotent PowerShell command that installs and validates every non-driver dependency required by the Windows Docker control plane and NVIDIA native renderer.

**Architecture:** A new top-level installer owns package installation, environment validation, Python/Node setup, Docker startup, NVENC verification, and optional native-runner scheduled-task registration. Existing focused setup scripts remain available, but the runbook points new Windows deployments to the unified installer.

**Tech Stack:** PowerShell 5.1+, winget, Git, Docker Desktop, Python 3.12, Node.js 20, FFmpeg, NVIDIA NVENC, pytest contract tests.

---

### Task 1: Define Installer Contract

**Files:**
- Modify: `tests/test_production_installers.py`

- [ ] Add a failing test requiring `scripts/install_windows_production.ps1`, strict mode, Administrator/winget checks, package IDs `Git.Git`, `Docker.DockerDesktop`, `Python.Python.3.12`, `OpenJS.NodeJS.LTS`, and `Gyan.FFmpeg`.
- [ ] Require `.venv`, `requirements.txt`, `npm ci`, `docker compose up -d --build`, `/api/ready`, `nvidia-smi`, `h264_nvenc`, `NATIVE_RENDER_FALLBACK`, `assets/audio/bgm`, and `Y5ENativeRenderRunner` in the script source.
- [ ] Run `python3 -m pytest tests/test_production_installers.py -q`; expect failure because the script does not exist.

### Task 2: Implement Unified Installer

**Files:**
- Create: `scripts/install_windows_production.ps1`
- Modify: `scripts/setup_native_render_windows.ps1`

- [ ] Implement parameters `-InstallTools`, `-InstallRunnerService`, and `-SkipStart` with strict error handling.
- [ ] Add idempotent winget package installation using `winget list --id` before `winget install`.
- [ ] Resolve installed commands from PATH and standard locations; stop with a rerun message when a terminal restart is required.
- [ ] Create `.env` only when absent, validate required production keys and native-only settings, and never print secret values.
- [ ] Create `.venv`, install Python requirements, run `npm ci`, verify Docker/NVIDIA/NVENC, warn if music is absent, start Compose, poll `/api/ready`, run native `--check`, and optionally register the scheduled task using `.venv\Scripts\python.exe`.
- [ ] Update `setup_native_render_windows.ps1` to prefer the repository virtualenv Python and use `npm ci`.
- [ ] Run installer contract tests; expect pass.

### Task 3: Document and Verify

**Files:**
- Modify: `docs/production-server-setup-full.md`
- Modify: `README.md`
- Test: `tests/test_production_installers.py`

- [ ] Replace the primary Windows setup command with `install_windows_production.ps1 -InstallTools` and document the rerun flow after tool installation/reboot.
- [ ] Document copying `.env` and licensed MP3 files separately because Git ignores them.
- [ ] Document foreground validation before `-InstallRunnerService` and native-only settings (`NATIVE_RENDER_ENABLED=true`, `NATIVE_RENDER_FALLBACK=error`).
- [ ] Run `python3 -m pytest tests/test_production_installers.py -q` and the full Python suite.
- [ ] Commit and push `main` so the command exists on the Windows clone.
