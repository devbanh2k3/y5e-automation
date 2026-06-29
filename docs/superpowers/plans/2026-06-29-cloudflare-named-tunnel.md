# Cloudflare Named Tunnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the production API permanently at `https://studio.veo3depzai.io.vn` through an automatically restarted Cloudflare Named Tunnel.

**Architecture:** Add the official `cloudflare/cloudflared` container to Docker Compose and run a remotely managed tunnel using a secret token from `.env`. Cloudflare owns the public-hostname route to `http://api:8000`; installers validate the token and stable URL, start the connector, and verify both local and public health endpoints.

**Tech Stack:** Docker Compose, Cloudflare Tunnel, Bash, PowerShell, pytest, Google OAuth 2.0

---

## File Structure

- Modify `docker-compose.yml`: define the production `cloudflared` connector and lifecycle dependency.
- Modify `.env.example`: document the stable public URL and secret tunnel token without including credentials.
- Modify `tests/test_docker_runtime_contract.py`: enforce the Compose tunnel contract.
- Modify `scripts/setup_wsl_production.sh`: validate tunnel configuration, start the connector, and verify public health.
- Modify `scripts/setup_windows_server.ps1`: show the required Cloudflare setup values to a new Windows operator.
- Modify `tests/test_production_installers.py`: enforce installer validation and startup behavior.
- Create `scripts/verify_named_tunnel.sh`: provide a repeatable production smoke check.
- Create `tests/test_named_tunnel_verifier.py`: validate the smoke script's interface and shell syntax.
- Modify `README.md`: replace Quick Tunnel instructions with the stable Named Tunnel workflow.
- Modify `docs/production-server-setup-full.md`: document Cloudflare dashboard, Google OAuth, deployment, rotation, and recovery steps.

### Task 1: Docker Named Tunnel Contract

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `tests/test_docker_runtime_contract.py`

- [ ] **Step 1: Write the failing Compose contract test**

Add this test to `tests/test_docker_runtime_contract.py`:

```python
def test_compose_runs_stable_cloudflare_named_tunnel() -> None:
    source = (ROOT / "docker-compose.yml").read_text()
    env_example = (ROOT / ".env.example").read_text()

    assert "cloudflared:" in source
    assert "image: cloudflare/cloudflared:latest" in source
    assert 'command: ["tunnel", "--no-autoupdate", "run"]' in source
    assert "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?" in source
    assert "condition: service_started" in source
    assert "CLOUDFLARE_TUNNEL_TOKEN=" in env_example
    assert "PUBLIC_BASE_URL=https://studio.veo3depzai.io.vn" in env_example
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
python3 -m pytest tests/test_docker_runtime_contract.py::test_compose_runs_stable_cloudflare_named_tunnel -q
```

Expected: FAIL because `cloudflared` and `CLOUDFLARE_TUNNEL_TOKEN` are not configured.

- [ ] **Step 3: Add the environment contract**

Change the public URL and add the empty secret in `.env.example`:

```dotenv
PUBLIC_BASE_URL=https://studio.veo3depzai.io.vn
CLOUDFLARE_TUNNEL_TOKEN=
```

- [ ] **Step 4: Add the Compose connector**

Add this service after `api` in `docker-compose.yml`:

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    command: ["tunnel", "--no-autoupdate", "run"]
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:?CLOUDFLARE_TUNNEL_TOKEN is required}
    depends_on:
      api:
        condition: service_started
```

The remotely managed Cloudflare route must target `http://api:8000`; no credential volume or account certificate is mounted.

- [ ] **Step 5: Validate Compose and run the contract tests**

Run:

```bash
CLOUDFLARE_TUNNEL_TOKEN=test-contract-token docker compose config --quiet
python3 -m pytest tests/test_docker_runtime_contract.py -q
```

Expected: Compose exits 0 when the local `.env` has a token, and all Docker runtime tests PASS.

- [ ] **Step 6: Commit the Docker contract**

```bash
git add .env.example docker-compose.yml tests/test_docker_runtime_contract.py
git commit -m "feat: add Cloudflare named tunnel service"
```

### Task 2: Production Installer Integration

