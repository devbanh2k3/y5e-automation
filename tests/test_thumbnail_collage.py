from pathlib import Path

from PIL import Image


def test_build_review_thumbnail_uses_three_verified_real_images(tmp_path: Path) -> None:
    from services.thumbnail_collage import build_review_thumbnail

    image_paths = []
    for index, color in enumerate(("red", "green", "blue")):
        path = tmp_path / f"real_{index}.jpg"
        Image.new("RGB", (500, 700), color=color).save(path)
        image_paths.append(path)

    scenes = [
        {
            "title": f"#{index + 1} Person {index + 1}",
            "statusText": f"TOP {index + 1}",
            "metricValue": f"{index + 1}M",
        }
        for index in range(3)
    ]
    result = build_review_thumbnail(
        review_id="review-1",
        topic_dir=tmp_path,
        content_contract={"hook": "Celebrity Data", "scenes": scenes},
        image_verification_contract={
            "items": [
                {"scene_index": index, "status": "verified", "local_path": str(path)}
                for index, path in enumerate(image_paths)
            ]
        },
        selected_metadata={"thumbnail_text": "TOP CELEBRITIES"},
    )

    assert result["status"] == "ready"
    thumbnail_path = Path(result["file_path"])
    assert thumbnail_path.is_file()
    with Image.open(thumbnail_path) as thumbnail:
        assert thumbnail.size == (1280, 720)
