# Real Image Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict real-image pipeline for celebrity local renders that verifies Wikimedia-sourced photos before they can replace placeholder card images.

**Architecture:** Add image verification primitives to `core/video_contract.py`, a new `RealImageAgent` for strict Wikimedia image lookup/download/validation, and wire the celebrity local render path to apply verified image paths without changing the existing timeline template. Review artifacts will carry the image verification contract so the user can inspect sources, licenses, attribution, and failures.

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio, httpx, Pillow, existing JSON review store, existing Remotion timeline render path.

---

## File Structure

- Modify `core/video_contract.py`: image verification contract builders/validators and `apply_verified_images_to_video_data`.
- Create `agents/real_image_agent.py`: strict Wikimedia-only real image agent and deterministic verification helpers.
- Modify `core/reviews.py`: optional `image_verification_contract` persisted in review JSON.
- Modify `agents/pipeline.py`: celebrity local render runs `RealImageAgent`, applies verified images, and passes image contract into review/result.
- Create `tests/test_image_verification_contract.py`: contract validation and render-data image application tests.
- Create `tests/test_real_image_agent.py`: unit tests for person extraction, license/name matching, and mocked image download/processing.
- Modify `tests/test_reviews.py`: review artifacts persist image verification data.
- Modify `tests/test_pipeline_local_render.py`: pipeline uses `RealImageAgent`, preserves `template: timeline`, and passes image contract to review.
- Modify `README.md`: document strict real-image behavior.

## Task 1: Image Verification Contract

**Files:**
- Modify: `core/video_contract.py`
- Create: `tests/test_image_verification_contract.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_image_verification_contract.py`:

```python
import pytest

from core.video_contract import (
    VideoContractError,
    apply_verified_images_to_video_data,
    build_image_verification_contract_v1,
    validate_image_verification_contract_v1,
)


def _verified_item(scene_index: int = 0) -> dict:
    return {
        "scene_index": scene_index,
        "person_name": "Celine Dion",
        "expected_title": "#10 Celine Dion",
        "status": "verified",
        "confidence": 0.95,
        "local_path": "/tmp/topic/images/real_0.webp",
        "render_image_path": "images/real_0.webp",
        "source_url": "https://commons.wikimedia.org/wiki/File:Celine_Dion.jpg",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
        "license": "CC BY-SA 4.0",
        "attribution": "Example photographer",
        "reject_reason": "",
    }


def test_build_image_verification_contract_v1_accepts_verified_items():
    contract = build_image_verification_contract_v1(
        topic_id=1,
        items=[_verified_item()],
    )

    validate_image_verification_contract_v1(contract)

    assert contract["schema_version"] == "image_verification_contract_v1"
    assert contract["source_policy"] == "wikimedia_commons_strict"
    assert contract["required_count"] == 1
    assert contract["verified_count"] == 1
    assert contract["status"] == "verified"


def test_validate_image_verification_contract_rejects_verified_item_without_source():
    item = _verified_item()
    item["source_url"] = ""
    contract = build_image_verification_contract_v1(topic_id=1, items=[item])

    with pytest.raises(VideoContractError, match="items\\[0\\].source_url is required"):
        validate_image_verification_contract_v1(contract)


def test_build_image_verification_contract_marks_missing_items_pending_review():
    missing = {
        "scene_index": 0,
        "person_name": "Celine Dion",
        "expected_title": "#10 Celine Dion",
        "status": "missing_image",
        "confidence": 0.0,
        "local_path": "",
        "render_image_path": "",
        "source_url": "",
        "image_url": "",
        "license": "",
        "attribution": "",
        "reject_reason": "no verified Wikimedia image found",
    }

    contract = build_image_verification_contract_v1(topic_id=1, items=[missing])
    validate_image_verification_contract_v1(contract)

    assert contract["verified_count"] == 0
    assert contract["status"] == "pending_review"


def test_apply_verified_images_to_video_data_preserves_template_and_replaces_images():
    contract = build_image_verification_contract_v1(topic_id=1, items=[_verified_item()])
    video_data = {
        "template": "timeline",
        "title": "Top 10",
        "subtitle": "Data comparison",
        "language": "vi",
        "cards": [
            {
                "header": "SCENE 1",
                "title": "#10 Celine Dion",
                "description": "Description",
                "imagePath": "images/local-placeholder.svg",
                "statusText": "#10 | 550M USD",
            }
        ],
        "introCards": [],
        "musicPath": "",
        "sfxPaths": {"transition": "", "alert": "", "reveal": ""},
        "logoPath": "images/local-logo.svg",
        "holdDurationFrames": 120,
        "transitionDurationFrames": 15,
    }

    result = apply_verified_images_to_video_data(video_data, contract)

    assert result["template"] == "timeline"
    assert result["cards"][0]["imagePath"] == "images/real_0.webp"
    assert result["cards"][0]["title"] == "#10 Celine Dion"
    assert result["image_verification_contract"] == contract


def test_apply_verified_images_rejects_pending_contract():
    missing = {
        "scene_index": 0,
        "person_name": "Celine Dion",
        "expected_title": "#10 Celine Dion",
        "status": "missing_image",
        "confidence": 0.0,
        "local_path": "",
        "render_image_path": "",
        "source_url": "",
        "image_url": "",
        "license": "",
        "attribution": "",
        "reject_reason": "no verified Wikimedia image found",
    }
    contract = build_image_verification_contract_v1(topic_id=1, items=[missing])
    video_data = {
        "template": "timeline",
        "title": "Top 10",
        "subtitle": "Data comparison",
        "language": "vi",
        "cards": [{"title": "#10 Celine Dion"}],
    }

    with pytest.raises(VideoContractError, match="image verification contract must be verified"):
        apply_verified_images_to_video_data(video_data, contract)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_image_verification_contract.py -v
```

