import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from core.job_models import JobAction


@pytest.mark.asyncio
async def test_start_pipeline_enqueues_run_pipeline(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_enqueue(
        queue_name,
        job_data,
        *,
        action,
        max_attempts=3,
        attempt=0,
        job_id=None,
    ):
        captured["queue_name"] = queue_name
        captured["job_data"] = job_data
        captured["action"] = action
        captured["max_attempts"] = max_attempts
        captured["attempt"] = attempt
        captured["job_id"] = job_id
        return "job-123"

    monkeypatch.setattr("api.main.enqueue", fake_enqueue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pipeline/start",
            json={"category": "science", "language": "vi", "count": 1},
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"
    assert captured["queue_name"] == "pipeline"
    assert captured["action"] == JobAction.RUN_PIPELINE
    assert captured["job_data"] == {
        "category": "science",
        "language": "vi",
        "count": 1,
    }


@pytest.mark.asyncio
async def test_get_job_status_returns_metadata(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_job_metadata(job_id: str):
        return {
            "job_id": job_id,
            "queue": "pipeline",
            "action": "run_pipeline",
            "status": "queued",
            "attempt": "0",
            "max_attempts": "3",
            "created_at": "2026-06-26T00:00:00+00:00",
        }

    monkeypatch.setattr("api.main.get_job_metadata", fake_get_job_metadata)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/jobs/job-123")

    assert response.status_code == 200
    assert response.json()["action"] == "run_pipeline"
    assert response.json()["status"] == "queued"
    assert response.json()["attempt"] == "0"
    assert response.json()["max_attempts"] == "3"
    assert response.json()["started_at"] == ""
    assert response.json()["completed_at"] == ""
    assert response.json()["failed_at"] == ""
    assert response.json()["error"] == ""


@pytest.mark.asyncio
async def test_get_job_status_unknown_returns_404(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_job_metadata(job_id: str):
        return {}

    monkeypatch.setattr("api.main.get_job_metadata", fake_get_job_metadata)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/jobs/missing")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analyze_channel_enqueues_channel_analysis_action(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    async def fake_fetchrow(query: str, *args):
        if "SELECT id FROM reference_channels" in query:
            return {"id": 7}
        raise AssertionError(f"Unexpected query: {query}")

    async def fake_execute(query: str, *args):
        return None

    async def fake_enqueue(
        queue_name,
        job_data,
        *,
        action,
        max_attempts=3,
        attempt=0,
        job_id=None,
    ):
        captured["queue_name"] = queue_name
        captured["job_data"] = job_data
        captured["action"] = action
        return "job-chan-123"

    monkeypatch.setattr("api.main.fetchrow", fake_fetchrow)
    monkeypatch.setattr("api.main.execute", fake_execute)
    monkeypatch.setattr("api.main.enqueue", fake_enqueue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/channels/analyze",
            json={
                "channel_url": "https://youtube.com/@science",
                "channel_name": "Science Channel",
            },
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-chan-123"
    assert captured["queue_name"] == "channel_analysis"
    assert captured["action"] == JobAction.CHANNEL_ANALYSIS
    assert captured["job_data"]["channel_db_id"] == 7
    assert captured["job_data"]["channel_url"] == "https://youtube.com/@science"
    assert "requested_at" in captured["job_data"]
