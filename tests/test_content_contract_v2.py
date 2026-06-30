import pytest

from core.video_contract import (
    VideoContractError,
    build_content_contract_v2,
    build_video_data_from_content_contract,
    validate_country_metadata,
    validate_content_contract_v2,
    validate_video_data,
)


def test_build_content_contract_v2_for_celebrity_is_complete():
    contract = build_content_contract_v2(
        niche="celebrity",
        title="3 bài học từ cách người nổi tiếng xây dựng thương hiệu cá nhân",
        hook="Không phải ai nổi tiếng cũng giữ được sự chú ý lâu dài.",
        target_audience="Người xem Việt Nam thích câu chuyện hậu trường và bài học phát triển bản thân.",
        language="vi",
        scenes=[
            {
                "title": "Khoảnh khắc tạo dấu ấn",
                "voiceover": "Điểm chung đầu tiên là họ có một hình ảnh rất dễ nhớ.",
                "caption": "Dấu ấn cá nhân",
                "image_prompt": "Vietnamese celebrity-inspired stage spotlight, editorial, no real logo",
                "statusText": "BÀI HỌC 1",
            },
            {
                "title": "Câu chuyện khiến khán giả theo dõi",
                "voiceover": "Khán giả không chỉ xem thành tích, họ theo dõi hành trình.",
                "caption": "Câu chuyện",
                "image_prompt": "cinematic behind the scenes portrait, respectful, documentary style",
                "statusText": "BÀI HỌC 2",
            },
            {
                "title": "Kỷ luật sau ánh đèn",
                "voiceover": "Đằng sau sự nổi tiếng là lịch làm việc, luyện tập và đội ngũ.",
                "caption": "Kỷ luật",
                "image_prompt": "practice room, microphone, notes, professional lighting",
                "statusText": "BÀI HỌC 3",
            },
        ],
        thumbnail_prompt="Vietnamese celebrity story thumbnail, bright face light, bold text area",
        youtube_title="3 bài học thương hiệu cá nhân từ người nổi tiếng",
        youtube_description="Một video phân tích cách người nổi tiếng tạo dấu ấn và giữ sự chú ý.",
        youtube_tags=["nguoi noi tieng", "thuong hieu ca nhan", "giai tri"],
        duration_target=45,
    )

    validate_content_contract_v2(contract)

    assert contract["schema_version"] == "content_contract_v2"
    assert contract["niche"] == "celebrity"
    assert contract["duration_target"] == 45
    assert len(contract["scenes"]) == 3
    assert contract["scenes"][0]["caption"] == "Dấu ấn cá nhân"
    assert contract["youtube_tags"] == [
        "nguoi noi tieng",
        "thuong hieu ca nhan",
        "giai tri",
    ]


def test_build_video_data_from_content_contract_maps_scenes_to_cards():
    contract = build_content_contract_v2(
        niche="celebrity",
        title="Câu chuyện phía sau sự nổi tiếng",
        hook="Sự nổi tiếng không chỉ đến từ may mắn.",
        target_audience="Người xem Việt Nam",
        language="vi",
        scenes=[
                {
                    "title": "Dấu ấn đầu tiên",
                    "voiceover": "Một hình ảnh rõ ràng giúp khán giả nhớ tới họ.",
                    "caption": "Dấu ấn",
                    "image_prompt": "spotlight portrait",
                    "statusText": "MỞ ĐẦU",
                    "countryCode": "US",
                    "countryLabel": "UNITED STATES",
                    "metricLabel": "NET WORTH",
                    "metricValue": "550M USD",
                }
            ],
        thumbnail_prompt="celebrity thumbnail",
        youtube_title="Câu chuyện phía sau sự nổi tiếng",
        youtube_description="Phân tích nhanh.",
        youtube_tags=["celebrity"],
        duration_target=30,
    )

    video_data = build_video_data_from_content_contract(contract)
    validate_video_data(video_data)

    assert video_data["title"] == "Câu chuyện phía sau sự nổi tiếng"
    assert video_data["template"] == "timeline"
    assert video_data["cardLayout"] == "classic"
    assert video_data["targetDuration"] == 30
    assert video_data["subtitle"] == "Sự nổi tiếng không chỉ đến từ may mắn."
    assert video_data["cards"][0]["header"] == "TOP 1"
    assert video_data["cards"][0]["title"] == "Dấu ấn đầu tiên"
    assert video_data["cards"][0]["description"] == "Một hình ảnh rõ ràng giúp khán giả nhớ tới họ."
    assert video_data["cards"][0]["statusText"] == "MỞ ĐẦU"
    assert video_data["cards"][0]["countryCode"] == "US"
    assert video_data["cards"][0]["countryLabel"] == "UNITED STATES"
    assert video_data["cards"][0]["metricLabel"] == "NET WORTH"
    assert video_data["cards"][0]["metricValue"] == "550M USD"


def test_build_video_data_from_content_contract_keeps_stable_slide_pacing():
    scenes = [
        {
            "title": f"#{10 - index} Celebrity {index}",
            "voiceover": "Concise factual line.",
            "caption": "100M USD",
            "image_prompt": "real editorial photo",
            "statusText": f"#{10 - index} | 100M USD",
            "countryCode": "US",
            "countryLabel": "UNITED STATES",
            "metricLabel": "NET WORTH",
            "metricValue": "100M USD",
        }
        for index in range(10)
    ]
    contract = build_content_contract_v2(
        niche="celebrity",
        title="Top Celebrity Test",
        hook="Hook",
        target_audience="Viewers",
        language="en",
        scenes=scenes,
        thumbnail_prompt="thumbnail",
        youtube_title="Top Celebrity Test",
        youtube_description="Description.",
        youtube_tags=["celebrity"],
        duration_target=90,
    )

    video_data = build_video_data_from_content_contract(contract)
    assert video_data["holdDurationFrames"] == 120
    assert video_data["transitionDurationFrames"] == 15


def test_validate_country_metadata_rejects_wrong_flag_label_pairing():
    validate_country_metadata({"countryCode": "CA", "countryLabel": "CANADA"}, index=0)
    validate_country_metadata({"countryCode": "JP", "countryLabel": "JAPAN"}, index=1)

    with pytest.raises(VideoContractError, match="countryLabel must be CANADA"):
        validate_country_metadata({"countryCode": "CA", "countryLabel": "UNITED STATES"}, index=0)

    with pytest.raises(VideoContractError, match="countryCode is not supported"):
        validate_country_metadata({"countryCode": "XX", "countryLabel": "UNKNOWN"}, index=0)


def test_validate_content_contract_v2_rejects_empty_scenes():
    contract = build_content_contract_v2(
        niche="celebrity",
        title="Thiếu cảnh",
        hook="Hook",
        target_audience="Người xem Việt Nam",
        language="vi",
        scenes=[],
        thumbnail_prompt="thumbnail",
        youtube_title="title",
        youtube_description="description",
        youtube_tags=["celebrity"],
        duration_target=30,
    )

    with pytest.raises(VideoContractError, match="scenes must contain at least one scene"):
        validate_content_contract_v2(contract)