Expected: FAIL during import because `build_image_verification_contract_v1` does not exist.

- [ ] **Step 3: Implement contract helpers**

In `core/video_contract.py`, add these functions after `validate_content_contract_v2`:

```python
def build_image_verification_contract_v1(
    *,
    topic_id: int,
    items: list[dict[str, Any]],
    source_policy: str = "wikimedia_commons_strict",
) -> dict[str, Any]:
    verified_count = sum(1 for item in items if item.get("status") == "verified")
    status = "verified" if items and verified_count == len(items) else "pending_review"
    return {
        "schema_version": "image_verification_contract_v1",
        "topic_id": topic_id,
        "source_policy": source_policy,
        "required_count": len(items),
        "verified_count": verified_count,
        "status": status,
        "items": items,
    }


def validate_image_verification_contract_v1(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != "image_verification_contract_v1":
        raise VideoContractError("schema_version must be image_verification_contract_v1")
    if payload.get("source_policy") != "wikimedia_commons_strict":
        raise VideoContractError("source_policy must be wikimedia_commons_strict")
    if not isinstance(payload.get("topic_id"), int) or payload["topic_id"] <= 0:
        raise VideoContractError("topic_id must be a positive integer")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise VideoContractError("items must contain at least one image verification item")

    verified_count = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise VideoContractError(f"items[{index}] must be an object")
        for field_name in ("scene_index", "person_name", "expected_title", "status", "confidence"):
            if field_name == "scene_index":
                if not isinstance(item.get(field_name), int) or item[field_name] < 0:
                    raise VideoContractError(f"items[{index}].scene_index must be a non-negative integer")
            elif field_name == "confidence":
                confidence = item.get(field_name)
                if not isinstance(confidence, int | float) or confidence < 0 or confidence > 1:
                    raise VideoContractError(f"items[{index}].confidence must be between 0 and 1")
            elif not str(item.get(field_name, "")).strip():
                raise VideoContractError(f"items[{index}].{field_name} is required")

        status = item["status"]
        if status not in {"verified", "missing_image", "rejected"}:
            raise VideoContractError(f"items[{index}].status is invalid")

        if status == "verified":
            verified_count += 1
            for field_name in ("local_path", "render_image_path", "source_url", "image_url", "license", "attribution"):
                if not str(item.get(field_name, "")).strip():
                    raise VideoContractError(f"items[{index}].{field_name} is required")
            if str(item.get("reject_reason", "")):
                raise VideoContractError(f"items[{index}].reject_reason must be empty for verified images")
        elif not str(item.get("reject_reason", "")).strip():
            raise VideoContractError(f"items[{index}].reject_reason is required")

    if payload.get("required_count") != len(items):
        raise VideoContractError("required_count must equal item count")
    if payload.get("verified_count") != verified_count:
        raise VideoContractError("verified_count must equal verified item count")

    expected_status = "verified" if verified_count == len(items) else "pending_review"
    if payload.get("status") != expected_status:
        raise VideoContractError(f"status must be {expected_status}")
```

