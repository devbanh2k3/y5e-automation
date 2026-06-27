from pathlib import Path

import pytest

from core.config import get_settings
from core.quality_gate import ProductionQualityGateError, run_production_quality_gate
from core.video_contract import build_content_contract_v2


def _fact_contract(*, low_confidence: bool = False):
    return {
        "schema_version": "fact_verification_contract_v1",
        "verification_policy": "ai_only_independent_pass",
        "status": "ai_verified" if not low_confidence else "rejected",
        "required_count": 2,
        "verified_count": 2 if not low_confidence else 1,
        "corrected_count": 0,
        "rejected_count": 0 if not low_confidence else 1,
        "items": [
            {
                "scene_index": 0,
                "person_name": "Celine Dion",
                "metric_label": "NET WORTH",
                "original_value": "550M USD",
                "verified_value": "550M USD",
                "unit": "USD",
                "as_of": "2026",
                "status": "verified" if not low_confidence else "rejected",
                "confidence": 0.92 if not low_confidence else 0.5,
                "reason": "Public estimate check.",
                "knowledge_cutoff_risk": "medium",
            },
            {
                "scene_index": 1,
                "person_name": "Taylor Swift",
                "metric_label": "NET WORTH",
                "original_value": "1.6B USD",
                "verified_value": "1.6B USD",
                "unit": "USD",
                "as_of": "2026",
                "status": "verified",
                "confidence": 0.93,
                "reason": "Public estimate check.",
                "knowledge_cutoff_risk": "medium",
            },
        ],
    }


def _contracts(topic_id: int, *, card_layout: str = "flag_hero", factual: bool = False):
    scenes = [
        {
            "title": "#2 Celine Dion",
            "voiceover": "Celine Dion has a public estimate.",
            "caption": "550M USD",
            "image_prompt": "real photo of Celine Dion",
            "statusText": "#2 | 550M USD",
            "countryCode": "CA",
            "countryLabel": "CANADA",
            "metricLabel": "NET WORTH",
            "metricValue": "550M USD",
            **(
                {
                    "factClaim": "Celine Dion has an estimated public net worth of 550M USD.",
                    "factValue": "550M USD",
                    "factUnit": "USD",
                    "factAsOf": "2026",
                    "factContext": "public celebrity net worth estimate",
                }
                if factual
                else {}
            ),
        },
        {
            "title": "#1 Taylor Swift",
            "voiceover": "Taylor Swift has a public estimate.",
            "caption": "1.6B USD",
            "image_prompt": "real photo of Taylor Swift",
            "statusText": "#1 | 1.6B USD",
            "countryCode": "US",
            "countryLabel": "UNITED STATES",
            "metricLabel": "NET WORTH",
            "metricValue": "1.6B USD",
            **(
                {
                    "factClaim": "Taylor Swift has an estimated public net worth of 1.6B USD.",
                    "factValue": "1.6B USD",
                    "factUnit": "USD",
                    "factAsOf": "2026",
                    "factContext": "public celebrity net worth estimate",
                }
                if factual
                else {}
            ),
        },
    ]
    content_contract = build_content_contract_v2(
        niche="celebrity",
        title="Top Celebrity",
        hook="Hook",
        target_audience="Fans",
        language="vi",
        scenes=scenes,
        thumbnail_prompt="thumbnail",
        youtube_title="Top Celebrity",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        duration_target=60,
        cardLayout=card_layout,
        contentFormat="ranking" if factual else None,
        metricScope="public net worth estimates" if factual else "",
        timeScope="through 2026" if factual else "",
    )
    video_data = {
        "template": "timeline",
        "cardLayout": card_layout,
        "title": "Top Celebrity",
        "subtitle": "Hook",
        "category": "celebrity",
        "language": "vi",
        "cards": [
            {
                "header": "TOP 2",
                "title": "#2 Celine Dion",
                "description": "Celine Dion has a public estimate.",
                "imagePath": "images/real_0.webp",
                "countryCode": "CA",
                "countryLabel": "CANADA",
                "metricLabel": "NET WORTH",
                "metricValue": "550M USD",
                "statusText": "#2 | 550M USD",
            },
            {
                "header": "TOP 1",
                "title": "#1 Taylor Swift",
                "description": "Taylor Swift has a public estimate.",
                "imagePath": "images/real_1.webp",
                "countryCode": "US",
                "countryLabel": "UNITED STATES",
                "metricLabel": "NET WORTH",
                "metricValue": "1.6B USD",
                "statusText": "#1 | 1.6B USD",
            },
        ],
    }
    image_contract = {
        "schema_version": "image_verification_contract_v1",
        "topic_id": topic_id,
        "source_policy": "wikimedia_commons_strict",
        "required_count": 2,
        "verified_count": 2,
        "status": "verified",
        "items": [
            {
                "scene_index": index,
                "person_name": scenes[index]["title"].split(" ", 1)[1],
                "expected_title": scenes[index]["title"],
                "status": "verified",
                "confidence": 0.92,
                "local_path": str(Path("/tmp") / f"real_{index}.webp"),
                "render_image_path": f"images/real_{index}.webp",
                "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                "image_url": "https://upload.wikimedia.org/wikipedia/commons/example.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "Example photographer",
                "quality_score": 0.82,
                "quality_reason": "portrait or stage photo metadata",
                "identity_confidence": 0.95,
                "content_match_status": "passed",
                "needs_human_review": False,
                "reject_reason": "",
            }
            for index in range(2)
        ],
    }
    return content_contract, video_data, image_contract


