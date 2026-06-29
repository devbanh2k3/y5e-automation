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