Add this helper before `validate_video_data`:

```python
def apply_verified_images_to_video_data(
    video_data: dict[str, Any],
    image_contract: dict[str, Any],
) -> dict[str, Any]:
    validate_image_verification_contract_v1(image_contract)
    if image_contract["status"] != "verified":
        raise VideoContractError("image verification contract must be verified")

    cards = video_data.get("cards")
    if not isinstance(cards, list):
        raise VideoContractError("cards must contain at least one card")

    for item in image_contract["items"]:
        scene_index = item["scene_index"]
        if scene_index >= len(cards):
            raise VideoContractError(f"items[{scene_index}].scene_index is outside card range")
        cards[scene_index]["imagePath"] = item["render_image_path"]

    video_data["image_verification_contract"] = image_contract
    return video_data
```

- [ ] **Step 4: Run contract tests**

Run:

```bash
python3 -m pytest tests/test_image_verification_contract.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/video_contract.py tests/test_image_verification_contract.py
git commit -m "feat: add image verification contract"
```

## Task 2: Real Image Agent Deterministic Helpers

**Files:**
- Create: `agents/real_image_agent.py`
- Create: `tests/test_real_image_agent.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_real_image_agent.py`:

```python
from agents.real_image_agent import RealImageAgent


def test_extract_person_name_from_ranked_scene_title():
    assert RealImageAgent.extract_person_name("#10 Celine Dion") == "Celine Dion"
    assert RealImageAgent.extract_person_name("#1 Jay-Z") == "Jay-Z"


def test_is_allowed_license_accepts_commons_friendly_licenses():
    assert RealImageAgent.is_allowed_license("CC BY-SA 4.0") is True
    assert RealImageAgent.is_allowed_license("Creative Commons Attribution 2.0") is True
    assert RealImageAgent.is_allowed_license("Public domain") is True
    assert RealImageAgent.is_allowed_license("All rights reserved") is False


def test_metadata_matches_person_requires_strong_name_tokens():
    metadata = "File:Celine Dion 2012.jpg Celine Dion performing live"

    assert RealImageAgent.metadata_matches_person("Celine Dion", metadata) is True
    assert RealImageAgent.metadata_matches_person("Beyonce", metadata) is False


def test_build_missing_item_contains_reviewable_reason():
    item = RealImageAgent.build_missing_item(
        scene_index=0,
        person_name="Celine Dion",
        expected_title="#10 Celine Dion",
        reason="no verified Wikimedia image found",
    )

    assert item["status"] == "missing_image"
    assert item["confidence"] == 0.0
    assert item["reject_reason"] == "no verified Wikimedia image found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py -v
```

Expected: FAIL during import because `agents.real_image_agent` does not exist.

- [ ] **Step 3: Implement deterministic helper shell**

Create `agents/real_image_agent.py`:

```python
"""Strict real-image agent for celebrity content."""

from __future__ import annotations

import re
from typing import Any

from agents.base_agent import BaseAgent

_ALLOWED_LICENSE_PARTS = (
    "cc0",
    "public domain",
    "cc by",
    "cc-by",
    "creative commons attribution",
    "creative commons attribution-sharealike",
)


class RealImageAgent(BaseAgent):
    """Find and verify real sourced images for celebrity render cards."""

    def __init__(self) -> None:
        super().__init__(name="real_image_agent")

    @staticmethod
    def extract_person_name(scene_title: str) -> str:
        cleaned = re.sub(r"^#\d+\s+", "", scene_title.strip())
        return cleaned.strip()

    @staticmethod
    def is_allowed_license(license_text: str) -> bool:
        normalized = license_text.strip().lower()
        return any(part in normalized for part in _ALLOWED_LICENSE_PARTS)

    @staticmethod
    def metadata_matches_person(person_name: str, metadata_text: str) -> bool:
        name_tokens = [
            token.lower()
            for token in re.findall(r"[A-Za-z0-9]+", person_name)
            if len(token) > 1
        ]
        normalized_metadata = metadata_text.lower()
        return bool(name_tokens) and all(token in normalized_metadata for token in name_tokens)

    @staticmethod
    def build_missing_item(
        *,
        scene_index: int,
        person_name: str,
        expected_title: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "scene_index": scene_index,
            "person_name": person_name,
            "expected_title": expected_title,
            "status": "missing_image",
            "confidence": 0.0,
            "local_path": "",
            "render_image_path": "",
            "source_url": "",
            "image_url": "",
            "license": "",
            "attribution": "",
            "reject_reason": reason,
        }
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/real_image_agent.py tests/test_real_image_agent.py
git commit -m "feat: add real image agent helpers"
```

## Task 3: Real Image Agent Wikimedia Flow

**Files:**
- Modify: `agents/real_image_agent.py`
- Modify: `tests/test_real_image_agent.py`

- [ ] **Step 1: Add mocked Wikimedia run test**

Append to `tests/test_real_image_agent.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_run_for_content_contract_returns_verified_wikimedia_contract(monkeypatch, tmp_path):
    agent = RealImageAgent()
    content_contract = {
        "scenes": [
            {
                "title": "#10 Celine Dion",
                "voiceover": "voiceover",
                "caption": "550M USD",
                "image_prompt": "unused",
                "statusText": "#10 | 550M USD",
            }
        ]
    }

    async def fake_find_verified_image(*, topic_id, scene_index, person_name, expected_title):
        local_path = tmp_path / "topics" / str(topic_id) / "images" / f"real_{scene_index}.webp"
        local_path.parent.mkdir(parents=True)
        local_path.write_bytes(b"fake image")
        return {
            "scene_index": scene_index,
            "person_name": person_name,
            "expected_title": expected_title,
            "status": "verified",
            "confidence": 0.9,
            "local_path": str(local_path),
            "render_image_path": f"images/real_{scene_index}.webp",
            "source_url": "https://commons.wikimedia.org/wiki/File:Celine_Dion.jpg",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
            "license": "CC BY-SA 4.0",
            "attribution": "Example photographer",
            "reject_reason": "",
        }

    monkeypatch.setattr(agent, "_find_verified_image", fake_find_verified_image)

    contract = await agent.run_for_content_contract(
        topic_id=1,
        content_contract=content_contract,
        strict=True,
    )

    assert contract["status"] == "verified"
    assert contract["verified_count"] == 1
    assert contract["items"][0]["person_name"] == "Celine Dion"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py::test_run_for_content_contract_returns_verified_wikimedia_contract -v
```

Expected: FAIL because `run_for_content_contract` does not exist.

- [ ] **Step 3: Implement run orchestration**

In `agents/real_image_agent.py`, add imports:

```python
from core.video_contract import build_image_verification_contract_v1, validate_image_verification_contract_v1
```

Add methods inside `RealImageAgent`:

