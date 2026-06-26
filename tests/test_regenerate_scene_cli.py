import pytest

from core.config import get_settings
from core.reviews import create_review, get_review
from scripts.regenerate_scene import regenerate_wrong_image_scene


@pytest.fixture
def regenerate_storage(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    yield tmp_path
    get_settings.cache_clear()


def image_contract():
    return {
        "schema_version": "image_verification_contract_v1",
        "topic_id": 99,
        "source_policy": "wikimedia_commons_strict",
        "required_count": 2,
        "verified_count": 2,
        "status": "verified",
        "items": [
            {
                "scene_index": 0,
                "person_name": "Old One",
                "expected_title": "#2 Old One",
                "status": "verified",
                "confidence": 0.9,
                "local_path": "/tmp/old0.webp",
                "render_image_path": "images/real_0.webp",
                "source_url": "https://commons.wikimedia.org/wiki/File:Old0.jpg",
                "image_url": "https://upload.wikimedia.org/old0.jpg",
                "license": "CC BY 2.0",
                "attribution": "Old",
                "reject_reason": "",
            },
            {
                "scene_index": 1,
                "person_name": "Old Two",
                "expected_title": "#1 Old Two",
                "status": "verified",
                "confidence": 0.9,
                "local_path": "/tmp/old1.webp",
                "render_image_path": "images/real_1.webp",
                "source_url": "https://commons.wikimedia.org/wiki/File:Old1.jpg",
                "image_url": "https://upload.wikimedia.org/old1.jpg",
                "license": "CC BY 2.0",
                "attribution": "Old",
                "reject_reason": "",
            },
        ],
    }


async def create_regenerate_review():
    return await create_review(
        job_id="job-1",
        topic_id=99,
        video_id=99,
        file_path="/tmp/final.mp4",
        content_contract={
            "schema_version": "content_contract_v2",
            "scenes": [
                {"title": "#2 Old One", "voiceover": "one"},
                {"title": "#1 Old Two", "voiceover": "two"},
            ],
        },
        image_verification_contract=image_contract(),
        youtube_title="Title",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail",
    )


@pytest.mark.asyncio
async def test_regenerate_wrong_image_scene_replaces_only_selected_item(
    monkeypatch,
    regenerate_storage,
):
    review = await create_regenerate_review()

    class FakeRealImageAgent:
        async def run_for_content_contract(self, *, topic_id, content_contract, strict=True):
            assert topic_id == 99
            assert strict is True
            assert content_contract["scenes"][0]["title"] == "#1 Old Two"
            return {
                "schema_version": "image_verification_contract_v1",
                "topic_id": topic_id,
                "source_policy": "wikimedia_commons_strict",
                "required_count": 1,
                "verified_count": 1,
                "status": "verified",
                "items": [
                    {
                        "scene_index": 0,
                        "person_name": "Old Two",
                        "expected_title": "#1 Old Two",
                        "status": "verified",
                        "confidence": 0.9,
                        "local_path": "/tmp/new1.webp",
                        "render_image_path": "images/real_0.webp",
                        "source_url": "https://commons.wikimedia.org/wiki/File:New1.jpg",
                        "image_url": "https://upload.wikimedia.org/new1.jpg",
                        "license": "CC BY 2.0",
                        "attribution": "New",
                        "reject_reason": "",
                    }
                ],
            }

    monkeypatch.setattr("scripts.regenerate_scene.RealImageAgent", FakeRealImageAgent)

    updated = await regenerate_wrong_image_scene(review["review_id"], scene_index=1)

    items = updated["image_verification_contract"]["items"]
    assert items[0]["source_url"] == "https://commons.wikimedia.org/wiki/File:Old0.jpg"
    assert items[1]["scene_index"] == 1
    assert items[1]["source_url"] == "https://commons.wikimedia.org/wiki/File:New1.jpg"
    assert updated["review_events"][-1]["event"] == "scene_regenerated"
    assert updated["review_events"][-1]["reason"] == "wrong_image"
    assert updated["review_events"][-1]["scenes"] == [1]

    loaded = await get_review(review["review_id"])
    assert loaded["image_verification_contract"]["items"][1]["source_url"].endswith("New1.jpg")


@pytest.mark.asyncio
async def test_regenerate_scene_rejects_out_of_range_scene(regenerate_storage):
    review = await create_regenerate_review()

    with pytest.raises(ValueError, match="scene index is outside content contract"):
        await regenerate_wrong_image_scene(review["review_id"], scene_index=9)