**Files:**
- Modify: `scripts/setup_wsl_production.sh`
- Modify: `scripts/setup_windows_server.ps1`
- Modify: `tests/test_production_installers.py`

- [ ] **Step 1: Write failing installer assertions**

Extend the existing tests in `tests/test_production_installers.py`:

```python
def test_windows_server_setup_script_has_required_guards() -> None:
    # Keep the existing assertions.
    assert "CLOUDFLARE_TUNNEL_TOKEN" in text
    assert "studio.veo3depzai.io.vn" in text


def test_wsl_production_setup_script_has_required_deploy_steps() -> None:
    # Keep the existing assertions.
    assert "CLOUDFLARE_TUNNEL_TOKEN" in text
    assert "cloudflared" in text
    assert 'curl -fsS "${public_base_url}/api/health"' in text
```

- [ ] **Step 2: Run the installer tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_production_installers.py -q
```

Expected: FAIL because the installers do not require or start the Named Tunnel.

- [ ] **Step 3: Require tunnel configuration in WSL setup**

In `scripts/setup_wsl_production.sh`, add `CLOUDFLARE_TUNNEL_TOKEN` to both the generated `.env` guidance and `required` validation array. After the existing HTTPS check, enforce the selected hostname:

```bash
  if [[ "$(env_value PUBLIC_BASE_URL)" != "https://studio.veo3depzai.io.vn" ]]; then
    die "PUBLIC_BASE_URL must be https://studio.veo3depzai.io.vn"
  fi
```

- [ ] **Step 4: Start and verify the connector**

Include `cloudflared` in both branches of `start_stack`:

```bash
docker compose up -d api cloudflared telegram-bot production-worker youtube-upload-worker
```

and:

```bash
docker compose up -d --build api cloudflared telegram-bot production-worker youtube-upload-worker
```

After local API health succeeds, add public health verification:

```bash
  local public_base_url
  public_base_url="$(env_value PUBLIC_BASE_URL)"
  log "Checking Named Tunnel health at ${public_base_url}"
  until curl -fsS "${public_base_url}/api/health"; do
    if [[ "$index" -ge "$attempts" ]]; then
      docker compose logs --tail=80 cloudflared api || true
      die "Cloudflare Named Tunnel health check failed"
    fi
    index=$((index + 1))
    sleep 2
  done
```

Reset `index=1` before this second retry loop.

- [ ] **Step 5: Update Windows operator guidance**

Add these exact lines to `scripts/setup_windows_server.ps1`:

```powershell
Write-Host "CLOUDFLARE_TUNNEL_TOKEN"
Write-Host "Stable URL: https://studio.veo3depzai.io.vn"
Write-Host "OAuth callback: https://studio.veo3depzai.io.vn/api/youtube/oauth/callback"
```

- [ ] **Step 6: Verify installer behavior**

Run:

```bash
python3 -m pytest tests/test_production_installers.py -q
bash -n scripts/setup_wsl_production.sh
```

Expected: all installer tests PASS and Bash syntax exits 0.

- [ ] **Step 7: Commit installer integration**

```bash
git add scripts/setup_wsl_production.sh scripts/setup_windows_server.ps1 tests/test_production_installers.py
git commit -m "feat: deploy named tunnel with production stack"
```

### Task 3: Repeatable Tunnel Smoke Check

**Files:**
- Create: `scripts/verify_named_tunnel.sh`
- Create: `tests/test_named_tunnel_verifier.py`

- [ ] **Step 1: Write the failing verifier tests**

Create `tests/test_named_tunnel_verifier.py`:

```python
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_named_tunnel.sh"


def test_named_tunnel_verifier_checks_connector_and_public_health() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "docker compose ps --status running cloudflared" in source
    assert "https://studio.veo3depzai.io.vn/api/health" in source
    assert "docker compose logs --tail=80 cloudflared" in source


def test_named_tunnel_verifier_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_named_tunnel_verifier.py -q
```

Expected: FAIL because the verifier script does not exist.

- [ ] **Step 3: Implement the verifier**

Create `scripts/verify_named_tunnel.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

readonly PUBLIC_HEALTH_URL="https://studio.veo3depzai.io.vn/api/health"