```python
    async def run_for_content_contract(
        self,
        *,
        topic_id: int,
        content_contract: dict[str, Any],
        strict: bool = True,
    ) -> dict[str, Any]:
        scenes = content_contract.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("content_contract.scenes must contain at least one scene")

        items: list[dict[str, Any]] = []
        for scene_index, scene in enumerate(scenes):
            expected_title = str(scene.get("title", "")).strip()
            person_name = self.extract_person_name(expected_title)
            if not person_name:
                items.append(
                    self.build_missing_item(
                        scene_index=scene_index,
                        person_name="",
                        expected_title=expected_title,
                        reason="scene title does not contain a person name",
                    )
                )
                continue

            item = await self._find_verified_image(
                topic_id=topic_id,
                scene_index=scene_index,
                person_name=person_name,
                expected_title=expected_title,
            )
            if item is None:
                item = self.build_missing_item(
                    scene_index=scene_index,
                    person_name=person_name,
                    expected_title=expected_title,
                    reason="no verified Wikimedia image found",
                )
            items.append(item)

        contract = build_image_verification_contract_v1(topic_id=topic_id, items=items)
        validate_image_verification_contract_v1(contract)
        if strict and contract["status"] != "verified":
            missing = [
                item["person_name"]
                for item in contract["items"]
                if item["status"] != "verified"
            ]
            raise ValueError(f"missing verified real images: {', '.join(missing)}")
        return contract

    async def _find_verified_image(
        self,
        *,
        topic_id: int,
        scene_index: int,
        person_name: str,
        expected_title: str,
    ) -> dict[str, Any] | None:
        return None
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Add Wikimedia candidate/download tests**

Append to `tests/test_real_image_agent.py`:

```python
from io import BytesIO
from PIL import Image


def test_extract_wikimedia_candidate_reads_license_and_attribution():
    page = {
        "title": "File:Celine Dion 2012.jpg",
        "imageinfo": [
            {
                "url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Celine_Dion_2012.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "Artist": {"value": "Example photographer"},
                    "ImageDescription": {"value": "Celine Dion performing live"},
                },
            }
        ],
    }

    candidate = RealImageAgent.extract_wikimedia_candidate("Celine Dion", page)

    assert candidate == {
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Celine_Dion_2012.jpg",
        "license": "CC BY-SA 4.0",
        "attribution": "Example photographer",
        "metadata_text": "File:Celine Dion 2012.jpg CC BY-SA 4.0 Example photographer Celine Dion performing live",
    }


@pytest.mark.asyncio
async def test_process_verified_candidate_downloads_webp(monkeypatch, tmp_path):
    agent = RealImageAgent()
    image = Image.new("RGB", (640, 400), color="red")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")

    async def fake_download_image_bytes(image_url: str) -> bytes:
        assert image_url == "https://upload.wikimedia.org/wikipedia/commons/celine.jpg"
        return buffer.getvalue()

    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(agent, "_download_image_bytes", fake_download_image_bytes)

    item = await agent._process_verified_candidate(
        topic_id=1,
        scene_index=0,
        person_name="Celine Dion",
        expected_title="#10 Celine Dion",
        candidate={
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
            "source_url": "https://commons.wikimedia.org/wiki/File:Celine_Dion_2012.jpg",
            "license": "CC BY-SA 4.0",
            "attribution": "Example photographer",
            "metadata_text": "Celine Dion performing live",
        },
    )

    assert item["status"] == "verified"
    assert item["render_image_path"] == "images/real_0.webp"
    assert item["source_url"].startswith("https://commons.wikimedia.org/")
```

- [ ] **Step 6: Run new tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py::test_extract_wikimedia_candidate_reads_license_and_attribution tests/test_real_image_agent.py::test_process_verified_candidate_downloads_webp -v
```

Expected: FAIL because `extract_wikimedia_candidate` and `_process_verified_candidate` do not exist.

- [ ] **Step 7: Implement Wikimedia candidate and image processing**

In `agents/real_image_agent.py`, add imports:

```python
import html
from io import BytesIO
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from PIL import Image

from core.config import get_settings
```

Add constants:

```python
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
_MIN_IMAGE_WIDTH = 200
_MIN_IMAGE_HEIGHT = 200
```

Add methods:

