# Review Gate CLI + Regenerate Scene MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CLI review loop for rendered videos and a wrong-image single-scene regeneration MVP.

**Architecture:** Extend `core.reviews` with additive structured review metadata, then build thin stdlib CLIs over that store. Scene regeneration will load an existing review, run `RealImageAgent` against a one-scene contract, replace only the selected image verification item, and persist the updated review without rerendering the MP4.

**Tech Stack:** Python stdlib `argparse`/`asyncio`/`json`, existing JSON review store, existing `RealImageAgent`, pytest.

---

## File Structure

- Modify `core/reviews.py`: structured reject metadata, event history, helper update APIs.
- Create `scripts/review_video.py`: CLI for list/show/approve/reject.
- Create `scripts/regenerate_scene.py`: CLI and reusable `regenerate_wrong_image_scene()` helper.
- Modify `tests/test_reviews.py`: review metadata/event tests.
- Create `tests/test_review_video_cli.py`: CLI tests for list/show/approve/reject.
- Create `tests/test_regenerate_scene_cli.py`: scene regeneration tests.

## Task 1: Structured Review Metadata

**Files:**
- Modify: `core/reviews.py`
- Test: `tests/test_reviews.py`

- [ ] **Step 1: Write failing tests for review events and structured reject**

Add tests to `tests/test_reviews.py`:

```python
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
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python3 -m pytest tests/test_reviews.py -q
```

Expected: FAIL because `reject_review()` does not accept `scenes`/`notes` and no event history exists.

- [ ] **Step 3: Implement minimal structured review metadata**

Update `core/reviews.py`:

```python
ALLOWED_REJECT_REASONS = {
    "wrong_image",
    "bad_text",
    "bad_layout",
    "bad_topic",
    "bad_metric",
    "other",
}
```

In `create_review()`, add:

```python
"reject_reason": "",
"rejected_scenes": [],
"review_events": [],
```

Change `approve_review()` to call `_transition_review()` with `event="approved"`.

Change `reject_review()` signature to:

```python
async def reject_review(
    review_id: str,
    reason: str = "",
    *,
    scenes: list[int] | None = None,
    notes: str = "",
) -> dict[str, Any]:
```

Validate `reason in ALLOWED_REJECT_REASONS`; store `reject_reason`, `rejected_scenes`, `review_notes`, and append a review event.

- [ ] **Step 4: Verify tests pass**

Run:

```bash
python3 -m pytest tests/test_reviews.py -q
```

Expected: PASS.

## Task 2: Review Gate CLI

**Files:**
- Create: `scripts/review_video.py`
- Test: `tests/test_review_video_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_review_video_cli.py`:

```python
import json
import subprocess
import sys

import pytest

from core.config import get_settings
from core.reviews import create_review


@pytest.fixture
def review_cli_env(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    yield tmp_path
    get_settings.cache_clear()


async def create_cli_review():
    return await create_review(
        job_id="job-1",
        topic_id=11,
        video_id=22,
        file_path="/tmp/final.mp4",
        content_contract={"title": "Video"},
        youtube_title="Title",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail",
    )


@pytest.mark.asyncio
async def test_review_cli_list_outputs_pending_summary(review_cli_env):
    review = await create_cli_review()

    result = subprocess.run(
        [sys.executable, "scripts/review_video.py", "list", "--status", "pending_review"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["reviews"][0]["review_id"] == review["review_id"]
    assert payload["reviews"][0]["title"] == "Title"
    assert payload["reviews"][0]["video_path"] == "/tmp/final.mp4"


@pytest.mark.asyncio
async def test_review_cli_show_outputs_full_review(review_cli_env):
    review = await create_cli_review()

    result = subprocess.run(
        [sys.executable, "scripts/review_video.py", "show", review["review_id"]],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["review_id"] == review["review_id"]
    assert payload["content_contract"]["title"] == "Video"


@pytest.mark.asyncio
async def test_review_cli_approve_updates_status(review_cli_env):
    review = await create_cli_review()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/review_video.py",
            "approve",
            review["review_id"],
            "--notes",
            "looks good",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "approved"
    assert payload["review_notes"] == "looks good"


@pytest.mark.asyncio
async def test_review_cli_reject_stores_reason_and_scene(review_cli_env):
    review = await create_cli_review()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/review_video.py",
            "reject",
            review["review_id"],
            "--reason",
            "wrong_image",
            "--scene",
            "5",
            "--notes",
            "wrong person",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "rejected"
    assert payload["reject_reason"] == "wrong_image"
    assert payload["rejected_scenes"] == [5]
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python3 -m pytest tests/test_review_video_cli.py -q
```

Expected: FAIL because `scripts/review_video.py` does not exist.

- [ ] **Step 3: Implement CLI**

