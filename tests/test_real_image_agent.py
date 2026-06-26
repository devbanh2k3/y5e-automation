from io import BytesIO

from PIL import Image

from agents.real_image_agent import RealImageAgent
import pytest


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


def test_wikimedia_user_agent_includes_contact_and_project_url():
    assert "github.com/devbanh2k3/y5e-automation" in RealImageAgent.WIKIMEDIA_USER_AGENT
    assert "example.com" not in RealImageAgent.WIKIMEDIA_USER_AGENT


def test_wikimedia_headers_use_configurable_policy_identity(monkeypatch):
    monkeypatch.setenv(
        "WIKIMEDIA_USER_AGENT",
        "Y5E-TestBot/1.0 (https://github.com/devbanh2k3/y5e-automation; owner@example.org)",
    )
    monkeypatch.setenv("WIKIMEDIA_CONTACT_EMAIL", "owner@example.org")

    headers = RealImageAgent().wikimedia_headers(accept="application/json")

    assert headers == {
        "User-Agent": "Y5E-TestBot/1.0 (https://github.com/devbanh2k3/y5e-automation; owner@example.org)",
        "Api-User-Agent": "Y5E-TestBot/1.0 (https://github.com/devbanh2k3/y5e-automation; owner@example.org)",
        "From": "owner@example.org",
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }


def test_wikimedia_headers_reject_placeholder_identity(monkeypatch):
    monkeypatch.setenv(
        "WIKIMEDIA_USER_AGENT",
        "Y5E-TestBot/1.0 (https://example.com/y5e; devbanh@example.com)",
    )

    with pytest.raises(ValueError, match="must not use placeholder contact"):
        RealImageAgent().wikimedia_headers()


def test_wikimedia_search_queries_include_celebrity_disambiguation():
    assert RealImageAgent.wikimedia_search_queries("Celine Dion") == [
        "Celine Dion portrait",
        "Celine Dion singer",
    ]
    assert RealImageAgent.wikimedia_search_queries("Jay-Z") == [
        "Jay-Z portrait",
        "Jay-Z rapper",
        "Jay Z rapper",
        "Shawn Carter Jay-Z",
    ]


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


def test_extract_wikimedia_candidate_reads_license_and_attribution():
    page = {
        "title": "File:Celine Dion 2012.jpg",
        "imageinfo": [
            {
                "url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
                "thumburl": "https://upload.wikimedia.org/thumb/celine.jpg",
                "mime": "image/jpeg",
                "thumbmime": "image/jpeg",
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
        "download_url": "https://upload.wikimedia.org/thumb/celine.jpg",
        "image_url": "https://upload.wikimedia.org/wikipedia/commons/celine.jpg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Celine_Dion_2012.jpg",
        "license": "CC BY-SA 4.0",
        "attribution": "Example photographer",
        "metadata_text": "File:Celine Dion 2012.jpg CC BY-SA 4.0 Example photographer Celine Dion performing live",
        "mime": "image/jpeg",
        "thumbmime": "image/jpeg",
        "source_adapter": "commons_search_thumbnail",
        "identity_check_status": "passed",
        "identity_confidence": 0.95,
        "content_match_status": "passed",
        "content_match_reason": "metadata matches acceptable celebrity photo context",
        "is_group_photo": False,
        "needs_human_review": False,
    }


def test_extract_wikimedia_candidate_rejects_non_image_mime():
    page = {
        "title": "File:Celine Dion book.pdf",
        "imageinfo": [
            {
                "url": "https://upload.wikimedia.org/wikipedia/commons/celine.pdf",
                "thumburl": "https://upload.wikimedia.org/thumb/celine.jpg",
                "mime": "application/pdf",
                "thumbmime": "image/jpeg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Celine_Dion_book.pdf",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "Artist": {"value": "Example photographer"},
                    "ImageDescription": {"value": "Celine Dion portrait"},
                },
            }
        ],
    }

    assert RealImageAgent.extract_wikimedia_candidate("Celine Dion", page) is None


@pytest.mark.asyncio
async def test_process_verified_candidate_downloads_webp(monkeypatch, tmp_path):
    agent = RealImageAgent()
    image = Image.new("RGB", (640, 400), color="red")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")

    async def fake_download_image_bytes(image_url: str) -> tuple[bytes, str]:
        assert image_url == "https://upload.wikimedia.org/wikipedia/commons/celine.jpg"
        return buffer.getvalue(), "image/jpeg"

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


@pytest.mark.asyncio
async def test_find_verified_image_tries_next_candidate_when_download_fails(monkeypatch, tmp_path):
    agent = RealImageAgent()
    calls = []

    pages = {
        "1": {
            "title": "File:Celine Dion bad.jpg",
            "imageinfo": [
                {
                    "url": "https://upload.wikimedia.org/original/bad.jpg",
                    "thumburl": "https://upload.wikimedia.org/thumb/bad.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Celine_bad.jpg",
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "A"},
                        "ImageDescription": {"value": "Celine Dion portrait"},
                    },
                }
            ],
        },
        "2": {
            "title": "File:Celine Dion good.jpg",
            "imageinfo": [
                {
                    "url": "https://upload.wikimedia.org/original/good.jpg",
                    "thumburl": "https://upload.wikimedia.org/thumb/good.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Celine_good.jpg",
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "B"},
                        "ImageDescription": {"value": "Celine Dion portrait"},
                    },
                }
            ],
        },
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"query": {"pages": pages}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

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