```python
    @staticmethod
    def clean_metadata(value: Any) -> str:
        return re.sub(r"<[^>]+>", "", html.unescape(str(value or ""))).strip()

    @classmethod
    def extract_wikimedia_candidate(cls, person_name: str, page: dict[str, Any]) -> dict[str, str] | None:
        image_info_list = page.get("imageinfo")
        if not image_info_list:
            return None
        info = image_info_list[0]
        image_url = str(info.get("url", "")).strip()
        source_url = str(info.get("descriptionurl", "")).strip()
        metadata = info.get("extmetadata") or {}
        license_text = cls.clean_metadata(metadata.get("LicenseShortName", {}).get("value", ""))
        attribution = cls.clean_metadata(metadata.get("Artist", {}).get("value", ""))
        description = cls.clean_metadata(metadata.get("ImageDescription", {}).get("value", ""))
        title = cls.clean_metadata(page.get("title", ""))
        metadata_text = " ".join(part for part in (title, license_text, attribution, description) if part)

        if not image_url or not source_url:
            return None
        if not cls.is_allowed_license(license_text):
            return None
        if not cls.metadata_matches_person(person_name, metadata_text):
            return None
        return {
            "image_url": image_url,
            "source_url": source_url,
            "license": license_text,
            "attribution": attribution or "Wikimedia Commons contributor",
            "metadata_text": metadata_text,
        }

    async def _download_image_bytes(self, image_url: str) -> bytes:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(image_url, headers={"User-Agent": "Y5E-Automation/1.0"})
            response.raise_for_status()
            return response.content

    async def _process_verified_candidate(
        self,
        *,
        topic_id: int,
        scene_index: int,
        person_name: str,
        expected_title: str,
        candidate: dict[str, str],
    ) -> dict[str, Any]:
        raw_bytes = await self._download_image_bytes(candidate["image_url"])
        with Image.open(BytesIO(raw_bytes)) as image:
            image = image.convert("RGB")
            if image.width < _MIN_IMAGE_WIDTH or image.height < _MIN_IMAGE_HEIGHT:
                raise ValueError("image is too small")
            settings = get_settings()
            image_dir = settings.storage_dir / "topics" / str(topic_id) / "images"
            image_dir.mkdir(parents=True, exist_ok=True)
            local_path = image_dir / f"real_{scene_index}.webp"
            image.save(local_path, format="WEBP", quality=90)

        return {
            "scene_index": scene_index,
            "person_name": person_name,
            "expected_title": expected_title,
            "status": "verified",
            "confidence": 0.9,
            "local_path": str(local_path),
            "render_image_path": f"images/real_{scene_index}.webp",
            "source_url": candidate["source_url"],
            "image_url": candidate["image_url"],
            "license": candidate["license"],
            "attribution": candidate["attribution"],
            "reject_reason": "",
        }
```

- [ ] **Step 8: Implement real Wikimedia lookup**

Replace `_find_verified_image` body in `agents/real_image_agent.py`:

```python
        query = quote_plus(f"{person_name} portrait")
        url = (
            "https://commons.wikimedia.org/w/api.php"
            f"?action=query&generator=search"
            f"&gsrsearch={query}"
            f"&gsrnamespace=6"
            f"&gsrlimit=10"
            f"&prop=imageinfo"
            f"&iiprop=url|extmetadata"
            f"&format=json"
        )
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "Y5E-Automation/1.0"})
            response.raise_for_status()
            data = response.json()

        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            candidate = self.extract_wikimedia_candidate(person_name, page)
            if candidate is None:
                continue
            try:
                return await self._process_verified_candidate(
                    topic_id=topic_id,
                    scene_index=scene_index,
                    person_name=person_name,
                    expected_title=expected_title,
                    candidate=candidate,
                )
            except Exception:
                self.logger.exception("Failed to process verified image candidate for %s", person_name)
                continue
        return None
```

- [ ] **Step 9: Run all real image agent tests**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py -v
```

Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add agents/real_image_agent.py tests/test_real_image_agent.py
git commit -m "feat: add Wikimedia real image agent"
```

