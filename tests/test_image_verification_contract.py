import pytest

from core.video_contract import (
    VideoContractError,
    apply_verified_images_to_video_data,
    build_image_verification_contract_v1,
    validate_image_verification_contract_v1,
)


def _verified_item(scene_index: int = 0) -> dict:
    return {
        "scene_index": scene_index,
        "person_name": "Celine Dion",
        "expected_title": "#10 Celine Dion",
        "status": "verified",
        "confidence": 0.95,
        "local_path": "/tmp/topic/images/real_0.webp",
        "render_image_path": "images/real_0.webp",
        "source_url": "https://commons.wikimedia.org/wiki/File:Celine_Dion.jpg",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
        "license": "CC BY-SA 4.0",
        "attribution": "Example photographer",
        "reject_reason": "",
    }


def test_build_image_verification_contract_v1_accepts_verified_items():
    contract = build_image_verification_contract_v1(
        topic_id=1,
        items=[_verified_item()],
    )

    validate_image_verification_contract_v1(contract)

    assert contract["schema_version"] == "image_verification_contract_v1"
    assert contract["source_policy"] == "wikimedia_commons_strict"
    assert contract["required_count"] == 1
    assert contract["verified_count"] == 1
    assert contract["status"] == "verified"


def test_validate_image_verification_contract_rejects_verified_item_without_source():
    item = _verified_item()
    item["source_url"] = ""
    contract = build_image_verification_contract_v1(topic_id=1, items=[item])

    with pytest.raises(VideoContractError, match="items\\[0\\].source_url is required"):
        validate_image_verification_contract_v1(contract)


def test_build_image_verification_contract_marks_missing_items_pending_review():
    missing = {
        "scene_index": 0,
        "person_name": "Celine Dion",
        "expected_title": "#10 Celine Dion",
        "status": "missing_image",
        "confidence": 0.0,
        "local_path": "",
        "render_image_path": "",
        "source_url": "",
        "image_url": "",
        "license": "",
        "attribution": "",
        "reject_reason": "no verified Wikimedia image found",
    }

    contract = build_image_verification_contract_v1(topic_id=1, items=[missing])
    validate_image_verification_contract_v1(contract)

    assert contract["verified_count"] == 0
    assert contract["status"] == "pending_review"


def test_apply_verified_images_to_video_data_preserves_template_and_replaces_images():
    contract = build_image_verification_contract_v1(topic_id=1, items=[_verified_item()])
    video_data = {
        "template": "timeline",
        "title": "Top 10",
        "subtitle": "Data comparison",
        "language": "vi",
        "cards": [
            {
                "header": "SCENE 1",
                "title": "#10 Celine Dion",
                "description": "Description",
                "imagePath": "images/local-placeholder.svg",
                "statusText": "#10 | 550M USD",
            }
        ],
        "introCards": [],
        "musicPath": "",
        "sfxPaths": {"transition": "", "alert": "", "reveal": ""},
        "logoPath": "images/local-logo.svg",
        "holdDurationFrames": 120,
        "transitionDurationFrames": 15,
    }

    result = apply_verified_images_to_video_data(video_data, contract)

    assert result["template"] == "timeline"
    assert result["cards"][0]["imagePath"] == "images/real_0.webp"
    assert result["cards"][0]["title"] == "#10 Celine Dion"
    assert result["image_verification_contract"] == contract


def test_apply_verified_images_rejects_pending_contract():
    missing = {
        "scene_index": 0,
        "person_name": "Celine Dion",
        "expected_title": "#10 Celine Dion",
        "status": "missing_image",
        "confidence": 0.0,
        "local_path": "",
        "render_image_path": "",
        "source_url": "",
        "image_url": "",
        "license": "",
        "attribution": "",
        "reject_reason": "no verified Wikimedia image found",
    }
    contract = build_image_verification_contract_v1(topic_id=1, items=[missing])
    video_data = {
        "template": "timeline",
        "title": "Top 10",
        "subtitle": "Data comparison",
        "language": "vi",
        "cards": [{"title": "#10 Celine Dion"}],
    }

    with pytest.raises(VideoContractError, match="image verification contract must be verified"):
        apply_verified_images_to_video_data(video_data, contract)
