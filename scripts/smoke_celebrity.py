#!/usr/bin/env python3
"""Run an end-to-end Celebrity local render smoke through the API."""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]


def resolve_host_video_path(path_value: str) -> Path:
    """Map Docker container output paths to the host workspace output mount."""
    if path_value.startswith("/app/output/"):
        return ROOT_DIR / "output" / path_value.removeprefix("/app/output/")
    return Path(path_value).resolve()


def request_json(
    *,
    base_url: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc


def wait_until_ready(*, base_url: str, timeout_seconds: int = 60) -> None:
    """Wait until the API readiness endpoint answers successfully."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            ready = request_json(base_url=base_url, path="/api/ready", timeout=5)
            if ready.get("status") == "ready":
                return
        except (RuntimeError, urllib.error.URLError, http.client.RemoteDisconnected) as exc:
            last_error = exc
        time.sleep(1)
    raise TimeoutError(f"API did not become ready within {timeout_seconds}s: {last_error}")


def write_artifacts(*, review: dict[str, Any], result_summary: dict[str, Any]) -> dict[str, str]:
    video_path = resolve_host_video_path(str(result_summary["file_path"]))
    artifact_dir = video_path.parent
    artifact_dir.mkdir(parents=True, exist_ok=True)

    review_path = artifact_dir / "review.json"
    content_contract_path = artifact_dir / "content_contract.json"
    image_verification_contract_path = artifact_dir / "image_verification_contract.json"

    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2))
    content_contract_path.write_text(
        json.dumps(review.get("content_contract", {}), ensure_ascii=False, indent=2)
    )
    image_verification_contract_path.write_text(
        json.dumps(review.get("image_verification_contract", {}), ensure_ascii=False, indent=2)
    )

    return {
        "video_path": str(video_path),
        "review_path": str(review_path),
        "content_contract_path": str(content_contract_path),
        "image_verification_contract_path": str(image_verification_contract_path),
    }


def run_smoke(*, base_url: str, timeout_seconds: int, poll_seconds: float) -> dict[str, Any]:
    wait_until_ready(base_url=base_url)
    start_payload = {
        "category": "Celebrity",
        "language": "vi",
        "count": 1,
        "mode": "local_render",
    }
    start = request_json(
        base_url=base_url,
        path="/api/pipeline/start",
        method="POST",
        payload=start_payload,
    )
    job_id = start["job_id"]

    deadline = time.monotonic() + timeout_seconds
    job_path_template = "/api/jobs/{job_id}"
    while True:
        job = request_json(base_url=base_url, path=job_path_template.format(job_id=job_id))
        status = job.get("status")
        if status in {"completed", "failed"}:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Job {job_id} did not finish within {timeout_seconds}s")
        time.sleep(poll_seconds)

    if job.get("status") != "completed":
        raise RuntimeError(f"Celebrity smoke failed: {job.get('error', 'unknown error')}")

    result_summary = json.loads(job.get("result_summary") or "{}")
    review_id = result_summary.get("review_id")
    if not review_id:
        raise RuntimeError("Celebrity smoke completed without review_id")
    if result_summary.get("review_status") != "pending_review":
        raise RuntimeError(
            f"Expected pending_review, got {result_summary.get('review_status')}"
        )

    review_path_template = "/api/reviews/{review_id}"
    review = request_json(
        base_url=base_url,
        path=review_path_template.format(review_id=review_id),
    )
    artifacts = write_artifacts(review=review, result_summary=result_summary)

    return {
        "job_id": job_id,
        "review_id": review_id,
        "review_status": "pending_review",
        "topic_id": result_summary.get("topic_id"),
        "video_id": result_summary.get("video_id"),
        **artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()

    result = run_smoke(
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
