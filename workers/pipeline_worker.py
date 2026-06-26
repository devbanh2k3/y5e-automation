from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from core.job_models import JobAction, JobStatus
from core.queue import close_queue, dequeue, init_queue, requeue, set_job_metadata

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PipelineWorker:
    def __init__(
        self,
        pipeline_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.pipeline_factory = pipeline_factory or self._default_pipeline_factory
        self._stop_requested = False

    @staticmethod
    def _default_pipeline_factory() -> Any:
        from agents.pipeline import Pipeline

        return Pipeline()

    def request_stop(self) -> None:
        self._stop_requested = True

    async def _fail_job(self, job_id: str, error: str) -> None:
        await set_job_metadata(
            job_id,
            status=JobStatus.FAILED.value,
            failed_at=utc_now(),
            error=error[:500],
            completed_at="",
        )

    @staticmethod
    def _validate_data(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("data must be an object")
        if not str(data.get("category", "")).strip():
            raise ValueError("category is required")
        return data

    async def process(self, envelope: dict[str, Any] | None) -> None:
        if envelope is None:
            return

        job_id = str(envelope.get("job_id", ""))
        if not job_id:
            logger.error("Dropping malformed envelope without job_id: %s", envelope)
            return

        action = str(envelope.get("action", ""))
        attempt = int(envelope.get("attempt", 0))
        max_attempts = int(envelope.get("max_attempts", 1))
        queue_name = str(envelope.get("queue", "pipeline"))

        started_at = utc_now()
        await set_job_metadata(
            job_id,
            status=JobStatus.PROCESSING.value,
            started_at=started_at,
            attempt=str(attempt),
            error="",
            completed_at="",
            failed_at="",
        )

        if action != JobAction.RUN_PIPELINE.value:
            await set_job_metadata(
                job_id,
                status=JobStatus.FAILED.value,
                failed_at=utc_now(),
                error=f"unsupported action: {action}",
            )
            return

        try:
            data = self._validate_data(envelope.get("data"))
        except ValueError as exc:
            await self._fail_job(job_id, str(exc))
            return

        pipeline = self.pipeline_factory()

        try:
            await pipeline.run_full(
                category=data["category"],
                language=data.get("language", "vi"),
            )
        except Exception as exc:
            if attempt + 1 < max_attempts:
                next_attempt = attempt + 1
                await set_job_metadata(
                    job_id,
                    status=JobStatus.QUEUED.value,
                    attempt=str(next_attempt),
                    error=str(exc)[:500],
                    completed_at="",
                    failed_at="",
                )
                await requeue(envelope, attempt=next_attempt)
                return

            await set_job_metadata(
                job_id,
                status=JobStatus.FAILED.value,
                failed_at=utc_now(),
                error=str(exc),
                completed_at="",
            )
            return

        await set_job_metadata(
            job_id,
            status=JobStatus.COMPLETED.value,
            completed_at=utc_now(),
            error="",
            failed_at="",
        )

    async def run_forever(self, queue_name: str = "pipeline") -> None:
        while not self._stop_requested:
            envelope = await dequeue(queue_name, timeout=1)
            await self.process(envelope)


async def _run_worker() -> None:
    from core.database import close_db, init_db

    await init_db()
    await init_queue()

    worker = PipelineWorker()
    loop = asyncio.get_running_loop()

    def handle_stop() -> None:
        logger.info("Stop requested for pipeline worker.")
        worker.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_stop)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: handle_stop())

    try:
        await worker.run_forever()
    finally:
        await close_queue()
        await close_db()


def main() -> None:
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