def _write_render_files(tmp_path: Path, topic_id: int) -> Path:
    topic_dir = tmp_path / "topics" / str(topic_id)
    (topic_dir / "images").mkdir(parents=True)
    (topic_dir / "final_video.mp4").write_bytes(b"fake mp4")
    (topic_dir / "images" / "real_0.webp").write_bytes(b"image 0")
    (topic_dir / "images" / "real_1.webp").write_bytes(b"image 1")
    return topic_dir


def test_quality_gate_passes_verified_render(tmp_path, monkeypatch):
    get_settings.cache_clear()


def test_quality_gate_passes_factual_render_with_fact_evidence(tmp_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    topic_id = 321
    topic_dir = _write_render_files(tmp_path, topic_id)
    content_contract, video_data, image_contract = _contracts(topic_id, factual=True)

    result = run_production_quality_gate(
        topic_id=topic_id,
        video_path=str(topic_dir / "final_video.mp4"),
        video_data=video_data,
        content_contract=content_contract,
        fact_verification_contract=_fact_contract(),
        image_verification_contract=image_contract,
        expected_card_layout="flag_hero",
    )

    fact_checks = [check for check in result["checks"] if check["name"].startswith("fact_")]
    assert result["status"] == "passed"
    assert fact_checks
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("fact_contract", "mutate", "message"),
    [
        (None, None, "fact verification contract is required"),
        (_fact_contract(low_confidence=True), None, "all facts must be AI verified"),
        (_fact_contract(), lambda _, video_data: video_data["cards"][0].update({"metricValue": "999M USD"}), "verified_value"),
        (_fact_contract(), lambda content_contract, _: content_contract["scenes"].pop(), "fact item count"),
    ],
)
def test_quality_gate_rejects_factual_evidence_blockers(
    tmp_path,
    monkeypatch,
    fact_contract,
    mutate,
    message,
):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    topic_id = 654
    topic_dir = _write_render_files(tmp_path, topic_id)
    content_contract, video_data, image_contract = _contracts(topic_id, factual=True)
    if mutate:
        mutate(content_contract, video_data)

    with pytest.raises(ProductionQualityGateError, match=message):
        run_production_quality_gate(
            topic_id=topic_id,
            video_path=str(topic_dir / "final_video.mp4"),
            video_data=video_data,
            content_contract=content_contract,
            fact_verification_contract=fact_contract,
            image_verification_contract=image_contract,
            expected_card_layout="flag_hero",
        )
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    topic_id = 123
    topic_dir = tmp_path / "topics" / str(topic_id)
    (topic_dir / "images").mkdir(parents=True)
    (topic_dir / "final_video.mp4").write_bytes(b"fake mp4")
    (topic_dir / "images" / "real_0.webp").write_bytes(b"image 0")
    (topic_dir / "images" / "real_1.webp").write_bytes(b"image 1")
    content_contract, video_data, image_contract = _contracts(topic_id)

    result = run_production_quality_gate(
        topic_id=topic_id,
        video_path=str(topic_dir / "final_video.mp4"),
        video_data=video_data,
        content_contract=content_contract,
        image_verification_contract=image_contract,
        expected_card_layout="flag_hero",
    )

    assert result["status"] == "passed"
    assert result["required_checks"] >= 8
    get_settings.cache_clear()


def test_quality_gate_accepts_baseline_verified_identity_score(tmp_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    topic_id = 789
    topic_dir = tmp_path / "topics" / str(topic_id)
    (topic_dir / "images").mkdir(parents=True)
    (topic_dir / "final_video.mp4").write_bytes(b"fake mp4")
    (topic_dir / "images" / "real_0.webp").write_bytes(b"image 0")
    (topic_dir / "images" / "real_1.webp").write_bytes(b"image 1")
    content_contract, video_data, image_contract = _contracts(topic_id)
    image_contract["items"][0]["quality_score"] = 0.58

    result = run_production_quality_gate(
        topic_id=topic_id,
        video_path=str(topic_dir / "final_video.mp4"),
        video_data=video_data,
        content_contract=content_contract,
        image_verification_contract=image_contract,
        expected_card_layout="flag_hero",
    )

    assert result["status"] == "passed"
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda _, video_data, __: video_data["cards"][0].update({"imagePath": "images/local-placeholder.svg"}), "placeholder"),
        (lambda _, video_data, __: video_data.update({"cardLayout": "split_data"}), "cardLayout"),
        (lambda _, __, image_contract: image_contract["items"][1].update({"render_image_path": "images/real_9.webp"}), "render_image_path"),
        (lambda _, __, image_contract: image_contract["items"][0].update({"quality_score": 0.4}), "quality_score"),
    ],
)
def test_quality_gate_rejects_production_blockers(tmp_path, monkeypatch, mutate, message):
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    topic_id = 456
    topic_dir = tmp_path / "topics" / str(topic_id)
    (topic_dir / "images").mkdir(parents=True)
    (topic_dir / "final_video.mp4").write_bytes(b"fake mp4")
    (topic_dir / "images" / "real_0.webp").write_bytes(b"image 0")
    (topic_dir / "images" / "real_1.webp").write_bytes(b"image 1")
    content_contract, video_data, image_contract = _contracts(topic_id)
    mutate(content_contract, video_data, image_contract)

    with pytest.raises(ProductionQualityGateError, match=message):
        run_production_quality_gate(
            topic_id=topic_id,
            video_path=str(topic_dir / "final_video.mp4"),
            video_data=video_data,
            content_contract=content_contract,
            image_verification_contract=image_contract,
            expected_card_layout="flag_hero",
        )
    get_settings.cache_clear()
