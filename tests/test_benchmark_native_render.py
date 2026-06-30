from scripts.benchmark_native_render import build_report


def _valid_probe() -> dict:
    return {
        "duration": 300.0,
        "fps": 30.0,
        "width": 1920,
        "height": 1080,
        "size": 1000000,
    }


def test_benchmark_report_calculates_reproducible_speedup() -> None:
    report = build_report(
        baseline_seconds=1200,
        native_seconds=600,
        baseline_probe=_valid_probe(),
        native_probe=_valid_probe(),
        encoder="h264_videotoolbox",
    )

    assert report["speedup"] == 2.0
    assert report["time_reduction_percent"] == 50.0
    assert report["rollout_gate_passed"] is True


def test_benchmark_gate_rejects_fast_but_invalid_output() -> None:
    invalid = {**_valid_probe(), "width": 1280}

    report = build_report(
        baseline_seconds=1200,
        native_seconds=400,
        baseline_probe=_valid_probe(),
        native_probe=invalid,
        encoder="h264_nvenc",
    )

    assert report["time_reduction_percent"] > 40
    assert report["rollout_gate_passed"] is False
