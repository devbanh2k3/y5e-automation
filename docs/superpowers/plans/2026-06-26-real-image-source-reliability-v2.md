# Real Image Source Reliability v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `RealImageAgent` prefer verified Wikimedia thumbnail downloads and reject images that do not match the intended celebrity/content.

**Architecture:** Extend the existing `RealImageAgent` instead of adding a parallel image system. Candidate extraction will return both provenance (`image_url`, `source_url`, license, attribution) and render download data (`download_url`) plus deterministic identity/content checks. The pipeline and video template remain unchanged.

**Tech Stack:** Python 3.12+, pytest, httpx, Pillow, existing `content_contract_v2`, existing `image_verification_contract_v1`.

---

## File Structure

- Modify `agents/real_image_agent.py`: add content guard helpers, `thumburl` support, download content-type validation, and next-candidate fallback.
- Modify `tests/test_real_image_agent.py`: add TDD coverage for content matching, thumbnail preference, download URL usage, non-image rejection, and fallback behavior.
- Modify `README.md`: document that image matching checks identity and context, not only source/license.

## Task 1: Candidate Content Guard

**Files:**
- Modify: `agents/real_image_agent.py`
- Modify: `tests/test_real_image_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_real_image_agent.py`:

```python
def test_identity_check_requires_full_name_not_loose_tokens():
    passed = RealImageAgent.evaluate_identity_match(
        "Celine Dion",
        "File:Celine Dion 2012.jpg Celine Dion performing live",
    )
    failed = RealImageAgent.evaluate_identity_match(
        "Jay-Z",
        "File:John Jay portrait.jpg Judge John Jay historical portrait",
    )

    assert passed["identity_check_status"] == "passed"
    assert passed["identity_confidence"] == 0.95
    assert failed["identity_check_status"] == "failed"
    assert failed["identity_confidence"] == 0.0


def test_content_match_rejects_non_photo_and_reviewable_group_photos():
    pdf_result = RealImageAgent.evaluate_content_match(
        metadata_text="File:John Jay book.pdf scanned book archive",
        source_url="https://commons.wikimedia.org/wiki/File:John_Jay_book.pdf",
    )
    group_result = RealImageAgent.evaluate_content_match(
        metadata_text="Celine Dion with other artists group photo",
        source_url="https://commons.wikimedia.org/wiki/File:Celine_group.jpg",
    )
    portrait_result = RealImageAgent.evaluate_content_match(
        metadata_text="Celine Dion portrait performing live concert",
        source_url="https://commons.wikimedia.org/wiki/File:Celine_Dion.jpg",
    )

    assert pdf_result["content_match_status"] == "failed"
    assert pdf_result["needs_human_review"] is True
    assert group_result["content_match_status"] == "uncertain"
    assert group_result["is_group_photo"] is True
    assert portrait_result["content_match_status"] == "passed"
    assert portrait_result["needs_human_review"] is False
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py::test_identity_check_requires_full_name_not_loose_tokens tests/test_real_image_agent.py::test_content_match_rejects_non_photo_and_reviewable_group_photos -v
```

Expected: FAIL because `evaluate_identity_match` and `evaluate_content_match` do not exist.

- [ ] **Step 3: Implement helpers**

In `agents/real_image_agent.py`, add these methods inside `RealImageAgent`:

```python
    @staticmethod
    def normalize_identity_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    @classmethod
    def evaluate_identity_match(cls, person_name: str, metadata_text: str) -> dict[str, Any]:
        normalized_name = cls.normalize_identity_text(person_name)
        normalized_metadata = cls.normalize_identity_text(metadata_text)
        compact_name = normalized_name.replace(" ", "")
        compact_metadata = normalized_metadata.replace(" ", "")
        if normalized_name and normalized_name in normalized_metadata:
            return {"identity_check_status": "passed", "identity_confidence": 0.95}
        if compact_name and compact_name in compact_metadata:
            return {"identity_check_status": "passed", "identity_confidence": 0.9}
        return {"identity_check_status": "failed", "identity_confidence": 0.0}

    @classmethod
    def evaluate_content_match(cls, metadata_text: str, source_url: str) -> dict[str, Any]:
        combined = f"{metadata_text} {source_url}".lower()
        blocked_terms = ("pdf", "book", "archive", "painting", "diagram", "logo", "fan art", "meme")
        if any(term in combined for term in blocked_terms):
            return {
                "content_match_status": "failed",
                "content_match_reason": "metadata indicates non-photo or unrelated media",
                "is_group_photo": False,
                "needs_human_review": True,
            }
        is_group_photo = any(term in combined for term in ("group", "with other", "honorees"))
        if is_group_photo:
            return {
                "content_match_status": "uncertain",
                "content_match_reason": "metadata indicates group photo",
                "is_group_photo": True,
                "needs_human_review": True,
            }
        return {
            "content_match_status": "passed",
            "content_match_reason": "metadata matches acceptable celebrity photo context",
            "is_group_photo": False,
            "needs_human_review": False,
        }
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/real_image_agent.py tests/test_real_image_agent.py
git commit -m "feat: add real image content match guard"
```

