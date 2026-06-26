from agents.video_agent import build_video_result


def test_build_video_result_exposes_id_and_video_id():
    result = build_video_result(
        video_id=42,
        file_path="/tmp/final.mp4",
        duration_sec=123,
        resolution="1920x1080",
    )

    assert result["id"] == 42
    assert result["video_id"] == 42
    assert result["file_path"] == "/tmp/final.mp4"
    assert result["duration_sec"] == 123
    assert result["resolution"] == "1920x1080"
