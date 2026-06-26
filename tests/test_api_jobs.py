import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from core.job_models import JobAction, JobStatus, PipelineMode


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
            json={"category": "science", "language": "vi", "count": 1, "mode": "smoke"},
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"
    assert captured["queue_name"] == "pipeline"
    assert captured["action"] == JobAction.RUN_PIPELINE
    assert captured["job_data"] == {
        "category": "science",
        "language": "vi",
        "count": 1,
        "mode": PipelineMode.SMOKE.value,
    }
    assert "mode smoke" in response.json()["message"]


@pytest.mark.asyncio
async def test_start_pipeline_defaults_mode_to_production(monkeypatch: pytest.MonkeyPatch):
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
        captured["job_data"] = job_data
        return "job-123"

    monkeypatch.setattr("api.main.enqueue", fake_enqueue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pipeline/start",
            json={"category": "science", "language": "vi", "count": 1},
        )

    assert response.status_code == 200
    assert captured["job_data"]["mode"] == PipelineMode.PRODUCTION.value


@pytest.mark.asyncio
async def test_start_pipeline_rejects_invalid_mode():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pipeline/start",
            json={
                "category": "science",
                "language": "vi",
                "count": 1,
                "mode": "expensive_unknown_mode",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_start_pipeline_accepts_local_render_mode(monkeypatch: pytest.MonkeyPatch):
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
        return "job-local-render"

    monkeypatch.setattr("api.main.enqueue", fake_enqueue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/pipeline/start",
            json={
                "category": "Science",
                "language": "vi",
                "count": 1,
                "mode": "local_render",
            },
        )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-local-render"
    assert captured["queue_name"] == "pipeline"
    assert captured["action"] == JobAction.RUN_PIPELINE
    assert captured["job_data"] == {
        "category": "Science",
        "language": "vi",
        "count": 1,
        "mode": PipelineMode.LOCAL_RENDER.value,
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
            "result_summary": '{"mode":"smoke"}',
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
    assert response.json()["result_summary"] == '{"mode":"smoke"}'


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


@pytest.mark.asyncio
async def test_list_jobs_endpoint_returns_recent_jobs(monkeypatch: pytest.MonkeyPatch):
    async def fake_list_jobs(status=None, queue=None, limit=50):
        assert status is None
        assert queue is None
        assert limit == 50
        return [
            {
                "job_id": "job-123",
                "queue": "pipeline",
                "action": "run_pipeline",
                "status": "queued",
                "attempt": "0",
                "max_attempts": "3",
                "created_at": "2026-06-26T00:00:00+00:00",
            }
        ]

    monkeypatch.setattr("api.main.list_jobs", fake_list_jobs)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["jobs"][0]["job_id"] == "job-123"


@pytest.mark.asyncio
async def test_retry_job_endpoint_returns_409_for_non_failed_job(monkeypatch: pytest.MonkeyPatch):
    async def fake_retry_failed_job(job_id: str):
        raise ValueError("job is not failed")

    monkeypatch.setattr("api.main.retry_failed_job", fake_retry_failed_job)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/jobs/job-123/retry")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_retry_job_endpoint_requeues_failed_job(monkeypatch: pytest.MonkeyPatch):
    async def fake_retry_failed_job(job_id: str):
        assert job_id == "job-123"
        return job_id

    monkeypatch.setattr("api.main.retry_failed_job", fake_retry_failed_job)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/jobs/job-123/retry")

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"
    assert response.json()["status"] == JobStatus.QUEUED.value


@pytest.mark.asyncio
async def test_retry_job_endpoint_returns_404_for_unknown_job(monkeypatch: pytest.MonkeyPatch):
    async def fake_retry_failed_job(job_id: str):
        raise KeyError(job_id)

    monkeypatch.setattr("api.main.retry_failed_job", fake_retry_failed_job)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/jobs/missing/retry")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_queue_stats_endpoint(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_queue_stats(queue_names: list[str]):
        assert queue_names == ["pipeline", "channel_analysis"]
        return {
            "queues": {"pipeline": {"pending": 1}, "channel_analysis": {"pending": 0}},
            "statuses": {"queued": 1},
        }

    monkeypatch.setattr("api.main.get_queue_stats", fake_get_queue_stats)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/queues")

    assert response.status_code == 200
    assert response.json()["queues"]["pipeline"]["pending"] == 1
