"""Thumbnail generation agent — creates click-optimised YouTube thumbnails."""

from __future__ import annotations

import json
import logging
import math
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from agents.base_agent import BaseAgent
from core import database as db
from core.config import get_settings
from core.storage import get_asset_path

logger = logging.getLogger(__name__)

# YouTube recommended thumbnail size
THUMB_WIDTH = 1280
THUMB_HEIGHT = 720

# Maximum JPEG file size (2 MB)
_MAX_FILE_BYTES = 2 * 1024 * 1024

# Font search paths (macOS → Linux → bundled)
_FONT_SEARCH_PATHS: list[str] = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/Impact.ttf",
]

# Category badge colours
_BADGE_COLOURS: dict[str, str] = {
    "WhatIf": "#E63946",
    "Timeline": "#457B9D",
    "History": "#2A9D8F",
    "Ranking": "#E9C46A",
    "Comparison": "#F4A261",
    "Science": "#264653",
    "Geography": "#6A994E",
    "Evolution": "#BC6C25",
}

_DEFAULT_BADGE_COLOUR = "#333333"


class ThumbnailAgent(BaseAgent):
    """Generates YouTube thumbnails optimised for CTR.

    Creates a 1280×720 composite with:
    - Full-bleed background image (best available from assets)
    - Dark gradient overlay for text contrast
    - Bold title text with black outline
    - Category badge
    - AI-scored CTR prediction
    """

    def __init__(self) -> None:
        super().__init__(name="thumbnail_agent")
        self._settings = get_settings()
        self._project_root = Path(__file__).resolve().parent.parent

    # ── Public entry point ────────────────────────────────────

    async def run(self, topic_id: int) -> dict[str, Any]:  # type: ignore[override]
        """Generate a thumbnail for the given topic.

        Args:
            topic_id: The topic to create a thumbnail for.

        Returns:
            Dict with ``file_path``, ``score``, and ``text_used``.
        """
        await self.log(topic_id, "running")

        try:
            # 1. Fetch topic + script + channel style
            topic = await self._fetch_topic(topic_id)
            if topic is None:
                raise ValueError(f"Topic {topic_id} not found")

            script = await self._fetch_script(topic_id)
            thumbnail_style = await self._fetch_thumbnail_style(topic_id)

            # 2. Select the best background image
            image_path = await self._select_best_image(topic_id)

            # 3. Generate short title text via AI
            title_text = await self._generate_title_text(
                full_title=topic["title"],
                category=topic.get("category", ""),
            )

            # 4. Build the thumbnail
            category: str = topic.get("category", "")
            output_path = get_asset_path(topic_id, "thumbnail.jpg")

            self._render_thumbnail(
                image_path=image_path,
                title_text=title_text,
                category=category,
                output_path=output_path,
                thumbnail_style=thumbnail_style,
            )

            # 5. Score with AI
            image_desc = f"Background from section image for '{topic['title']}'"
            layout_desc = "Bold white text top-left, dark gradient, category badge top-right"
            score_data = await self._score_thumbnail(
                image_description=image_desc,
                text=title_text,
                layout_description=layout_desc,
            )
            score: int = score_data.get("score", 0)
            feedback: str = score_data.get("feedback", "")

            # 6. Store asset
            await self.save_asset(
                topic_id=topic_id,
                asset_type="thumbnail",
                file_path=str(output_path),
                license_type="original",
                title_text=title_text,
                score=score,
                feedback=feedback,
            )

            await self.log(topic_id, "completed")
            await self.notify(
                f"🖼️ Thumbnail for topic <b>{topic_id}</b> — "
                f"score {score}/100, text: \"{title_text}\""
            )

            return {
                "file_path": str(output_path),
                "score": score,
                "text_used": title_text,
            }

        except Exception as exc:
            await self.log(topic_id, "failed", error=str(exc))
            raise

    # ── Image selection ───────────────────────────────────────

    async def _select_best_image(self, topic_id: int) -> Path | None:
        """Find the most visually striking image from the topic's assets.

        Heuristic: prefer images from earlier sections (typically more
        dramatic/relevant to the overall topic) and choose the largest
        file on disk (usually highest quality).

        Args:
            topic_id: Topic ID.

        Returns:
            Path to the best image, or ``None`` if none found.
        """
        assets = await db.fetch(
            """
            SELECT file_path, metadata
            FROM assets
            WHERE topic_id = $1 AND asset_type = 'image'
            ORDER BY id ASC
            """,
            topic_id,
        )

        if not assets:
            return None

        best_path: Path | None = None
        best_size: int = 0

        for asset in assets:
            path = Path(asset["file_path"])
            if not path.is_file():
                continue

            file_size = path.stat().st_size
            metadata = asset.get("metadata", {})
            if isinstance(metadata, str):
                metadata = json.loads(metadata)

            # Boost score for section_index 0 (main topic image)
            section_idx: int = metadata.get("section_index", 99)
            effective_size = file_size * (2 if section_idx == 0 else 1)

            if effective_size > best_size:
                best_size = effective_size
                best_path = path

        return best_path

    # ── Title text generation ─────────────────────────────────

    async def _generate_title_text(
        self, full_title: str, category: str
    ) -> str:
        """Use AI to extract a short, punchy thumbnail title (max 5 words).

        Args:
            full_title: The full topic title.
            category: Topic category.

        Returns:
            A short uppercase title string.
        """
        prompt = f"""Extract a short, punchy thumbnail title (maximum 5 words) from this video title.
The title should be:
- Emotionally provocative or curiosity-inducing
- ALL CAPS for visual impact
- No more than 5 words
- Category context: {category}

Full title: "{full_title}"

Return ONLY the short title text, nothing else. No quotes, no explanation.
"""
        try:
            result = await self.ai(
                prompt=prompt,
                system="You are a YouTube thumbnail designer. Return only the short title.",
            )
            # Clean and limit
            text = result.strip().strip('"').strip("'").upper()
            words = text.split()
            if len(words) > 5:
                text = " ".join(words[:5])
            return text

        except Exception:
            self.logger.exception("AI title generation failed — using fallback")
            # Fallback: take first 5 words of the original title
            words = full_title.split()[:5]
            return " ".join(words).upper()

    # ── Thumbnail rendering ───────────────────────────────────

    def _render_thumbnail(
        self,
        image_path: Path | None,
        title_text: str,
        category: str,
        output_path: Path,
        thumbnail_style: str = "",
    ) -> None:
        """Create the final thumbnail image using PIL.

        Args:
            image_path: Background image path (or None for solid colour).
            title_text: Bold title text to overlay.
            category: Topic category (for badge colour).
            output_path: Where to save the JPEG.
            thumbnail_style: Optional style hints from reference channel.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Create canvas
        canvas = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), (20, 20, 30))

        # Place background image
        if image_path and image_path.is_file():
            canvas = self._place_background(canvas, image_path)

        draw = ImageDraw.Draw(canvas)

        # Apply gradient overlay
        canvas = self._apply_gradient(canvas)
        draw = ImageDraw.Draw(canvas)

        # Load font
        title_font = self._load_font(size=90)
        badge_font = self._load_font(size=28)

        # Draw title text with outline
        self._draw_outlined_text(
            draw=draw,
            text=title_text,
            position=(60, THUMB_HEIGHT - 240),
            font=title_font,
            fill=(255, 255, 255),
            outline_fill=(0, 0, 0),
            stroke_width=4,
            max_width=THUMB_WIDTH - 120,
        )

        # Draw category badge (top-right, avoiding bottom-right YouTube badge area)
        if category:
            self._draw_badge(
                draw=draw,
                text=category.upper(),
                position=(THUMB_WIDTH - 40, 40),
                font=badge_font,
                colour=_BADGE_COLOURS.get(category, _DEFAULT_BADGE_COLOUR),
            )

        # Draw channel logo (top-left)
        canvas = self._overlay_logo(canvas)

        # Save as JPEG, reduce quality if needed to meet size limit
        self._save_jpeg(canvas, output_path)

    @staticmethod
    def _place_background(canvas: Image.Image, image_path: Path) -> Image.Image:
        """Resize and crop the background image to fill the canvas.

        Args:
            canvas: The target canvas.
            image_path: Source image.

        Returns:
            The canvas with the background placed.
        """
        try:
            with Image.open(image_path) as bg:
                if bg.mode != "RGB":
                    bg = bg.convert("RGB")

                # Cover-fill: scale up to cover entire canvas, then centre-crop
                bg_w, bg_h = bg.size
                scale = max(THUMB_WIDTH / bg_w, THUMB_HEIGHT / bg_h)
                new_w = round(bg_w * scale)
                new_h = round(bg_h * scale)
                bg = bg.resize((new_w, new_h), Image.LANCZOS)

                # Centre crop
                left = (new_w - THUMB_WIDTH) // 2
                top = (new_h - THUMB_HEIGHT) // 2
                bg = bg.crop((left, top, left + THUMB_WIDTH, top + THUMB_HEIGHT))

                # Slight blur for depth of field effect (keeps text readable)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=1.5))

                canvas.paste(bg, (0, 0))
        except Exception:
            logger.exception("Failed to load background image: %s", image_path)

        return canvas

    @staticmethod
    def _apply_gradient(canvas: Image.Image) -> Image.Image:
        """Apply a dark gradient overlay from bottom to top for text contrast.

        The bottom 60% of the image gets a darkening gradient.

        Args:
            canvas: Source image.

        Returns:
            Image with gradient applied.
        """
        gradient = Image.new("RGBA", (THUMB_WIDTH, THUMB_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(gradient)

        # Bottom-to-top gradient (dark at bottom, transparent at top)
        gradient_start = int(THUMB_HEIGHT * 0.3)  # Start at 30% from top
        for y in range(gradient_start, THUMB_HEIGHT):
            # Opacity increases from 0 to ~200 (out of 255)
            progress = (y - gradient_start) / (THUMB_HEIGHT - gradient_start)
            alpha = int(200 * progress)
            draw.line([(0, y), (THUMB_WIDTH, y)], fill=(0, 0, 0, alpha))

        # Also add a slight top vignette for the badge/logo area
        for y in range(0, int(THUMB_HEIGHT * 0.15)):
            progress = 1.0 - (y / (THUMB_HEIGHT * 0.15))
            alpha = int(100 * progress)
            draw.line([(0, y), (THUMB_WIDTH, y)], fill=(0, 0, 0, alpha))

        # Composite
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba = Image.alpha_composite(canvas_rgba, gradient)
        return canvas_rgba.convert("RGB")

    @staticmethod
    def _draw_outlined_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        position: tuple[int, int],
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        fill: tuple[int, int, int],
        outline_fill: tuple[int, int, int],
        stroke_width: int,
        max_width: int,
    ) -> None:
        """Draw text with a black outline, wrapping if it exceeds max_width.

        Args:
            draw: PIL ImageDraw instance.
            text: Text to render.
            position: (x, y) top-left anchor.
            font: Font to use.
            fill: Text fill colour.
            outline_fill: Outline colour.
            stroke_width: Outline thickness.
            max_width: Maximum text width before wrapping.
        """
        # Word-wrap the text
        lines = _wrap_text(text, font, max_width)

        x, y = position
        line_spacing = 10

        for line in lines:
            # Draw with stroke (outline)
            draw.text(
                (x, y),
                line,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=outline_fill,
            )
            # Get line height
            bbox = font.getbbox(line)
            line_height = bbox[3] - bbox[1] if bbox else 90
            y += line_height + line_spacing

    @staticmethod
    def _draw_badge(
        draw: ImageDraw.ImageDraw,
        text: str,
        position: tuple[int, int],
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        colour: str,
    ) -> None:
        """Draw a coloured category badge.

        Args:
            draw: PIL ImageDraw instance.
            text: Badge text.
            position: (right_x, top_y) — badge is right-aligned.
            font: Font for badge text.
            colour: Hex colour string.
        """
        # Measure text
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0] if bbox else len(text) * 16
        text_h = bbox[3] - bbox[1] if bbox else 28

        padding_x = 16
        padding_y = 8
        badge_w = text_w + padding_x * 2
        badge_h = text_h + padding_y * 2

        right_x, top_y = position
        left_x = right_x - badge_w

        # Draw rounded rectangle
        draw.rounded_rectangle(
            [left_x, top_y, right_x, top_y + badge_h],
            radius=6,
            fill=colour,
        )

        # Draw text centred in badge
        text_x = left_x + padding_x
        text_y = top_y + padding_y
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255))

    def _overlay_logo(self, canvas: Image.Image) -> Image.Image:
        """Overlay the channel logo in the top-left corner.

        Args:
            canvas: The thumbnail canvas.

        Returns:
            Canvas with logo composited (unchanged if logo not found).
        """
        logo_path = self._project_root / "assets" / "branding" / "logo.png"
        if not logo_path.is_file():
            return canvas

        try:
            with Image.open(logo_path) as logo:
                # Resize logo to 60px height, maintaining aspect ratio
                logo_h = 60
                aspect = logo.width / logo.height
                logo_w = round(logo_h * aspect)
                logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

                if logo.mode == "RGBA":
                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba.paste(logo, (40, 40), mask=logo.split()[3])
                    return canvas_rgba.convert("RGB")
                else:
                    canvas.paste(logo, (40, 40))
        except Exception:
            self.logger.exception("Failed to overlay logo")

        return canvas

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Load a bold font, falling back through system paths and bundled fonts.

        Args:
            size: Desired font size in pixels.

        Returns:
            A PIL font object.
        """
        # Check bundled fonts first
        bundled_dir = self._project_root / "assets" / "fonts"
        if bundled_dir.is_dir():
            for font_file in bundled_dir.iterdir():
                if font_file.suffix.lower() in (".ttf", ".otf"):
                    try:
                        return ImageFont.truetype(str(font_file), size)
                    except (OSError, IOError):
                        continue

        # Try system fonts
        for font_path in _FONT_SEARCH_PATHS:
            try:
                return ImageFont.truetype(font_path, size)
            except (OSError, IOError):
                continue

        # Last resort: PIL default
        self.logger.warning("No TrueType font found — using PIL default")
        return ImageFont.load_default()

    @staticmethod
    def _save_jpeg(image: Image.Image, path: Path) -> None:
        """Save as JPEG, reducing quality until file is under 2 MB.

        Args:
            image: PIL Image to save.
            path: Output file path.
        """
        for quality in (95, 90, 85, 80, 75, 70):
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            if buffer.tell() <= _MAX_FILE_BYTES or quality == 70:
                path.write_bytes(buffer.getvalue())
                logger.info(
                    "Saved thumbnail: %s (quality=%d, size=%d KB)",
                    path.name,
                    quality,
                    buffer.tell() // 1024,
                )
                return

    # ── AI CTR scoring ────────────────────────────────────────

    async def _score_thumbnail(
        self,
        image_description: str,
        text: str,
        layout_description: str,
    ) -> dict[str, Any]:
        """Use AI to predict the CTR effectiveness of the thumbnail.

        Args:
            image_description: Description of the background image.
            text: The title text used.
            layout_description: How elements are arranged.

        Returns:
            Dict with ``score`` (0-100) and ``feedback`` string.
        """
        prompt = f"""Score this YouTube thumbnail concept for CTR (click-through rate) on a scale of 0–100.

Consider:
- Emotional impact and curiosity factor
- Text readability and contrast
- Composition and visual hierarchy
- Whether it stands out in a YouTube feed
- Avoidance of clickbait clichés

Thumbnail details:
- Background image: {image_description}
- Text: "{text}"
- Layout: {layout_description}

Return ONLY a JSON object with:
- "score": int (0–100)
- "feedback": str (2–3 sentences of constructive feedback)
"""

        try:
            result = await self.ai_json(
                prompt=prompt,
                system="You are a YouTube thumbnail expert. Return valid JSON only.",
            )
            return {
                "score": int(result.get("score", 50)),
                "feedback": str(result.get("feedback", "")),
            }
        except Exception:
            self.logger.exception("AI scoring failed — returning default")
            return {"score": 50, "feedback": "AI scoring unavailable"}

    # ── DB helpers ────────────────────────────────────────────

    @staticmethod
    async def _fetch_topic(topic_id: int) -> dict[str, Any] | None:
        """Load a topic row."""
        return await db.fetchrow(
            "SELECT id, title, category, language, status, inspired_by FROM topics WHERE id = $1",
            topic_id,
        )

    @staticmethod
    async def _fetch_script(topic_id: int) -> dict[str, Any] | None:
        """Load the latest script for a topic."""
        return await db.fetchrow(
            """
            SELECT id, topic_id, intro, sections, outro
            FROM scripts
            WHERE topic_id = $1
            ORDER BY id DESC
            LIMIT 1
            """,
            topic_id,
        )

    @staticmethod
    async def _fetch_thumbnail_style(topic_id: int) -> str:
        """Load the reference channel's thumbnail_style for this topic.

        Args:
            topic_id: The topic ID.

        Returns:
            The thumbnail_style text, or an empty string.
        """
        row = await db.fetchrow(
            """
            SELECT rc.thumbnail_style
            FROM topics t
            JOIN reference_channels rc ON t.inspired_by = rc.id
            WHERE t.id = $1
            """,
            topic_id,
        )
        if row is None:
            return ""
        return row.get("thumbnail_style", "") or ""


# ── Module-level helpers ──────────────────────────────────────


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Word-wrap text to fit within a maximum pixel width.

    Args:
        text: The text to wrap.
        font: Font used for measuring.
        max_width: Maximum line width in pixels.

    Returns:
        A list of wrapped lines.
    """
    words = text.split()
    if not words:
        return [text]

    lines: list[str] = []
    current_line = words[0]

    for word in words[1:]:
        test_line = f"{current_line} {word}"
        bbox = font.getbbox(test_line)
        line_width = bbox[2] - bbox[0] if bbox else len(test_line) * 50

        if line_width <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word

    lines.append(current_line)
    return lines
