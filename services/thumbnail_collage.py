"""Create YouTube thumbnails from the same verified card images used in video."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

THUMBNAIL_SIZE = (1280, 720)
PANEL_COUNT = 3


def build_review_thumbnail(
    *,
    review_id: str,
    topic_dir: Path,
    content_contract: dict[str, Any],
    image_verification_contract: dict[str, Any] | None,
    selected_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a 16:9 thumbnail from three verified scene images."""
    scenes = content_contract.get("scenes") if isinstance(content_contract.get("scenes"), list) else []
    image_items = (
        image_verification_contract.get("items")
        if isinstance(image_verification_contract, dict)
        and isinstance(image_verification_contract.get("items"), list)
        else []
    )
    selected = _select_items(image_items, scenes)
    if len(selected) < PANEL_COUNT:
        return {
            "status": "skipped",
            "reason": "not enough verified images for thumbnail",
            "file_path": "",
        }

    output_path = topic_dir / "thumbnail.jpg"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    title = str((selected_metadata or {}).get("thumbnail_text") or content_contract.get("hook") or "CELEBRITY DATA")
    canvas = Image.new("RGB", THUMBNAIL_SIZE, (10, 10, 12))
    panel_w = THUMBNAIL_SIZE[0] // PANEL_COUNT

    for panel_index, item in enumerate(selected[:PANEL_COUNT]):
        scene_index = int(item.get("scene_index", panel_index))
        scene = scenes[scene_index] if scene_index < len(scenes) and isinstance(scenes[scene_index], dict) else {}
        source = Path(str(item.get("local_path") or ""))
        if not source.is_file():
            render_path = str(item.get("render_image_path") or "")
            source = topic_dir / render_path
        image = Image.open(source).convert("RGB")
        box = (panel_index * panel_w, 0, panel_w, THUMBNAIL_SIZE[1])
        _paste_panel(canvas, image, box)
        _draw_panel_text(canvas, box, scene, panel_index)

    _draw_title_strip(canvas, title)
    canvas.save(output_path, format="JPEG", quality=92, optimize=True)
    return {
        "status": "ready",
        "file_path": str(output_path.resolve()),
        "source_scene_indexes": [int(item.get("scene_index", index)) for index, item in enumerate(selected[:PANEL_COUNT])],
        "width": THUMBNAIL_SIZE[0],
        "height": THUMBNAIL_SIZE[1],
    }


def _select_items(items: list[Any], scenes: list[Any]) -> list[dict[str, Any]]:
    verified = [item for item in items if isinstance(item, dict) and item.get("status") == "verified"]
    if not verified:
        return []
    last_indexes = {max(0, len(scenes) - 1), max(0, len(scenes) - 2), max(0, len(scenes) - 3)}
    preferred = [item for item in verified if int(item.get("scene_index", -1)) in last_indexes]
    remainder = [item for item in verified if item not in preferred]
    return (preferred + remainder)[:PANEL_COUNT]


def _paste_panel(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int]) -> None:
    left, top, width, height = box
    panel_size = (width, height)
    background = _cover(image, panel_size).filter(ImageFilter.GaussianBlur(radius=18))
    overlay = Image.new("RGB", panel_size, (0, 0, 0))
    background = Image.blend(background, overlay, 0.18)
    foreground = _contain(image, (width - 28, height - 132))
    x = left + (width - foreground.width) // 2
    y = top + 76 + (height - 132 - foreground.height) // 2
    canvas.paste(background, (left, top))
    canvas.paste(foreground, (x, y))


def _draw_panel_text(canvas: Image.Image, box: tuple[int, int, int, int], scene: dict[str, Any], panel_index: int) -> None:
    left, _top, width, height = box
    draw = ImageDraw.Draw(canvas)
    rank = str(scene.get("statusText") or scene.get("rankLabel") or f"#{panel_index + 1}").strip()
    name = _short_name(str(scene.get("title") or ""))
    metric = str(scene.get("metricValue") or scene.get("factValue") or "").strip()
    label_font = _font(36)
    name_font = _font(42)
    metric_font = _font(30)
    draw.rectangle((left, 0, left + width, 74), fill=(0, 0, 0))
    draw.text((left + 20, 18), rank.upper(), fill=(255, 255, 255), font=label_font)
    draw.rectangle((left, height - 112, left + width, height), fill=(45, 184, 238))
    draw.text((left + 18, height - 98), name.upper(), fill=(0, 0, 0), font=name_font)
    if metric:
        draw.text((left + 18, height - 46), metric.upper(), fill=(0, 0, 0), font=metric_font)
    if panel_index:
        draw.rectangle((left - 4, 0, left + 4, height), fill=(24, 24, 28))


def _draw_title_strip(canvas: Image.Image, title: str) -> None:
    draw = ImageDraw.Draw(canvas)
    clean = re.sub(r"\s+", " ", str(title).upper()).strip()[:38]
    font = _font(54)
    bbox = draw.textbbox((0, 0), clean, font=font)
    pad_x = 34
    strip_w = min(THUMBNAIL_SIZE[0] - 64, bbox[2] - bbox[0] + pad_x * 2)
    x = (THUMBNAIL_SIZE[0] - strip_w) // 2
    draw.rounded_rectangle((x, 18, x + strip_w, 88), radius=14, fill=(0, 0, 0), outline=(255, 255, 255), width=3)
    text_x = x + (strip_w - (bbox[2] - bbox[0])) // 2
    draw.text((text_x, 25), clean, fill=(255, 255, 255), font=font)


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = min(target_w / image.width, target_h / image.height)
    return image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _short_name(value: str) -> str:
    clean = re.sub(r"^#\s*\d+\s*", "", value).strip()
    return clean[:22] or "CELEBRITY"
