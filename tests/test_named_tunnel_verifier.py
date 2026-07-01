from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_named_tunnel.sh"


def _bash_path(path: Path) -> str:
    if path.drive:
        drive = path.drive.rstrip(":").lower()
        return f"/mnt/{drive}/{path.relative_to(path.anchor).as_posix()}"
    return path.as_posix()


def test_named_tunnel_verifier_checks_connector_and_public_health() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "docker compose ps --status running cloudflared" in source
    assert "https://studio.veo3depzai.io.vn/api/health" in source
    assert "docker compose logs --tail=80 cloudflared" in source


def test_named_tunnel_verifier_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", _bash_path(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