Create `scripts/review_video.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from core.reviews import approve_review, get_review, list_reviews, reject_review


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def summarize_review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": review.get("review_id", ""),
        "status": review.get("status", ""),
        "title": (review.get("youtube") or {}).get("title", ""),
        "topic_id": (review.get("video") or {}).get("topic_id", ""),
        "video_path": (review.get("video") or {}).get("file_path", ""),
        "created_at": review.get("created_at", ""),
    }


async def run(args: argparse.Namespace) -> int:
    if args.command == "list":
        reviews = await list_reviews(status=args.status, limit=args.limit)
        print_json({"reviews": [summarize_review(review) for review in reviews]})
        return 0
    if args.command == "show":
        print_json(await get_review(args.review_id))
        return 0
    if args.command == "approve":
        print_json(await approve_review(args.review_id, notes=args.notes))
        return 0
    if args.command == "reject":
        print_json(
            await reject_review(
                args.review_id,
                reason=args.reason,
                scenes=args.scene,
                notes=args.notes,
            )
        )
        return 0
    raise ValueError(f"unsupported command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review rendered video artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--status", default="pending_review")
    list_parser.add_argument("--limit", type=int, default=10)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("review_id")

    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("review_id")
    approve_parser.add_argument("--notes", default="")

    reject_parser = subparsers.add_parser("reject")
    reject_parser.add_argument("review_id")
    reject_parser.add_argument("--reason", required=True)
    reject_parser.add_argument("--scene", type=int, action="append", default=[])
    reject_parser.add_argument("--notes", default="")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyError as exc:
        print(f"Review {exc.args[0]} not found", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Verify CLI tests pass**

Run:

```bash
python3 -m pytest tests/test_review_video_cli.py -q
```

Expected: PASS.

## Task 3: Regenerate Wrong-Image Scene CLI

**Files:**
- Create: `scripts/regenerate_scene.py`
- Test: `tests/test_regenerate_scene_cli.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_regenerate_scene_cli.py`:

```python
import pytest

from core.config import get_settings
from core.reviews import create_review, get_review
from scripts.regenerate_scene import regenerate_wrong_image_scene, run


@pytest.fixture
def regenerate_storage(monkeypatch, tmp_path):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    yield tmp_path
    get_settings.cache_clear()


def image_contract():
    return {
        "schema_version": "image_verification_contract_v1",
        "topic_id": 99,
        "source_policy": "wikimedia_commons_strict",
        "required_count": 2,
        "verified_count": 2,
        "status": "verified",
        "items": [
            {
                "scene_index": 0,
                "person_name": "Old One",
                "expected_title": "#2 Old One",
                "status": "verified",
                "confidence": 0.9,
                "local_path": "/tmp/old0.webp",
                "render_image_path": "images/real_0.webp",
                "source_url": "https://commons.wikimedia.org/wiki/File:Old0.jpg",
                "image_url": "https://upload.wikimedia.org/old0.jpg",
                "license": "CC BY 2.0",
                "attribution": "Old",
                "reject_reason": "",
            },
            {
                "scene_index": 1,
                "person_name": "Old Two",
                "expected_title": "#1 Old Two",
                "status": "verified",
                "confidence": 0.9,
                "local_path": "/tmp/old1.webp",
                "render_image_path": "images/real_1.webp",
                "source_url": "https://commons.wikimedia.org/wiki/File:Old1.jpg",
                "image_url": "https://upload.wikimedia.org/old1.jpg",
                "license": "CC BY 2.0",
                "attribution": "Old",
                "reject_reason": "",
            },
        ],
    }


async def create_regenerate_review():
    return await create_review(
        job_id="job-1",
        topic_id=99,
        video_id=99,
        file_path="/tmp/final.mp4",
        content_contract={
            "schema_version": "content_contract_v2",
            "scenes": [
                {"title": "#2 Old One", "voiceover": "one"},
                {"title": "#1 Old Two", "voiceover": "two"},
            ],
        },
        image_verification_contract=image_contract(),
        youtube_title="Title",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        thumbnail_prompt="thumbnail",
    )


@pytest.mark.asyncio
async def test_regenerate_wrong_image_scene_replaces_only_selected_item(monkeypatch, regenerate_storage):
    review = await create_regenerate_review()

    class FakeRealImageAgent:
        async def run_for_content_contract(self, *, topic_id, content_contract, strict=True):
            assert topic_id == 99
            assert strict is True
            assert content_contract["scenes"][0]["title"] == "#1 Old Two"
            return {
                "schema_version": "image_verification_contract_v1",
                "topic_id": topic_id,
                "source_policy": "wikimedia_commons_strict",
                "required_count": 1,
                "verified_count": 1,
                "status": "verified",
                "items": [
                    {
                        "scene_index": 0,
                        "person_name": "Old Two",
                        "expected_title": "#1 Old Two",
                        "status": "verified",
                        "confidence": 0.9,
                        "local_path": "/tmp/new1.webp",
                        "render_image_path": "images/real_0.webp",
                        "source_url": "https://commons.wikimedia.org/wiki/File:New1.jpg",
                        "image_url": "https://upload.wikimedia.org/new1.jpg",
                        "license": "CC BY 2.0",
                        "attribution": "New",
                        "reject_reason": "",
                    }
                ],
            }

    monkeypatch.setattr("scripts.regenerate_scene.RealImageAgent", FakeRealImageAgent)

    updated = await regenerate_wrong_image_scene(review["review_id"], scene_index=1)

    items = updated["image_verification_contract"]["items"]
    assert items[0]["source_url"] == "https://commons.wikimedia.org/wiki/File:Old0.jpg"
    assert items[1]["scene_index"] == 1
    assert items[1]["source_url"] == "https://commons.wikimedia.org/wiki/File:New1.jpg"
    assert updated["review_events"][-1]["event"] == "scene_regenerated"
    assert updated["review_events"][-1]["reason"] == "wrong_image"
    assert updated["review_events"][-1]["scenes"] == [1]

    loaded = await get_review(review["review_id"])
    assert loaded["image_verification_contract"]["items"][1]["source_url"].endswith("New1.jpg")


