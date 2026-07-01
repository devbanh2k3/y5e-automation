"""Hardware encoder selection and YouTube-ready output validation."""

from __future__ import annotations

import json
import platform as platform_module
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable


class OutputValidationError(ValueError):
    """Raised when the final MP4 is not structurally production-ready."""


@dataclass(frozen=True)
class EncoderCapabilities:
    platform: str
    working_encoders: frozenset[str]


@dataclass(frozen=True)
class EncoderProfile:
    name: str
    arguments: tuple[str, ...]


PROFILES = {
    "h264_videotoolbox": EncoderProfile(
        name="h264_videotoolbox",
        arguments=(
            "-c:v", "h264_videotoolbox", "-profile:v", "high",
            "-b:v", "12M", "-maxrate", "18M", "-bufsize", "24M",
        ),
    ),
    "h264_nvenc": EncoderProfile(
        name="h264_nvenc",
        arguments=(
            "-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq",
            "-rc", "vbr", "-cq", "20", "-b:v", "10M", "-maxrate", "18M",
        ),
    ),
    "libx264": EncoderProfile(
        name="libx264",
        arguments=("-c:v", "libx264", "-preset", "medium", "-crf", "20"),
    ),
}


def select_encoder(
    preference: str,
    capabilities: EncoderCapabilities,
    *,
    strict: bool = False,
) -> EncoderProfile:
    """Select only an encoder that passed a real capability probe."""
    preferred_names = {
        "videotoolbox": "h264_videotoolbox",
        "nvenc": "h264_nvenc",
        "cpu": "libx264",
    }
    if preference == "auto":
        if capabilities.platform.startswith("darwin"):
            candidates = ("h264_videotoolbox", "libx264")
        elif capabilities.platform.startswith("win"):
            candidates = ("h264_nvenc", "libx264")
        else:
            candidates = ("libx264",)
    else:
        requested = preferred_names.get(preference)
        if requested is None:
            raise ValueError(f"unsupported encoder preference: {preference}")
        candidates = (requested,) if strict else (requested, "libx264")

    for name in candidates:
        if name in capabilities.working_encoders:
            return PROFILES[name]
    raise RuntimeError(f"no working H.264 encoder for preference {preference}")


def _test_encoder(ffmpeg: str, encoder: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="native-render-encoder-") as directory:
        output = Path(directory) / "probe.mp4"
        result = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=30:d=0.2",
                "-an", "-c:v", encoder, "-pix_fmt", "yuv420p", str(output),
            ],
            capture_output=True,
            check=False,
            timeout=20,
        )
        return result.returncode == 0 and output.is_file() and output.stat().st_size > 0


def detect_encoder_capabilities(ffmpeg: str = "ffmpeg") -> EncoderCapabilities:
    """Probe advertised encoders and verify each candidate with a short encode."""
    listed = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if listed.returncode != 0:
        raise RuntimeError(f"ffmpeg encoder probe failed: {listed.stderr.strip()}")
    working = {
        name
        for name in PROFILES
        if name in listed.stdout and _test_encoder(ffmpeg, name)
    }
    return EncoderCapabilities(
        platform=platform_module.system().lower(),
        working_encoders=frozenset(working),
    )


def build_encode_command(
    *,
    input_path: Path,
    output_path: Path,
    profile: EncoderProfile,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """Build the final YouTube-compatible FFmpeg command."""
    return [
        ffmpeg, "-hide_banner", "-y", "-i", str(input_path),
        *profile.arguments,
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-map_metadata", "-1",
        str(output_path),
    ]


def probe_output(path: Path, ffprobe: str = "ffprobe") -> dict[str, Any]:
    """Return JSON stream metadata for an output file."""
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise OutputValidationError(f"ffprobe failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _first_stream(streams: Iterable[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((stream for stream in streams if stream.get("codec_type") == kind), None)


def validate_probe_payload(
    payload: dict[str, Any],
    *,
    expected_duration: float,
    require_audio: bool = False,
) -> dict[str, Any]:
    """Validate dimensions, codec, fps, duration, audio, and non-empty output."""
    streams = payload.get("streams") or []
    video = _first_stream(streams, "video")
    if not video:
        raise OutputValidationError("missing video stream")
    if video.get("codec_name") != "h264":
        raise OutputValidationError("video codec must be h264")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if (width, height) != (1920, 1080):
        raise OutputValidationError(f"output must be 1920x1080, got {width}x{height}")
    try:
        fps = float(Fraction(str(video.get("avg_frame_rate") or "0/1")))
    except (ValueError, ZeroDivisionError) as exc:
        raise OutputValidationError("invalid frame rate") from exc
    if abs(fps - 30.0) > 0.05:
        raise OutputValidationError(f"output must be 30 fps, got {fps:g}")
    duration = float(
        (payload.get("format") or {}).get("duration")
        or video.get("duration")
        or 0
    )
    tolerance = max(1.0, expected_duration * 0.02)
    if abs(duration - expected_duration) > tolerance:
        raise OutputValidationError(
            f"duration {duration:g}s differs from expected {expected_duration:g}s"
        )
    size = int((payload.get("format") or {}).get("size") or 0)
    if size <= 0:
        raise OutputValidationError("output file is empty")
    if require_audio and not _first_stream(streams, "audio"):
        raise OutputValidationError("missing required audio stream")
    return {"duration": duration, "fps": fps, "width": width, "height": height, "size": size}


def validate_output(
    path: Path,
    *,
    expected_duration: float,
    require_audio: bool = False,
    ffprobe: str = "ffprobe",
) -> dict[str, Any]:
    return validate_probe_payload(
        probe_output(path, ffprobe=ffprobe),
        expected_duration=expected_duration,
        require_audio=require_audio,
    )
