import pytest

from agents.pipeline import Pipeline
from core.job_models import PipelineMode


@pytest.mark.asyncio
async def test_run_smoke_returns_stable_no_side_effect_summary():
    pipeline = Pipeline()

    result = await pipeline.run_smoke(
        category="Science",
        language="vi",
        mode=PipelineMode.SMOKE.value,
    )

    assert result["mode"] == "smoke"
    assert result["category"] == "Science"
    assert result["language"] == "vi"
    assert result["side_effects"] == {
        "ai_calls": False,
        "render": False,
        "upload": False,
    }
    assert [step["name"] for step in result["steps"]] == [
        "topic",
        "research",
        "fact_check",
        "script",
        "assets",
        "render",
        "thumbnail",
        "upload",
    ]
    assert all(step["status"] == "skipped" for step in result["steps"])


@pytest.mark.asyncio
async def test_run_smoke_supports_dry_run_mode():
    pipeline = Pipeline()

    result = await pipeline.run_smoke(
        category="History",
        language="en",
        mode=PipelineMode.DRY_RUN.value,
    )

    assert result["mode"] == "dry_run"
    assert result["category"] == "History"
    assert result["language"] == "en"
    assert result["steps"][0]["reason"] == "dry_run mode"