if ! docker compose ps --status running cloudflared | grep -q cloudflared; then
  echo "cloudflared is not running" >&2
  docker compose logs --tail=80 cloudflared || true
  exit 1
fi

if ! curl --fail --silent --show-error --max-time 15 "$PUBLIC_HEALTH_URL" >/dev/null; then
  echo "Public tunnel health check failed: $PUBLIC_HEALTH_URL" >&2
  docker compose logs --tail=80 cloudflared api || true
  exit 1
fi

echo "Named Tunnel healthy: $PUBLIC_HEALTH_URL"
```

- [ ] **Step 4: Make the verifier executable and test it**

Run:

```bash
chmod +x scripts/verify_named_tunnel.sh
python3 -m pytest tests/test_named_tunnel_verifier.py -q
```

Expected: both tests PASS.

- [ ] **Step 5: Commit the verifier**

```bash
git add scripts/verify_named_tunnel.sh tests/test_named_tunnel_verifier.py
git commit -m "test: add named tunnel production smoke check"
```

### Task 4: Production Runbook and End-to-End Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/production-server-setup-full.md`
- Test: `tests/test_production_installers.py`
- Test: `tests/test_docker_runtime_contract.py`
- Test: `tests/test_named_tunnel_verifier.py`

- [ ] **Step 1: Replace Quick Tunnel instructions in README**

Document these operator actions with exact values:

```text
Cloudflare Dashboard -> Networking -> Tunnels -> Create tunnel
Name: youtube-automation-production
Public hostname: studio.veo3depzai.io.vn
Service: http://api:8000
PUBLIC_BASE_URL=https://studio.veo3depzai.io.vn
Authorized redirect URI:
https://studio.veo3depzai.io.vn/api/youtube/oauth/callback
```

State that only the `eyJ...` token value belongs in `.env`, and the token must never be committed.

- [ ] **Step 2: Update the full server runbook**

In `docs/production-server-setup-full.md`, replace the Quick Tunnel command and random URL workflow with:

```bash
docker compose up -d cloudflared
docker compose logs --tail=80 cloudflared
./scripts/verify_named_tunnel.sh
```

Add recovery procedures:

```bash
# Apply a rotated token from .env without restarting render or upload workers
docker compose up -d --force-recreate cloudflared

# Inspect connector failures
docker compose ps cloudflared
docker compose logs --since=10m cloudflared
```

- [ ] **Step 3: Run the focused test suite**

Run:

```bash
python3 -m pytest \
  tests/test_docker_runtime_contract.py \
  tests/test_production_installers.py \
  tests/test_named_tunnel_verifier.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 4: Validate repository and Compose configuration**

Run:

```bash
git diff --check
bash -n scripts/setup_wsl_production.sh scripts/verify_named_tunnel.sh
CLOUDFLARE_TUNNEL_TOKEN=test-contract-token docker compose config --quiet
```

Expected: all commands exit 0.

- [ ] **Step 5: Perform the live Cloudflare setup**

In Cloudflare, create the remotely managed tunnel and public hostname from Step 1. Put the token in local `.env`, then run:

```bash
docker compose up -d --force-recreate api cloudflared
./scripts/verify_named_tunnel.sh
```

Expected: the connector is running and the stable public health endpoint responds successfully.

- [ ] **Step 6: Verify Google OAuth callback configuration**

In Google Cloud, add exactly:

```text
https://studio.veo3depzai.io.vn/api/youtube/oauth/callback
```

Use Telegram `/channels`, choose **Add channel**, and complete OAuth. Expected: the callback returns to the API without a redirect URI mismatch and the connected channel appears for the requesting Telegram user.

- [ ] **Step 7: Commit documentation**

```bash
git add README.md docs/production-server-setup-full.md
git commit -m "docs: document stable Cloudflare tunnel operations"
```

- [ ] **Step 8: Final verification**

Run:

```bash
python3 -m pytest -q
docker compose ps
./scripts/verify_named_tunnel.sh
git status --short --branch
```

Expected: full tests PASS, `api` and `cloudflared` are running, public health succeeds, and the worktree is clean.
