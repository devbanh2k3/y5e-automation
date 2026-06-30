from pathlib import Path

import pytest

from core.render_contract import NativeRenderRequest, RenderContractError


def _build_request(root: Path, **overrides) -> NativeRenderRequest:
    values = {
        "task_id": "task-1",
        "topic_id": "42",
        "output_root": root,
        "video_data_path": root / "topics" / "42" / "video_data.json",
        "output_path": root / "topics" / "42" / "final_video.mp4",
        "composition_id": "ComparisonVideo",
        "target_duration": 300,
    }
    values.update(overrides)
    return NativeRenderRequest.create(**values)


def test_render_request_confines_artifacts_to_output_root(tmp_path: Path) -> None:
    root = tmp_path / "output"
    request = _build_request(root)

    assert request.contract_version == 1
    assert request.target_duration == 300
    assert request.width == 1080
    assert request.height == 1920
    assert request.idempotency_key

    with pytest.raises(RenderContractError, match="outside output root"):
        _build_request(root, video_data_path=tmp_path / "secret.json")


def test_render_request_idempotency_changes_with_render_input(tmp_path: Path) -> None:
    root = tmp_path / "output"

    first = _build_request(root)
    same = _build_request(root)
    changed = _build_request(root, target_duration=305)

    assert same.idempotency_key == first.idempotency_key
    assert changed.idempotency_key != first.idempotency_key


def test_render_request_round_trips_json(tmp_path: Path) -> None:
    request = _build_request(tmp_path / "output")

    restored = NativeRenderRequest.model_validate_json(request.model_dump_json())

    assert restored == request
