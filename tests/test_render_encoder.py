import subprocess
from pathlib import Path

import pytest

from services import render_encoder

from services.render_encoder import (
    EncoderCapabilities,
    OutputValidationError,
    build_encode_command,
    select_encoder,
    validate_probe_payload,
)


def _probe(*, platform: str, working: set[str]) -> EncoderCapabilities:
    return EncoderCapabilities(platform=platform, working_encoders=frozenset(working))


def _valid_probe(**stream_overrides):
    stream = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30/1",
        "duration": "300.0",
    }
    stream.update(stream_overrides)
    return {
        "streams": [
            stream,
            {"codec_type": "audio", "codec_name": "aac", "duration": "300.0"},
        ],
        "format": {"duration": "300.0", "size": "1000000"},
    }


def test_macos_auto_prefers_verified_videotoolbox() -> None:
    selected = select_encoder(
        "auto",
        _probe(platform="darwin", working={"h264_videotoolbox", "libx264"}),
    )
    assert selected.name == "h264_videotoolbox"


def test_windows_auto_prefers_verified_nvenc() -> None:
    selected = select_encoder(
        "auto",
        _probe(platform="win32", working={"h264_nvenc", "libx264"}),
    )
    assert selected.name == "h264_nvenc"


def test_failed_hardware_probe_falls_back_to_x264() -> None:
    selected = select_encoder(
        "auto", _probe(platform="win32", working={"libx264"})
    )
    assert selected.name == "libx264"


def test_encoder_probe_uses_production_dimensions(monkeypatch) -> None:
    def fake_run(command, **_kwargs):
        source = command[command.index("-i") + 1]
        output = Path(command[-1])
        if "s=1920x1080" in source:
            output.write_bytes(b"probe")
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(render_encoder.subprocess, "run", fake_run)

    assert render_encoder._test_encoder("ffmpeg", "h264_nvenc") is True


def test_encode_command_uses_encoder_specific_quality(tmp_path) -> None:
    command = build_encode_command(
        input_path=tmp_path / "joined.mp4",
        output_path=tmp_path / "final.mp4",
        profile=select_encoder(
            "nvenc", _probe(platform="win32", working={"h264_nvenc"})
        ),
    )
    assert "h264_nvenc" in command
    assert "-cq" in command
    assert "+faststart" in command


def test_validation_rejects_wrong_dimensions() -> None:
    with pytest.raises(OutputValidationError, match="1920x1080"):
        validate_probe_payload(
            _valid_probe(width=1280, height=720), expected_duration=300
        )


def test_validation_accepts_youtube_ready_output() -> None:
    result = validate_probe_payload(
        _valid_probe(), expected_duration=300, require_audio=True
    )
    assert result["duration"] == 300.0
    assert result["fps"] == 30.0