@pytest.mark.asyncio
async def test_regenerate_scene_rejects_out_of_range_scene(regenerate_storage):
    review = await create_regenerate_review()

    with pytest.raises(ValueError, match="scene index is outside content contract"):
        await regenerate_wrong_image_scene(review["review_id"], scene_index=9)
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
python3 -m pytest tests/test_regenerate_scene_cli.py -q
```

Expected: FAIL because `scripts/regenerate_scene.py` does not exist.

- [ ] **Step 3: Implement regenerate helper and CLI**

Create `scripts/regenerate_scene.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from agents.real_image_agent import RealImageAgent
from core.reviews import append_review_event, get_review, save_review, utc_now


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


async def regenerate_wrong_image_scene(review_id: str, *, scene_index: int) -> dict[str, Any]:
    review = await get_review(review_id)
    content_contract = review.get("content_contract") or {}
    scenes = content_contract.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("review content_contract.scenes is required")
    if scene_index < 0 or scene_index >= len(scenes):
        raise ValueError("scene index is outside content contract")

    image_contract = review.get("image_verification_contract") or {}
    items = image_contract.get("items")
    if not isinstance(items, list) or scene_index >= len(items):
        raise ValueError("scene index is outside image verification contract")

    topic_id = int((review.get("video") or {}).get("topic_id") or image_contract.get("topic_id") or 0)
    if topic_id <= 0:
        raise ValueError("review topic_id is required")

    one_scene_contract = dict(content_contract)
    one_scene_contract["scenes"] = [scenes[scene_index]]
    regenerated = await RealImageAgent().run_for_content_contract(
        topic_id=topic_id,
        content_contract=one_scene_contract,
        strict=True,
    )
    regenerated_item = dict(regenerated["items"][0])
    regenerated_item["scene_index"] = scene_index

    updated_items = [dict(item) for item in items]
    updated_items[scene_index] = regenerated_item
    image_contract = dict(image_contract)
    image_contract["items"] = updated_items
    image_contract["verified_count"] = sum(1 for item in updated_items if item.get("status") == "verified")
    image_contract["required_count"] = len(updated_items)
    image_contract["status"] = (
        "verified" if image_contract["verified_count"] == image_contract["required_count"] else "pending_review"
    )

    review["image_verification_contract"] = image_contract
    append_review_event(
        review,
        event="scene_regenerated",
        reason="wrong_image",
        scenes=[scene_index],
        notes="regenerated wrong-image scene",
    )
    review["updated_at"] = utc_now()
    await save_review(review)
    return review


async def run(args: argparse.Namespace) -> int:
    if args.reason != "wrong_image":
        raise ValueError("only wrong_image regeneration is supported in this MVP")
    print_json(await regenerate_wrong_image_scene(args.review_id, scene_index=args.scene))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenerate one scene in a review artifact.")
    parser.add_argument("review_id")
    parser.add_argument("--scene", type=int, required=True)
    parser.add_argument("--reason", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(run(args))
    except KeyError as exc:
        print(f"Review {exc.args[0]} not found", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add review persistence helpers**

In `core/reviews.py`, expose:

```python
def append_review_event(
    review: dict[str, Any],
    *,
    event: str,
    reason: str = "",
    scenes: list[int] | None = None,
    notes: str = "",
) -> None:
    review.setdefault("review_events", []).append(
        {
            "event": event,
            "reason": reason,
            "scenes": scenes or [],
            "notes": notes,
            "created_at": utc_now(),
        }
    )


async def save_review(review: dict[str, Any]) -> None:
    await _write_review(review)
```

- [ ] **Step 5: Verify regenerate tests pass**

Run:

```bash
python3 -m pytest tests/test_regenerate_scene_cli.py -q
```

Expected: PASS.

## Task 4: Full Verification and Commit

**Files:**
- All modified files from Tasks 1-3.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_reviews.py tests/test_review_video_cli.py tests/test_regenerate_scene_cli.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run TypeScript build**

Run:

```bash
npm run build
```

from `video_engine`.

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```bash
git add core/reviews.py scripts/review_video.py scripts/regenerate_scene.py tests/test_reviews.py tests/test_review_video_cli.py tests/test_regenerate_scene_cli.py
git commit -m "feat: add review gate cli and scene regeneration"
```

Expected: commit succeeds.

