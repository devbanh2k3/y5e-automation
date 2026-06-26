from __future__ import annotations

from pydantic import BaseModel

from core.config import get_settings
from core.database import fetchrow
from core.queue import get_redis


class ComponentCheck(BaseModel):
    status: str
    message: str = ""


class ReadinessResult(BaseModel):
    ok: bool
    checks: dict[str, ComponentCheck]


async def check_readiness() -> ReadinessResult:
    settings = get_settings()
    checks: dict[str, ComponentCheck] = {}

    try:
        await fetchrow("SELECT 1 AS ok")
        checks["database"] = ComponentCheck(status="ok")
    except Exception as exc:
        checks["database"] = ComponentCheck(status="error", message=str(exc)[:200])

    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = ComponentCheck(status="ok")
    except Exception as exc:
        checks["redis"] = ComponentCheck(status="error", message=str(exc)[:200])

    try:
        settings.storage_dir
        checks["storage"] = ComponentCheck(status="ok")
    except Exception as exc:
        checks["storage"] = ComponentCheck(status="error", message=str(exc)[:200])

    config_result = settings.validate_production_config()
    if config_result.ok:
        checks["config"] = ComponentCheck(status="ok")
    else:
        checks["config"] = ComponentCheck(
            status="error",
            message=", ".join(sorted(config_result.errors.keys())),
        )

    return ReadinessResult(
        ok=all(check.status == "ok" for check in checks.values()),
        checks=checks,
    )
