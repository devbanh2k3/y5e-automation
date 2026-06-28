import pytest

from core.config import get_settings
from core.reviews import (
    ReviewStatus,
    approve_review,
    create_review,
    get_review,
    list_reviews,
    reject_review,
    select_review_metadata,
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
async def test_create_review_persists_quality_gate(review_storage):
    review = await create_review(
        job_id="job-123",
        topic_id=1,
        video_id=2,
        file_path="/tmp/final_video.mp4",
        content_contract={"schema_version": "content_contract_v2", "title": "Video"},
        quality_gate={"status": "passed", "checks": [{"name": "mp4", "status": "passed"}]},
        youtube_title="YouTube title",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail prompt",
    )

    loaded = await get_review(review["review_id"])

    assert loaded["quality_gate"]["status"] == "passed"


@pytest.mark.asyncio
async def test_create_review_persists_metadata_variants(review_storage):
    metadata_variants = {
        "schema_version": "metadata_variants_v1",
        "title_variants": [
            {
                "title": "Celebrity Numbers That Feel Unreal",
                "score_total": 92,
                "score_breakdown": {"search": 90},
            }
        ],
        "description_variants": ["Optimized description."],
        "tags": ["celebrity", "data comparison"],
        "thumbnail_text_suggestions": ["THE GAP"],
        "search_keywords": ["celebrity data"],
        "trend_angle": "celebrity data gap",
        "selected_metadata": {
            "title": "Celebrity Numbers That Feel Unreal",
            "description": "Optimized description.",
            "tags": ["celebrity", "data comparison"],
            "thumbnail_text": "THE GAP",
        },
    }

    review = await create_review(
        job_id="job-123",
        topic_id=1,
        video_id=2,
        file_path="/tmp/final_video.mp4",
        content_contract={"schema_version": "content_contract_v2", "title": "Video"},
        metadata_variants=metadata_variants,
        selected_metadata=metadata_variants["selected_metadata"],
        youtube_title="Celebrity Numbers That Feel Unreal",
        youtube_description="Optimized description.",
        youtube_tags=["celebrity", "data comparison"],
        thumbnail_prompt="thumbnail prompt",
    )

    loaded = await get_review(review["review_id"])

    assert loaded["metadata_variants"] == metadata_variants
    assert loaded["selected_metadata"]["title"] == "Celebrity Numbers That Feel Unreal"


@pytest.mark.asyncio
async def test_select_review_metadata_updates_youtube_fields(review_storage):
    review = await create_review(
        job_id="job-123",
        topic_id=1,
        video_id=2,
        file_path="/tmp/final_video.mp4",
        content_contract={"schema_version": "content_contract_v2", "title": "Video"},
        metadata_variants={
            "schema_version": "metadata_variants_v1",
            "title_variants": [
                {"title": "Original Title", "score_total": 70},
                {"title": "Better Curiosity Title", "score_total": 92},
            ],
            "description_variants": ["Original description.", "Better description."],
            "tags": ["celebrity", "data comparison"],
            "thumbnail_text_suggestions": ["THE GAP", "UNREAL"],
        },
        selected_metadata={
            "title": "Original Title",
            "description": "Original description.",
            "tags": ["celebrity"],
            "thumbnail_text": "THE GAP",
        },
        youtube_title="Original Title",
        youtube_description="Original description.",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail prompt",
    )

    updated = await select_review_metadata(
        review["review_id"],
        title_index=1,
        description_index=1,
        thumbnail_text_index=1,
    )

    assert updated["selected_metadata"]["title"] == "Better Curiosity Title"
    assert updated["selected_metadata"]["description"] == "Better description."
    assert updated["selected_metadata"]["thumbnail_text"] == "UNREAL"
    assert updated["selected_metadata"]["tags"] == ["celebrity", "data comparison"]
    assert updated["youtube"]["title"] == "Better Curiosity Title"
    assert updated["youtube"]["description"] == "Better description."
    assert updated["youtube"]["tags"] == ["celebrity", "data comparison"]
    assert updated["review_events"][-1]["event"] == "metadata_selected"


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
async def test_list_reviews_filters_quality_and_sorts_metadata_score(review_storage):
    low = await create_review(
        job_id="job-1",
        topic_id=1,
        video_id=1,
        file_path="/tmp/low.mp4",
        content_contract={},
        quality_gate={"status": "passed"},
        metadata_variants={"title_variants": [{"title": "Low", "score_total": 72}]},
        youtube_title="Low",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )
    failed = await create_review(
        job_id="job-2",
        topic_id=2,
        video_id=2,
        file_path="/tmp/failed.mp4",
        content_contract={},
        quality_gate={"status": "failed"},
        metadata_variants={"title_variants": [{"title": "Failed", "score_total": 99}]},
        youtube_title="Failed",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )
    high = await create_review(
        job_id="job-3",
        topic_id=3,
        video_id=3,
        file_path="/tmp/high.mp4",
        content_contract={},
        quality_gate={"status": "passed"},
        metadata_variants={"title_variants": [{"title": "High", "score_total": 94}]},
        youtube_title="High",
        youtube_description="",
        youtube_tags=[],
        thumbnail_prompt="",
    )

    reviews = await list_reviews(
        status=ReviewStatus.PENDING.value,
        quality_status="passed",
        sort="metadata_score_desc",
    )

    assert [review["review_id"] for review in reviews] == [
        high["review_id"],
        low["review_id"],
    ]
    assert failed["review_id"] not in [review["review_id"] for review in reviews]


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
async def test_reject_review_accepts_fact_and_video_reasons(review_storage):
    first = await create_review(
        job_id="job-1",
        topic_id=1,
        video_id=2,
        file_path="/tmp/final.mp4",
        content_contract={},
        youtube_title="Title",
        youtube_description="Description",
        youtube_tags=["tag"],
        thumbnail_prompt="thumbnail",
    )
    second = await create_review(
        job_id="job-2",
        topic_id=3,
        video_id=4,
        file_path="/tmp/final-2.mp4",
        content_contract={},
        youtube_title="Title 2",
        youtube_description="Description",
        youtube_tags=["tag"],
        thumbnail_prompt="thumbnail",
    )

    fact_rejected = await reject_review(first["review_id"], reason="bad_fact")
    video_rejected = await reject_review(second["review_id"], reason="bad_video")

    assert fact_rejected["reject_reason"] == "bad_fact"
    assert video_rejected["reject_reason"] == "bad_video"


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


@pytest.mark.asyncio
async def test_create_review_persists_fact_verification_contract(review_storage):
    fact_contract = {
        "schema_version": "fact_verification_contract_v1",
        "verification_policy": "ai_only_independent_pass",
        "status": "ai_verified",
        "required_count": 1,
        "verified_count": 1,
        "corrected_count": 0,
        "rejected_count": 0,
        "items": [
            {
                "scene_index": 0,
                "person_name": "Celine Dion",
                "metric_label": "NET WORTH",
                "original_value": "550M USD",
                "verified_value": "550M USD",
                "unit": "USD",
                "as_of": "2026",
                "status": "verified",
                "confidence": 0.92,
                "reason": "Public estimate check.",
                "knowledge_cutoff_risk": "medium",
            }
        ],
    }

    review = await create_review(
        job_id="job-123",
        topic_id=1,
        video_id=2,
        file_path="/tmp/final_video.mp4",
        content_contract={"schema_version": "content_contract_v2", "title": "Video"},
        fact_verification_contract=fact_contract,
        youtube_title="YouTube title",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail prompt",
    )

    loaded = await get_review(review["review_id"])

    assert loaded["fact_verification_contract"] == fact_contract