## Task 4: Review Artifact Support

**Files:**
- Modify: `core/reviews.py`
- Modify: `tests/test_reviews.py`

- [ ] **Step 1: Write failing review persistence test**

Append to `tests/test_reviews.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_reviews.py::test_create_review_persists_image_verification_contract -v
```

Expected: FAIL because `create_review` does not accept `image_verification_contract`.

- [ ] **Step 3: Add optional review field**

Modify `core/reviews.py` function signature:

```python
async def create_review(
    *,
    job_id: str,
    topic_id: int,
    video_id: int,
    file_path: str,
    content_contract: dict[str, Any] | None,
    image_verification_contract: dict[str, Any] | None = None,
    youtube_title: str,
    youtube_description: str,
    youtube_tags: list[str],
    thumbnail_prompt: str,
) -> dict[str, Any]:
```

Add this field to the `review` dict after `content_contract`:

```python
        "image_verification_contract": image_verification_contract or {},
```

- [ ] **Step 4: Run review tests**

Run:

```bash
python3 -m pytest tests/test_reviews.py tests/test_api_reviews.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/reviews.py tests/test_reviews.py
git commit -m "feat: persist image verification in reviews"
```

## Task 5: Pipeline Integration

**Files:**
- Modify: `agents/pipeline.py`
- Modify: `tests/test_pipeline_local_render.py`

- [ ] **Step 1: Write failing pipeline test update**

In `tests/test_pipeline_local_render.py`, update `test_run_local_render_uses_content_agent_for_celebrity`.

Add a fake agent class inside the test before monkeypatches:

```python
    class FakeRealImageAgent:
        async def run_for_content_contract(self, *, topic_id, content_contract, strict=True):
            captured["image_agent_topic_id"] = topic_id
            captured["image_agent_content_contract"] = content_contract
            captured["image_agent_strict"] = strict
            return {
                "schema_version": "image_verification_contract_v1",
                "topic_id": topic_id,
                "source_policy": "wikimedia_commons_strict",
                "required_count": len(content_contract["scenes"]),
                "verified_count": len(content_contract["scenes"]),
                "status": "verified",
                "items": [
                    {
                        "scene_index": index,
                        "person_name": scene["title"].split(" ", 1)[1],
                        "expected_title": scene["title"],
                        "status": "verified",
                        "confidence": 0.9,
                        "local_path": f"/tmp/real_{index}.webp",
                        "render_image_path": f"images/real_{index}.webp",
                        "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                        "image_url": "https://upload.wikimedia.org/wikipedia/commons/example.jpg",
                        "license": "CC BY-SA 4.0",
                        "attribution": "Example photographer",
                        "reject_reason": "",
                    }
                    for index, scene in enumerate(content_contract["scenes"])
                ],
            }
```

Add monkeypatch:

```python
    monkeypatch.setattr("agents.pipeline.RealImageAgent", FakeRealImageAgent)
```

Add assertions after `review_kwargs = captured["review_kwargs"]`:

```python
    image_contract = video_data["image_verification_contract"]
    assert captured["image_agent_topic_id"] == 1
    assert captured["image_agent_content_contract"] == content_contract
    assert captured["image_agent_strict"] is True
    assert image_contract["status"] == "verified"
    assert video_data["cards"][0]["imagePath"] == "images/real_0.webp"
    assert review_kwargs["image_verification_contract"] == image_contract
    assert result["image_verification_contract"] == image_contract
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_pipeline_local_render.py::test_run_local_render_uses_content_agent_for_celebrity -v
```

Expected: FAIL because `agents.pipeline.RealImageAgent` is not imported or used.

- [ ] **Step 3: Implement pipeline integration**

In `agents/pipeline.py`, add imports near the top:

```python
from agents.real_image_agent import RealImageAgent
```

Update `core.video_contract` import:

```python
from core.video_contract import (
    apply_verified_images_to_video_data,
    build_local_render_video_data,
    build_video_data_from_content_contract,
    validate_video_data,
)
```

