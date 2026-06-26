import pytest

from core.config import get_settings
from core.reviews import (
    ReviewStatus,
    approve_review,
    create_review,
    get_review,
    list_reviews,
    reject_review,
)


@pytest.fixture
def review_storage(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    yield tmp_path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_review_persists_pending_review(review_storage):
    review = await create_review(
        job_id="job-123",
        topic_id=1,
        video_id=2,
        file_path="/tmp/final_video.mp4",
        content_contract={"schema_version": "content_contract_v2", "title": "Video"},
        youtube_title="YouTube title",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail prompt",
    )

    loaded = await get_review(review["review_id"])

    assert loaded["review_id"] == review["review_id"]
    assert loaded["status"] == ReviewStatus.PENDING.value
    assert loaded["job_id"] == "job-123"
    assert loaded["video"]["file_path"] == "/tmp/final_video.mp4"
    assert loaded["youtube"]["title"] == "YouTube title"
    assert loaded["thumbnail_prompt"] == "thumbnail prompt"
    assert loaded["created_at"]
    assert loaded["updated_at"]


@pytest.mark.asyncio
async def test_list_reviews_filters_by_status(review_storage):
    first = await create_review(
        job_id="job-1",
        topic_id=1,
        video_id=1,
        file_path="/tmp/one.mp4",
        content_contract={},
        youtube_title="One",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )
    second = await create_review(
        job_id="job-2",
        topic_id=2,
        video_id=2,
        file_path="/tmp/two.mp4",
        content_contract={},
        youtube_title="Two",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )

    await approve_review(first["review_id"])

    pending = await list_reviews(status=ReviewStatus.PENDING.value)
    approved = await list_reviews(status=ReviewStatus.APPROVED.value)

    assert [review["review_id"] for review in pending] == [second["review_id"]]
    assert [review["review_id"] for review in approved] == [first["review_id"]]


@pytest.mark.asyncio
async def test_reject_review_blocks_later_approval(review_storage):
    review = await create_review(
        job_id="job-1",
        topic_id=1,
        video_id=1,
        file_path="/tmp/one.mp4",
        content_contract={},
        youtube_title="One",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )

    rejected = await reject_review(
        review["review_id"],
        reason="bad_text",
        notes="needs rewrite",
    )

    assert rejected["status"] == ReviewStatus.REJECTED.value
    assert rejected["review_notes"] == "needs rewrite"
    assert rejected["reject_reason"] == "bad_text"

    with pytest.raises(ValueError, match="review is not pending"):
        await approve_review(review["review_id"])


@pytest.mark.asyncio
async def test_approve_review_appends_review_event(review_storage):
    review = await create_review(
        job_id="job-1",
        topic_id=1,
        video_id=1,
        file_path="/tmp/one.mp4",
        content_contract={},
        youtube_title="One",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )

    approved = await approve_review(review["review_id"], notes="ready")

    assert approved["status"] == ReviewStatus.APPROVED.value
    assert approved["review_notes"] == "ready"
    assert approved["review_events"][-1]["event"] == "approved"
    assert approved["review_events"][-1]["notes"] == "ready"
    assert approved["review_events"][-1]["created_at"]


@pytest.mark.asyncio
async def test_reject_review_stores_structured_reason_and_scenes(review_storage):
    review = await create_review(
        job_id="job-1",
        topic_id=1,
        video_id=1,
        file_path="/tmp/one.mp4",
        content_contract={},
        youtube_title="One",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )

    rejected = await reject_review(
        review["review_id"],
        reason="wrong_image",
        scenes=[5],
        notes="wrong person image",
    )

    assert rejected["status"] == ReviewStatus.REJECTED.value
    assert rejected["reject_reason"] == "wrong_image"
    assert rejected["rejected_scenes"] == [5]
    assert rejected["review_notes"] == "wrong person image"
    assert rejected["review_events"][-1]["event"] == "rejected"
    assert rejected["review_events"][-1]["reason"] == "wrong_image"
    assert rejected["review_events"][-1]["scenes"] == [5]


@pytest.mark.asyncio
async def test_reject_review_requires_allowed_reason(review_storage):
    review = await create_review(
        job_id="job-1",
        topic_id=1,
        video_id=1,
        file_path="/tmp/one.mp4",
        content_contract={},
        youtube_title="One",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )

    with pytest.raises(ValueError, match="reject reason must be one of"):
        await reject_review(review["review_id"], reason="bad_reason")


@pytest.mark.asyncio
async def test_create_review_persists_image_verification_contract(review_storage):
    image_contract = {
        "schema_version": "image_verification_contract_v1",
        "topic_id": 1,
        "source_policy": "wikimedia_commons_strict",
        "required_count": 1,
        "verified_count": 1,
        "status": "verified",
        "items": [
            {
                "scene_index": 0,
                "person_name": "Celine Dion",
                "expected_title": "#10 Celine Dion",
                "status": "verified",
                "confidence": 0.9,
                "local_path": "/tmp/real_0.webp",
                "render_image_path": "images/real_0.webp",
                "source_url": "https://commons.wikimedia.org/wiki/File:Celine_Dion.jpg",
                "image_url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "Example photographer",
                "reject_reason": "",
            }
        ],
    }

    review = await create_review(
        job_id="job-123",
        topic_id=1,
        video_id=2,
        file_path="/tmp/final_video.mp4",
        content_contract={"schema_version": "content_contract_v2", "title": "Video"},
        image_verification_contract=image_contract,
        youtube_title="YouTube title",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail prompt",
    )

    loaded = await get_review(review["review_id"])

    assert loaded["image_verification_contract"] == image_contract
