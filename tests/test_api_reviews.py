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
async def test_reject_review_endpoint_returns_409_for_non_pending(monkeypatch):
    async def fake_reject_review(review_id: str, reason: str = ""):
        raise ValueError("review is not pending")

    monkeypatch.setattr("api.main.reject_review", fake_reject_review)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/reviews/review-1/reject", json={"notes": "bad audio"})

    assert response.status_code == 409
