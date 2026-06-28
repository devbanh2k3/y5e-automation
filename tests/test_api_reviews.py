import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app


@pytest.mark.asyncio
async def test_list_reviews_endpoint_returns_pending_reviews(monkeypatch):
    async def fake_list_reviews(*, status=None, limit=50):
        assert status == "pending_review"
        assert limit == 25
        return [
            {
                "review_id": "review-1",
                "status": "pending_review",
                "job_id": "job-1",
                "video": {"topic_id": 1, "video_id": 2, "file_path": "/tmp/video.mp4"},
                "content_contract": {},
                "youtube": {"title": "Title", "description": "Description", "tags": ["celebrity"]},
                "thumbnail_prompt": "thumbnail",
                "review_notes": "",
                "created_at": "2026-06-26T00:00:00+00:00",
                "updated_at": "2026-06-26T00:00:00+00:00",
            }
        ]

    monkeypatch.setattr("api.main.list_reviews", fake_list_reviews)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews?status=pending_review&limit=25")

    assert response.status_code == 200
    assert response.json()["reviews"][0]["review_id"] == "review-1"
    assert response.json()["reviews"][0]["youtube"]["title"] == "Title"


@pytest.mark.asyncio
async def test_get_review_endpoint_returns_detail(monkeypatch):
    async def fake_get_review(review_id: str):
        assert review_id == "review-1"
        return {
            "review_id": "review-1",
            "status": "pending_review",
            "job_id": "job-1",
            "video": {"topic_id": 1, "video_id": 2, "file_path": "/tmp/video.mp4"},
            "content_contract": {"title": "Video"},
            "youtube": {"title": "Title", "description": "Description", "tags": ["celebrity"]},
            "thumbnail_prompt": "thumbnail",
            "review_notes": "",
            "created_at": "2026-06-26T00:00:00+00:00",
            "updated_at": "2026-06-26T00:00:00+00:00",
        }

    monkeypatch.setattr("api.main.get_review", fake_get_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1")

    assert response.status_code == 200
    assert response.json()["content_contract"]["title"] == "Video"


@pytest.mark.asyncio
async def test_get_review_endpoint_returns_404(monkeypatch):
    async def fake_get_review(review_id: str):
        raise KeyError(review_id)

    monkeypatch.setattr("api.main.get_review", fake_get_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/missing")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_review_endpoint(monkeypatch):
    async def fake_approve_review(review_id: str, notes: str = ""):
        assert review_id == "review-1"
        assert notes == "looks good"
        return {
            "review_id": "review-1",
            "status": "approved",
            "job_id": "job-1",
            "video": {"topic_id": 1, "video_id": 2, "file_path": "/tmp/video.mp4"},
            "content_contract": {},
            "youtube": {"title": "Title", "description": "", "tags": []},
            "thumbnail_prompt": "",
            "review_notes": "looks good",
            "created_at": "2026-06-26T00:00:00+00:00",
            "updated_at": "2026-06-26T00:01:00+00:00",
        }

    monkeypatch.setattr("api.main.approve_review", fake_approve_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/reviews/review-1/approve", json={"notes": "looks good"})

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["review_notes"] == "looks good"


@pytest.mark.asyncio
async def test_select_review_metadata_endpoint(monkeypatch):
    captured = {}

    async def fake_select_review_metadata(review_id: str, **kwargs):
        captured["review_id"] = review_id
        captured.update(kwargs)
        return {
            "review_id": review_id,
            "status": "pending_review",
            "selected_metadata": {
                "title": "Better Curiosity Title",
                "description": "Better description.",
                "tags": ["celebrity", "data comparison"],
                "thumbnail_text": "UNREAL",
            },
            "youtube": {
                "title": "Better Curiosity Title",
                "description": "Better description.",
                "tags": ["celebrity", "data comparison"],
            },
        }

    monkeypatch.setattr("api.main.select_review_metadata", fake_select_review_metadata)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/review-1/metadata/select",
            json={
                "title_index": 1,
                "description_index": 1,
                "thumbnail_text_index": 0,
                "tags": ["celebrity", "ranking"],
            },
        )

    assert response.status_code == 200
    assert captured == {
        "review_id": "review-1",
        "title_index": 1,
        "description_index": 1,
        "thumbnail_text_index": 0,
        "tags": ["celebrity", "ranking"],
    }
    assert response.json()["youtube"]["title"] == "Better Curiosity Title"


@pytest.mark.asyncio
async def test_reject_review_endpoint_returns_409_for_non_pending(monkeypatch):
    async def fake_reject_review(review_id: str, reason: str = "", **kwargs):
        raise ValueError("review is not pending")

    monkeypatch.setattr("api.main.reject_review", fake_reject_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/reviews/review-1/reject", json={"notes": "bad audio"})

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_reject_review_endpoint_keeps_legacy_notes_compatible(monkeypatch):
    async def fake_reject_review(review_id: str, reason: str = "", **kwargs):
        assert review_id == "review-1"
        assert reason == "other"
        assert kwargs["notes"] == "bad audio"
        assert kwargs["scenes"] == []
        return {
            "review_id": "review-1",
            "status": "rejected",
            "job_id": "job-1",
            "video": {"topic_id": 1, "video_id": 2, "file_path": "/tmp/video.mp4"},
            "content_contract": {},
            "youtube": {"title": "Title", "description": "", "tags": []},
            "thumbnail_prompt": "",
            "review_notes": "bad audio",
            "reject_reason": "other",
            "rejected_scenes": [],
            "created_at": "2026-06-26T00:00:00+00:00",
            "updated_at": "2026-06-26T00:01:00+00:00",
        }

    monkeypatch.setattr("api.main.reject_review", fake_reject_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/reviews/review-1/reject", json={"notes": "bad audio"})

    assert response.status_code == 200
    assert response.json()["reject_reason"] == "other"


@pytest.mark.asyncio
async def test_review_ui_page_is_served():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/review-ui")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="review-app"' in response.text
    assert 'id="selectedMetadata"' in response.text


@pytest.mark.asyncio
async def test_review_ui_static_javascript_is_served():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/static/review-ui.js")

    assert response.status_code == 200
    assert "loadReviews" in response.text
    assert "renderMetadata" in response.text
    assert "selectMetadataVariant" in response.text
    assert "/metadata/select" in response.text


@pytest.mark.asyncio
async def test_review_video_endpoint_streams_review_file(monkeypatch, tmp_path):
    video_path = tmp_path / "final_video.mp4"
    video_path.write_bytes(b"mp4-bytes")

    async def fake_get_review(review_id: str):
        assert review_id == "review-1"
        return {
            "review_id": "review-1",
            "status": "pending_review",
            "video": {"file_path": str(video_path)},
        }

    monkeypatch.setattr("api.main.get_review", fake_get_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1/video")

    assert response.status_code == 200
    assert response.content == b"mp4-bytes"
    assert response.headers["content-type"] == "video/mp4"


@pytest.mark.asyncio
async def test_review_video_endpoint_returns_404_for_missing_file(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing.mp4"

    async def fake_get_review(review_id: str):
        return {
            "review_id": review_id,
            "status": "pending_review",
            "video": {"file_path": str(missing_path)},
        }

    monkeypatch.setattr("api.main.get_review", fake_get_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1/video")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_review_scene_image_endpoint_streams_verified_image(monkeypatch, tmp_path):
    image_path = tmp_path / "scene.webp"
    image_path.write_bytes(b"image-bytes")

    async def fake_get_review(review_id: str):
        return {
            "review_id": review_id,
            "image_verification_contract": {
                "items": [
                    {
                        "scene_index": 2,
                        "local_path": str(image_path),
                    }
                ]
            },
        }

    monkeypatch.setattr("api.main.get_review", fake_get_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1/images/2")

    assert response.status_code == 200
    assert response.content == b"image-bytes"


@pytest.mark.asyncio
async def test_review_scene_image_endpoint_returns_404_for_missing_scene(monkeypatch):
    async def fake_get_review(review_id: str):
        return {"review_id": review_id, "image_verification_contract": {"items": []}}

    monkeypatch.setattr("api.main.get_review", fake_get_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/reviews/review-1/images/9")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_regenerate_scene_endpoint_calls_service(monkeypatch):
    captured = {}

    async def fake_regenerate_wrong_image_scene(review_id: str, *, scene_index: int, rerender: bool):
        captured["review_id"] = review_id
        captured["scene_index"] = scene_index
        captured["rerender"] = rerender
        return {
            "review_id": review_id,
            "status": "pending_review",
            "video": {"file_path": "/tmp/final_video_r2.mp4"},
            "review_events": [
                {"event": "scene_regenerated", "scenes": [scene_index]},
                {"event": "video_rerendered", "scenes": [scene_index]},
            ],
        }

    monkeypatch.setattr(
        "api.main.regenerate_wrong_image_scene",
        fake_regenerate_wrong_image_scene,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/review-1/regenerate-scene",
            json={"scene": 3, "reason": "wrong_image", "rerender": True},
        )

    assert response.status_code == 200
    assert captured == {"review_id": "review-1", "scene_index": 3, "rerender": True}
    assert response.json()["video"]["file_path"] == "/tmp/final_video_r2.mp4"


@pytest.mark.asyncio
async def test_regenerate_scene_endpoint_rejects_unsupported_reason():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/review-1/regenerate-scene",
            json={"scene": 3, "reason": "bad_fact", "rerender": True},
        )

    assert response.status_code == 409
