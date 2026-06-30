from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_macos_installer_checks_videotoolbox_and_runner_dependencies() -> None:
    text = (ROOT / "scripts" / "setup_native_render_macos.sh").read_text()
    for required in (
        "set -Eeuo pipefail",
        "ffmpeg",
        "h264_videotoolbox",
        "ffprobe",
        "node",
        "python3",
        "native_render_runner.py",
        "redis",
    ):
        assert required in text
    assert "cp .env.example .env" not in text


def test_windows_installer_checks_nvenc_and_runner_dependencies() -> None:
    text = (ROOT / "scripts" / "setup_native_render_windows.ps1").read_text()
    for required in (
        "Set-StrictMode",
        "h264_nvenc",
        "nvidia-smi",
        "ffprobe",
        "node",
        "python",
        "native_render_runner.py",
        "redis",
    ):
        assert required in text
    assert "Copy-Item .env.example .env" not in text
