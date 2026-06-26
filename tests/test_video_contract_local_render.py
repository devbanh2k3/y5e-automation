import pytest

from core.video_contract import (
    VideoContractError,
    build_local_render_video_data,
    validate_video_data,
)


def test_build_local_render_video_data_returns_valid_payload():
    payload = build_local_render_video_data(
        title="Amazing Science Facts",
        category="Science",
        language="vi",
    )

    validate_video_data(payload)

    assert payload["template"] == "timeline"
    assert payload["title"] == "Amazing Science Facts"
    assert payload["language"] == "vi"
    assert payload["musicPath"] == ""
    assert len(payload["cards"]) >= 3
    assert payload["cards"][0]["title"]


def test_validate_video_data_rejects_missing_required_fields():
    payload = {
        "template": "timeline",
        "language": "vi",
        "cards": [],
        "musicPath": "",
        "logoPath": "",
    }

    with pytest.raises(VideoContractError, match="title is required"):
        validate_video_data(payload)


def test_validate_video_data_rejects_empty_cards():
    payload = build_local_render_video_data(
        title="Amazing Science Facts",
        category="Science",
        language="vi",
    )
    payload["cards"] = []

    with pytest.raises(VideoContractError, match="cards must contain at least one card"):
        validate_video_data(payload)
