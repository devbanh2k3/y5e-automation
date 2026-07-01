from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_unified_windows_installer_covers_full_production_stack() -> None:
    script = ROOT / "scripts" / "install_windows_production.ps1"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")

    required = [
        "Set-StrictMode -Version Latest",
        '$ErrorActionPreference = "Stop"',
        "Administrator",
        "winget",
        "Git.Git",
        "Docker.DockerDesktop",
        "Python.Python.3.12",
        "OpenJS.NodeJS.LTS",
        "Gyan.FFmpeg",
        ".venv",
        "requirements.txt",
        "npm ci",
        "docker compose up -d --build",
        "/api/ready",
        "nvidia-smi",
        "h264_nvenc",
        "NATIVE_RENDER_FALLBACK",
        "assets\\audio\\bgm",
        "Y5ENativeRenderRunner",
    ]
    for value in required:
        assert value in text


def test_windows_server_setup_script_has_required_guards() -> None:
    script = ROOT / "scripts" / "setup_windows_server.ps1"
    text = script.read_text(encoding="utf-8")

    assert "Set-StrictMode -Version Latest" in text
    assert "$ErrorActionPreference = \"Stop\"" in text
    assert "wsl --install -d Ubuntu-24.04" in text
    assert "Docker Desktop" in text
    assert "winget" in text
    assert "setup_wsl_production.sh" in text
    assert "PUBLIC_BASE_URL" in text
    assert "YOUTUBE_TOKEN_ENCRYPTION_KEY" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN" in text
    assert "studio.veo3depzai.io.vn" in text


def test_wsl_production_setup_script_has_required_deploy_steps() -> None:
    script = ROOT / "scripts" / "setup_wsl_production.sh"
    text = script.read_text(encoding="utf-8")

    assert "set -Eeuo pipefail" in text
    assert "apt-get install" in text
    assert "git clone" in text
    assert "cp .env.example .env" in text
    assert "validate_env" in text
    assert "docker compose up -d --build" in text
    assert "curl -fsS http://localhost:8000/api/health" in text
    assert "docker compose ps" in text
    assert "TELEGRAM_BOT_TOKEN" in text
    assert "YOUTUBE_OAUTH_CLIENT_ID" in text
    assert "CLOUDFLARE_TUNNEL_TOKEN" in text
    assert "cloudflared" in text
    assert 'curl -fsS "${public_base_url}/api/health"' in text


def test_wsl_production_setup_script_is_valid_bash() -> None:
    import subprocess

    script = ROOT / "scripts" / "setup_wsl_production.sh"
    result = subprocess.run(["bash", "-n", str(script)], check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