## Task 2: Wikimedia Thumbnail Download Fallback

**Files:**
- Modify: `agents/real_image_agent.py`
- Modify: `tests/test_real_image_agent.py`

- [ ] **Step 1: Write failing tests**

Update `test_extract_wikimedia_candidate_reads_license_and_attribution` so the fake page includes `"thumburl": "https://upload.wikimedia.org/thumb/celine.jpg"` and assert:

```python
assert candidate["download_url"] == "https://upload.wikimedia.org/thumb/celine.jpg"
assert candidate["image_url"] == "https://upload.wikimedia.org/wikipedia/commons/celine.jpg"
assert candidate["source_adapter"] == "commons_search_thumbnail"
assert candidate["identity_check_status"] == "passed"
assert candidate["content_match_status"] == "passed"
```

Append:

```python
@pytest.mark.asyncio
async def test_process_verified_candidate_prefers_download_url(monkeypatch, tmp_path):
    agent = RealImageAgent()
    image = Image.new("RGB", (640, 400), color="blue")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    seen = {}

    async def fake_download_image_bytes(image_url: str) -> tuple[bytes, str]:
        seen["url"] = image_url
        return buffer.getvalue(), "image/jpeg"

    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(agent, "_download_image_bytes", fake_download_image_bytes)

    item = await agent._process_verified_candidate(
        topic_id=1,
        scene_index=0,
        person_name="Celine Dion",
        expected_title="#10 Celine Dion",
        candidate={
            "download_url": "https://upload.wikimedia.org/thumb/celine.jpg",
            "image_url": "https://upload.wikimedia.org/original/celine.jpg",
            "source_url": "https://commons.wikimedia.org/wiki/File:Celine_Dion.jpg",
            "license": "CC BY-SA 4.0",
            "attribution": "Example photographer",
            "metadata_text": "Celine Dion portrait",
            "source_adapter": "commons_search_thumbnail",
            "identity_check_status": "passed",
            "identity_confidence": 0.95,
            "content_match_status": "passed",
            "content_match_reason": "metadata matches acceptable celebrity photo context",
            "is_group_photo": False,
            "needs_human_review": False,
        },
    )

    assert seen["url"] == "https://upload.wikimedia.org/thumb/celine.jpg"
    assert item["image_url"] == "https://upload.wikimedia.org/original/celine.jpg"
```

Append:

```python
@pytest.mark.asyncio
async def test_process_verified_candidate_rejects_non_image_content(monkeypatch):
    agent = RealImageAgent()

    async def fake_download_image_bytes(image_url: str) -> tuple[bytes, str]:
        return b"%PDF fake", "application/pdf"

    monkeypatch.setattr(agent, "_download_image_bytes", fake_download_image_bytes)

    with pytest.raises(ValueError, match="downloaded content is not an image"):
        await agent._process_verified_candidate(
            topic_id=1,
            scene_index=0,
            person_name="Celine Dion",
            expected_title="#10 Celine Dion",
            candidate={
                "download_url": "https://upload.wikimedia.org/file.pdf",
                "image_url": "https://upload.wikimedia.org/file.pdf",
                "source_url": "https://commons.wikimedia.org/wiki/File:Celine.pdf",
                "license": "CC BY-SA 4.0",
                "attribution": "Example",
                "metadata_text": "Celine Dion book pdf",
                "source_adapter": "commons_search_thumbnail",
                "identity_check_status": "passed",
                "identity_confidence": 0.95,
                "content_match_status": "passed",
                "content_match_reason": "test",
                "is_group_photo": False,
                "needs_human_review": False,
            },
        )
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py -v
```

Expected: FAIL on missing `download_url`, old `_download_image_bytes` return shape, and missing content-type validation.

- [ ] **Step 3: Implement thumbnail/download support**

Modify `_find_verified_image` API URL to include:

```python
f"&iiurlwidth=1200"
```

In `extract_wikimedia_candidate`, read:

```python
download_url = str(info.get("thumburl") or image_url).strip()
```

After `metadata_text`, call:

```python
identity = cls.evaluate_identity_match(person_name, metadata_text)
content = cls.evaluate_content_match(metadata_text, source_url)
if identity["identity_check_status"] != "passed":
    return None
if content["content_match_status"] != "passed":
    return None
```

Return candidate with `download_url`, `source_adapter`, and all identity/content fields.