Inside `run_local_render`, initialize:

```python
        image_verification_contract: dict[str, Any] | None = None
```

Inside the celebrity branch, after building `video_data`:

```python
            image_verification_contract = await RealImageAgent().run_for_content_contract(
                topic_id=1,
                content_contract=content_contract,
                strict=True,
            )
            video_data = apply_verified_images_to_video_data(
                video_data,
                image_verification_contract,
            )
```

In the `create_review` call, add:

```python
                image_verification_contract=image_verification_contract,
```

In the returned dict, add:

```python
            "image_verification_contract": image_verification_contract,
```

- [ ] **Step 4: Run focused pipeline test**

Run:

```bash
python3 -m pytest tests/test_pipeline_local_render.py::test_run_local_render_uses_content_agent_for_celebrity -v
```

Expected: PASS.

- [ ] **Step 5: Run local render tests**

Run:

```bash
python3 -m pytest tests/test_pipeline_local_render.py tests/test_image_verification_contract.py tests/test_real_image_agent.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/pipeline.py tests/test_pipeline_local_render.py
git commit -m "feat: require verified real images for celebrity local render"
```

## Task 6: Documentation And Full Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

In `README.md`, under the celebrity local render paragraph, add:

```markdown
Celebrity local renders use the strict `RealImageAgent` path before Remotion rendering. The agent accepts only verified real images from Wikimedia/Wikipedia-style sources with source URL, image URL, license, attribution, and person-name metadata checks. The existing timeline video template is not changed; verified images only replace each card's `imagePath`. If required images are missing or unverified, the celebrity render path must not silently render a production-looking MP4 with placeholders.
```

- [ ] **Step 2: Run full Python test suite**

Run:

```bash
python3 -m pytest tests/test_config_validation.py tests/test_health.py tests/test_queue.py tests/test_api_jobs.py tests/test_api_reviews.py tests/test_pipeline_worker.py tests/test_pipeline_smoke.py tests/test_pipeline_local_render.py tests/test_video_contract.py tests/test_video_contract_local_render.py tests/test_content_contract_v2.py tests/test_content_agent.py tests/test_reviews.py tests/test_image_verification_contract.py tests/test_real_image_agent.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Run compile check**

Run:

```bash
python3 -m compileall api core agents workers tests
```

Expected: exit code 0.

- [ ] **Step 4: Run Remotion type check**

Run:

```bash
npm run build
```

Working directory: `video_engine`

Expected: exit code 0.

- [ ] **Step 5: Optional live Wikimedia smoke render**

Run only after unit tests pass:

```bash
python3 - <<'PY'
import asyncio, json
from agents.pipeline import Pipeline

async def main():
    result = await Pipeline().run_local_render(category='Celebrity', language='vi')
    print(json.dumps({
        'file_path': result['file_path'],
        'review_id': result['review_id'],
        'review_status': result['review_status'],
        'image_status': result['image_verification_contract']['status'],
        'first_image': result['image_verification_contract']['items'][0]['render_image_path'],
    }, ensure_ascii=False, indent=2))

asyncio.run(main())
PY
```

Expected: either a rendered MP4 with `image_status: verified`, or a clear failure listing missing verified real images. Do not weaken strict mode if Wikimedia lacks an image for one celebrity.

- [ ] **Step 6: Commit docs and verification-ready state**

```bash
git add README.md
git commit -m "docs: document strict real image render gate"
```

- [ ] **Step 7: Push branch**

```bash
git status --short --untracked-files=all
git push origin main
```

Expected: push succeeds and working tree is clean except ignored runtime output.

## Self-Review

- Spec coverage: the plan covers contract creation/validation, strict Wikimedia agent, render data integration, review metadata, documentation, and verification.
- Placeholder scan: there are no plan placeholders requiring later invention; references to placeholder images are explicit production constraints.
- Type consistency: contract field names match the approved spec: `image_verification_contract_v1`, `source_policy`, `required_count`, `verified_count`, `items`, `render_image_path`, and `reject_reason`.
