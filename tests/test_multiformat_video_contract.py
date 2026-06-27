import pytest

from core.video_contract import (
    VideoContractError,
    build_content_contract_v2,
    build_video_data_from_content_contract,
)


def scene(title="#1 Taylor Swift", value="14", **overrides):
    item = {
        "title": title,
        "voiceover": "A concise factual statement.",
        "caption": value,
        "image_prompt": "real editorial photo of Taylor Swift",
        "statusText": value,
        "countryCode": "US",
        "countryLabel": "UNITED STATES",
        "metricLabel": "GRAMMY WINS",
        "metricValue": value,
        "factClaim": "Taylor Swift has 14 Grammy wins",
        "factValue": value,
        "factUnit": "awards",
        "factAsOf": "2026",
        "factContext": "Grammy wins through 2026",
    }
    item.update(overrides)
    return item


def contract(content_format, scenes):
    return build_content_contract_v2(
        niche="celebrity",
        title="Facts",
        hook="Hook",
        target_audience="Fans",
        language="en",
        scenes=scenes,
        thumbnail_prompt="Thumbnail",
        youtube_title="Facts",
        youtube_description="Description",
        youtube_tags=["celebrity"],
        duration_target=60,
        cardLayout="flag_hero",
        contentFormat=content_format,
        metricScope="public records",
        timeScope="2026",
    )


@pytest.mark.parametrize(
    ("content_format", "value", "expected_header"),
    [
        ("ranking", "14", "TOP 1"),
        ("fact_collection", "14", "FACT 1"),
        ("timeline", "2006", "MILESTONE"),
        ("record_comparison", "14", "RECORD"),
        ("before_after", "2006 / 2026", "THEN / NOW"),
        ("count_comparison", "14", "COUNT"),
        ("binary_comparison", "YES", "YES"),
    ],
)
def test_build_video_data_uses_format_header(
    content_format,
    value,
    expected_header,
):
    payload = contract(content_format, [scene(value=value, factValue=value)])

    assert build_video_data_from_content_contract(payload)["cards"][0]["header"] == expected_header


def test_factual_format_rejects_unscoped_scene():
    payload = contract("count_comparison", [scene(factAsOf="", factContext="")])

    with pytest.raises(VideoContractError, match="factAsOf"):
        build_video_data_from_content_contract(payload)