Modify `_download_image_bytes` to return a tuple:

```python
return response.content, response.headers.get("content-type", "")
```

Modify `_process_verified_candidate`:

```python
download_url = candidate.get("download_url") or candidate["image_url"]
raw_bytes, content_type = await self._download_image_bytes(download_url)
if "image/" not in content_type.lower():
    raise ValueError("downloaded content is not an image")
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/real_image_agent.py tests/test_real_image_agent.py
git commit -m "feat: prefer verified Wikimedia thumbnails"
```

## Task 3: Candidate Fallback And Verification

**Files:**
- Modify: `tests/test_real_image_agent.py`
- Modify: `README.md`

- [ ] **Step 1: Write fallback test**

Append:

```python
@pytest.mark.asyncio
async def test_find_verified_image_tries_next_candidate_when_download_fails(monkeypatch, tmp_path):
    agent = RealImageAgent()
    calls = []

    pages = {
        "1": {
            "title": "File:Celine Dion bad.jpg",
            "imageinfo": [{
                "url": "https://upload.wikimedia.org/original/bad.jpg",
                "thumburl": "https://upload.wikimedia.org/thumb/bad.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Celine_bad.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "Artist": {"value": "A"},
                    "ImageDescription": {"value": "Celine Dion portrait"},
                },
            }],
        },
        "2": {
            "title": "File:Celine Dion good.jpg",
            "imageinfo": [{
                "url": "https://upload.wikimedia.org/original/good.jpg",
                "thumburl": "https://upload.wikimedia.org/thumb/good.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Celine_good.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "Artist": {"value": "B"},
                    "ImageDescription": {"value": "Celine Dion portrait"},
                },
            }],
        },
    }

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"query": {"pages": pages}}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs): return FakeResponse()

    image = Image.new("RGB", (640, 400), color="green")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")

    async def fake_download_image_bytes(url):
        calls.append(url)
        if "bad" in url:
            raise ValueError("blocked")
        return buffer.getvalue(), "image/jpeg"

    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("agents.real_image_agent.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(agent, "_download_image_bytes", fake_download_image_bytes)

    item = await agent._find_verified_image(
        topic_id=1,
        scene_index=0,
        person_name="Celine Dion",
        expected_title="#10 Celine Dion",
    )

    assert calls == [
        "https://upload.wikimedia.org/thumb/bad.jpg",
        "https://upload.wikimedia.org/thumb/good.jpg",
    ]
    assert item["status"] == "verified"
    assert item["image_url"] == "https://upload.wikimedia.org/original/good.jpg"
```

- [ ] **Step 2: Run focused fallback test**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py::test_find_verified_image_tries_next_candidate_when_download_fails -v
```

Expected: PASS if Task 2 already preserved next-candidate fallback; otherwise fix `_find_verified_image` to continue after candidate processing failures.

- [ ] **Step 3: Update README**

Add to the strict real image paragraph:

```markdown
The image gate also performs deterministic identity and content checks. Loose token matches are not enough: a result for `John Jay` must not pass for `Jay-Z`, non-photo media such as PDFs/books/logos are rejected, and group photos are marked for review instead of being used in strict renders.
```

- [ ] **Step 4: Full verification**

Run:

```bash
python3 -m pytest tests/test_real_image_agent.py tests/test_image_verification_contract.py tests/test_pipeline_local_render.py tests/test_reviews.py -v
python3 -m compileall api core agents workers tests
npm run build
```

Run `npm run build` from `video_engine`.

- [ ] **Step 5: Optional live smoke**

Run:

```bash
python3 - <<'PY'
import asyncio, json
from agents.pipeline import Pipeline

async def main():
    result = await Pipeline().run_local_render(category='Celebrity', language='vi')
    print(json.dumps({
        'file_path': result['file_path'],
        'review_id': result['review_id'],
        'image_status': result['image_verification_contract']['status'],
    }, ensure_ascii=False, indent=2))

asyncio.run(main())
PY
```

Expected: either verified render succeeds or strict gate fails with clear missing image reasons. Do not weaken strict mode.

- [ ] **Step 6: Commit and push**

```bash
git add README.md agents/real_image_agent.py tests/test_real_image_agent.py
git commit -m "feat: improve real image source reliability"
git push origin main
```

## Self-Review

- Spec coverage: covers thumbnail `download_url`, original `image_url` provenance, content/identity matching, non-image rejection, candidate fallback, docs, and verification.
- Placeholder scan: no TBD/TODO/fill-in work remains.
- Type consistency: candidate fields match spec: `download_url`, `image_url`, `source_adapter`, `identity_check_status`, `identity_confidence`, `content_match_status`, `content_match_reason`, `is_group_photo`, `needs_human_review`.
