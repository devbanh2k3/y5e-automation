#!/usr/bin/env python3
"""Build a reproducible baseline-versus-native render benchmark report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import get_settings
from services.render_encoder import probe_output, validate_probe_payload


def _probe_is_full_hd_landscape(probe: dict[str, Any]) -> bool:
    return (
        probe.get("width") == 1920
        and probe.get("height") == 1080
        and abs(float(probe.get("fps") or 0) - 30.0) <= 0.05
        and float(probe.get("duration") or 0) > 0
        and int(probe.get("size") or 0) > 0
    )


def build_report(
    *,
    baseline_seconds: float,
    native_seconds: float,
    baseline_probe: dict[str, Any],
    native_probe: dict[str, Any],
    encoder: str,
) -> dict[str, Any]:
    """Calculate performance metrics and the conservative rollout gate."""
    if baseline_seconds <= 0 or native_seconds <= 0:
        raise ValueError("benchmark durations must be positive")
    speedup = baseline_seconds / native_seconds
    reduction = (1 - native_seconds / baseline_seconds) * 100
    outputs_valid = _probe_is_full_hd_landscape(
        baseline_probe
    ) and _probe_is_full_hd_landscape(native_probe)
    return {
        "schema_version": "native_render_benchmark_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_seconds": round(baseline_seconds, 3),
        "native_seconds": round(native_seconds, 3),
        "speedup": round(speedup, 3),
        "time_reduction_percent": round(reduction, 2),
        "encoder": encoder,
        "baseline_probe": baseline_probe,
        "native_probe": native_probe,
        "outputs_valid": outputs_valid,
        "rollout_gate_passed": outputs_valid and reduction >= 40.0,
    }


def run_timed(command: list[str], *, cwd: Path) -> float:
    """Run one explicit benchmark command and return wall time."""
    started = time.monotonic()
    subprocess.run(command, cwd=cwd, check=True)
    return time.monotonic() - started


def _validated_probe(path: Path, expected_duration: float) -> dict[str, Any]:
    return validate_probe_payload(
        probe_output(path),
        expected_duration=expected_duration,
        require_audio=False,
    )


def _latest_topic_video_data() -> Path:
    topics = get_settings().storage_dir / "topics"
    candidates = list(topics.glob("*/video_data.json"))
    if not candidates:
        raise FileNotFoundError(f"no video_data.json found under {topics}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-topic", action="store_true")
    parser.add_argument("--video-data", type=Path)
    parser.add_argument("--baseline-output", type=Path, required=True)
    parser.add_argument("--native-output", type=Path, required=True)
    parser.add_argument("--baseline-seconds", type=float, required=True)
    parser.add_argument("--native-seconds", type=float, required=True)
    parser.add_argument("--encoder", default="auto")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if args.latest_topic == bool(args.video_data):
        parser.error("choose exactly one of --latest-topic or --video-data")
    video_data_path = _latest_topic_video_data() if args.latest_topic else args.video_data
    video_data = json.loads(video_data_path.read_text(encoding="utf-8"))
    expected_duration = float(
        video_data.get("targetDuration")
        or video_data.get("duration_target")
        or video_data.get("target_duration")
        or 0
    )
    if expected_duration <= 0:
        parser.error("video data does not contain a positive target duration")

    report = build_report(
        baseline_seconds=args.baseline_seconds,
        native_seconds=args.native_seconds,
        baseline_probe=_validated_probe(args.baseline_output, expected_duration),
        native_probe=_validated_probe(args.native_output, expected_duration),
        encoder=args.encoder,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"Baseline: {report['baseline_seconds']}s | Native: {report['native_seconds']}s | "
        f"Speedup: {report['speedup']}x | Reduction: {report['time_reduction_percent']}% | "
        f"Gate: {'PASS' if report['rollout_gate_passed'] else 'FAIL'}"
    )


if __name__ == "__main__":
    main()