@pytest.mark.asyncio
async def test_find_verified_image_tries_disambiguated_search_when_first_query_is_wrong(
    monkeypatch,
    tmp_path,
):
    agent = RealImageAgent()
    api_urls = []
    downloads = []

    wrong_pages = {
        "1": {
            "title": "File:John Jay portrait.jpg",
            "imageinfo": [
                {
                    "url": "https://upload.wikimedia.org/original/john-jay.jpg",
                    "thumburl": "https://upload.wikimedia.org/thumb/john-jay.jpg",
                    "mime": "image/jpeg",
                    "thumbmime": "image/jpeg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:John_Jay.jpg",
                    "extmetadata": {
                        "LicenseShortName": {"value": "Public domain"},
                        "Artist": {"value": "A"},
                        "ImageDescription": {"value": "John Jay portrait"},
                    },
                }
            ],
        }
    }
    good_pages = {
        "2": {
            "title": "File:Jay-Z 3.jpg",
            "imageinfo": [
                {
                    "url": "https://upload.wikimedia.org/original/jay-z.jpg",
                    "thumburl": "https://upload.wikimedia.org/thumb/jay-z.jpg",
                    "mime": "image/jpeg",
                    "thumbmime": "image/jpeg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Jay-Z_3.jpg",
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "B"},
                        "ImageDescription": {"value": "Jay-Z rapper portrait"},
                    },
                }
            ],
        }
    }

    class FakeResponse:
        def __init__(self, pages):
            self.pages = pages

        def raise_for_status(self):
            pass

        def json(self):
            return {"query": {"pages": self.pages}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            api_urls.append(url)
            if "Jay-Z+rapper" in url:
                return FakeResponse(good_pages)
            return FakeResponse(wrong_pages)

    image = Image.new("RGB", (640, 400), color="purple")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")

    async def fake_download_image_bytes(url):
        downloads.append(url)
        return buffer.getvalue(), "image/jpeg"

    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("agents.real_image_agent.httpx.AsyncClient", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(agent, "_download_image_bytes", fake_download_image_bytes)

    item = await agent._find_verified_image(
        topic_id=1,
        scene_index=9,
        person_name="Jay-Z",
        expected_title="#1 Jay-Z",
    )

    assert len(api_urls) == 2
    assert "Jay-Z+portrait" in api_urls[0]
    assert "Jay-Z+rapper" in api_urls[1]
    assert downloads == ["https://upload.wikimedia.org/thumb/jay-z.jpg"]
    assert item["status"] == "verified"
    assert item["image_url"] == "https://upload.wikimedia.org/original/jay-z.jpg"
