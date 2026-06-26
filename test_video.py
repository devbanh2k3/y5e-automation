"""
YouTube AI Automation — Video Quality Test Script
Chạy pipeline rút gọn: Topic → Script → Images → Render → Xem video

Usage:
    python3 test_video.py
    python3 test_video.py --topic "What If Humans Lost 1 IQ Every Day"
    python3 test_video.py --category Ranking --lang vi
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import subprocess
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# ── Load .env ───────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_video")

# ── Config ──────────────────────────────────────────────────
API_BASE = os.getenv("PRIMARY_API_BASE", "")
API_KEY = os.getenv("PRIMARY_API_KEY", "")
MODEL = os.getenv("PRIMARY_MODEL", "gemini-2.5-flash")
PROJECT_ROOT = Path(__file__).parent
VIDEO_ENGINE = PROJECT_ROOT / "video_engine"
OUTPUT_DIR = PROJECT_ROOT / "output" / "test_video"

CATEGORY_MAP = {
    "WhatIf": "timeline",
    "Timeline": "timeline",
    "History": "timeline",
    "Ranking": "timeline",
    "Comparison": "timeline",
    "Science": "timeline",
    "Geography": "timeline",
    "Evolution": "timeline",
    "Celebrity": "timeline",
}

# ── AI Helper ───────────────────────────────────────────────

async def ai_json(prompt: str, system: str = "", max_retries: int = 6) -> dict:
    """Call AI and parse JSON response with retry."""
    import re

    for attempt in range(max_retries):
        client = httpx.AsyncClient(timeout=120.0)
        try:
            # On retry after JSON parse failure, add stronger instruction
            effective_prompt = prompt
            if attempt > 0:
                effective_prompt = (
                    "IMPORTANT: You MUST respond with ONLY a valid JSON object. "
                    "No explanations, no markdown, no text before or after. "
                    "Start your response with { and end with }.\n\n"
                    + prompt
                )

            messages = []
            if system:
                messages.append({"role": "system", "content": system + "\nYou MUST respond with valid JSON only. No other text."})
            else:
                messages.append({"role": "system", "content": "You MUST respond with valid JSON only. No explanations, no markdown."})
            messages.append({"role": "user", "content": effective_prompt})

            body = {
                "model": MODEL,
                "messages": messages,
                "temperature": 0.7,
                "stream": False,
            }

            # Try to force JSON mode (supported by most OpenAI-compatible APIs)
            try:
                body["response_format"] = {"type": "json_object"}
            except Exception:
                pass

            resp = await client.post(
                f"{API_BASE.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json=body,
            )

            if resp.status_code in (429, 503) and attempt < max_retries - 1:
                wait = 5 * (attempt + 1)
                log.warning(f"   ⏳ API returned {resp.status_code}, retrying in {wait}s... ({attempt+1}/{max_retries})")
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]

            # Extract JSON from response
            # Try direct parse first (if model returned clean JSON)
            text_stripped = text.strip()
            if text_stripped.startswith("{"):
                try:
                    return json.loads(text_stripped)
                except json.JSONDecodeError:
                    pass

            # Try code block
            m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
            if m:
                return json.loads(m.group(1).strip())

            # Try finding JSON object in text
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass

            # JSON parse failed — retry with stronger instruction
            if attempt < max_retries - 1:
                log.warning(f"   ⚠️  JSON parse failed, retrying ({attempt+1}/{max_retries})...")
                continue

            raise ValueError(f"No JSON found in: {text[:200]}")
        except (httpx.HTTPStatusError, ValueError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                log.warning(f"   ⏳ Request failed ({e.__class__.__name__}), retrying in {wait}s... ({attempt+1}/{max_retries})")
                await asyncio.sleep(wait)
                continue
            raise
        finally:
            await client.aclose()


# ── Step 1: Generate Topic ──────────────────────────────────

async def generate_topic(category: str, language: str, manual_subtopic: str = None) -> dict:
    log.info("🧠 Step 1: Generating topic...")

    lang_name = {"vi": "tiếng Việt", "ja": "tiếng Nhật", "en": "English"}[language]

    # ── Topic History: never repeat ──
    history_file = OUTPUT_DIR.parent / "topics_history.json"
    used_topics = _load_topic_history(history_file)
    used_in_category = [t["subtopic"] for t in used_topics if t.get("category") == category]

    if manual_subtopic:
        chosen_subtopic = manual_subtopic
        log.info(f"   🎯 Manual subtopic: {chosen_subtopic}")
    else:
        # AI generates a fresh, creative subtopic
        chosen_subtopic = await _ai_generate_subtopic(category, lang_name, used_in_category)
        log.info(f"   🎯 AI-generated subtopic: {chosen_subtopic}")

    result = await ai_json(f"""
Generate 1 YouTube video topic for category "{category}" in {lang_name}.

SPECIFIC SUBTOPIC: The video MUST be about "{chosen_subtopic}".
DO NOT make a video about con người/human body/human evolution unless the subtopic specifically says so.

The topic MUST be:
- Extremely click-worthy (gây tò mò mạnh)
- Suitable for an educational/infotainment channel
- About "{chosen_subtopic}" specifically
- Something that could go viral (lên xu hướng)

Return JSON:
{{
    "title": "catchy title about {chosen_subtopic}, max 60 chars, in {lang_name}",
    "subtitle": "banner text for the video, max 40 chars",
    "category": "{category}",
    "hook": "1 sentence that makes viewers NEED to watch",
    "subtopic": "{chosen_subtopic}"
}}
""")

    # Save to history
    _save_topic_history(history_file, {
        "category": category,
        "subtopic": chosen_subtopic,
        "title": result.get("title", ""),
        "language": language,
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    })

    log.info(f"   📌 Topic: {result.get('title', 'N/A')}")
    log.info(f"   🎣 Hook: {result.get('hook', 'N/A')}")
    log.info(f"   📊 Used {len(used_in_category)} previous {category} topics")
    return result


async def _ai_generate_subtopic(category: str, lang_name: str, used_subtopics: list[str]) -> str:
    """Let AI generate a fresh, creative subtopic that hasn't been used before."""
    used_list = "\n".join(f"- {t}" for t in used_subtopics[-30:]) if used_subtopics else "None yet"

    category_hints = {
        "Evolution": "the evolution/history of a specific technology, product, vehicle, tool, concept, or industry. Think: phones, cars, computers, weapons, medicine, architecture, fashion, money, sports, music, food, energy, maps, lighting, etc.",
        "Ranking": "a top 20 ranking of something fascinating: most dangerous, most expensive, most powerful, strangest, biggest, deadliest, etc. in any domain: animals, countries, disasters, inventions, crimes, buildings, sports records, etc.",
        "WhatIf": "a mind-bending hypothetical scenario about nature, physics, biology, society, or technology. Think: what if gravity reversed, what if the sun disappeared, what if humans could fly, etc.",
        "Science": "a fascinating scientific topic that blows people's minds. Think: quantum physics, black holes, DNA, the brain, parasites, the ocean floor, antimatter, time, infinity, etc.",
        "History": "a dramatic historical event, era, empire, war, or figure that most people don't know the full story of.",
        "Comparison": "a fascinating comparison between two things people think they understand but actually don't.",
        "Geography": "a ranking or exploration of countries, cities, natural wonders, or geographic extremes.",
        "Celebrity": "a THEMED RANKING of celebrities/famous people with specific data. PROVEN VIRAL TOPICS: Top 100 richest actors/singers in 2026, oldest celebrities still alive, celebrities who died from overdoses, Hollywood actors with most Oscar wins, longest celebrity marriages, youngest billionaires, celebrities over 50 without children, famous last words of legends, musicians who died too young, most followed on social media, celebrity transformations, K-pop idols net worth, tallest/shortest celebrities, celebrities who went from poor to rich. ALWAYS use a specific NUMBER in the topic (Top 40, 50 oldest, etc.) and add YEAR (2026) when relevant.",
    }

    hint = category_hints.get(category, "an interesting educational topic")

    result = await ai_json(f"""
You are a YouTube content strategist. Generate 1 SPECIFIC, FRESH subtopic for a "{category}" video.

The subtopic should be about: {hint}

ALREADY USED SUBTOPICS (DO NOT repeat these):
{used_list}

Rules:
1. Must be SPECIFIC (not "technology" but "điện thoại di động" or "dao kéo")
2. Must be something with RICH visual content (good for video)
3. Must have enough historical depth for 20 cards
4. Must be DIFFERENT from all used subtopics above
5. Think about what's TRENDING or what viewers are curious about right now

Return JSON:
{{
    "subtopic": "specific subtopic in Vietnamese, 2-5 words",
    "reason": "why this topic will get views"
}}
""")
    return result.get("subtopic", "công nghệ thú vị")


def _load_topic_history(path: Path) -> list[dict]:
    """Load topic history from JSON file."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, Exception):
            return []
    return []


def _save_topic_history(path: Path, entry: dict):
    """Append a new topic to history."""
    history = _load_topic_history(path)
    history.append(entry)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2))


# ── Step 2: Generate Script ─────────────────────────────────

async def generate_script(topic: dict, category: str, language: str) -> dict:
    log.info("✍️  Step 2: Generating script...")

    lang_name = {"vi": "tiếng Việt", "ja": "tiếng Nhật", "en": "English"}[language]
    # Header format depends on category + language
    section_count = 40

    # Language-specific header formats
    header_formats_by_lang = {
        "vi": {
            "WhatIf": "timeline markers (e.g. NGÀY 1, NGÀY 10, NGÀY 30...)",
            "Timeline": "timeline markers (e.g. NGÀY 1, TUẦN 1, THÁNG 1...)",
            "History": "year markers (e.g. NĂM 1945, NĂM 1969...)",
            "Ranking": "ranking markers counting down (e.g. TOP 20, TOP 19... TOP 1)",
            "Comparison": "comparison labels (e.g. VS 1, VS 2...)",
            "Science": "discovery markers (e.g. PHÁT HIỆN 1, PHÁT HIỆN 2...)",
            "Geography": "location markers (e.g. VỊ TRÍ 10, VỊ TRÍ 9... VỊ TRÍ 1)",
            "Evolution": "year/era markers (e.g. THẾ KỶ 18, NĂM 1990, NĂM 2024, NĂM 2030, TƯƠNG LAI XA)",
            "Celebrity": "celebrity name as header (e.g. the celebrity's full name in UPPERCASE)",
        },
        "ja": {
            "WhatIf": "タイムライン (例: 1日目, 10日目, 30日目...)",
            "Timeline": "タイムライン (例: 1日目, 1週間, 1ヶ月...)",
            "History": "年マーカー (例: 1945年, 1969年...)",
            "Ranking": "ランキング (例: TOP 20, TOP 19... TOP 1)",
            "Comparison": "比較 (例: VS 1, VS 2...)",
            "Science": "発見 (例: 発見 1, 発見 2...)",
            "Geography": "場所 (例: 場所 10, 場所 9... 場所 1)",
            "Evolution": "年代マーカー (例: 18世紀, 1990年, 2024年, 2030年, 遠い未来)",
            "Celebrity": "有名人の名前 (例: セレブの名前を大文字で)",
        },
        "en": {
            "WhatIf": "timeline markers (e.g. DAY 1, DAY 10, DAY 30...)",
            "Timeline": "timeline markers (e.g. DAY 1, WEEK 1, MONTH 1...)",
            "History": "year markers (e.g. YEAR 1945, YEAR 1969...)",
            "Ranking": "ranking markers counting down (e.g. TOP 20, TOP 19... TOP 1)",
            "Comparison": "comparison labels (e.g. VS 1, VS 2...)",
            "Science": "discovery markers (e.g. DISCOVERY 1, DISCOVERY 2...)",
            "Geography": "location markers (e.g. LOCATION 10, LOCATION 9... LOCATION 1)",
            "Evolution": "year/era markers (e.g. 18TH CENTURY, YEAR 1990, YEAR 2024, YEAR 2030, FAR FUTURE)",
            "Celebrity": "celebrity name as header (e.g. celebrity's full name in UPPERCASE)",
        },
    }

    lang_headers = header_formats_by_lang.get(language, header_formats_by_lang["vi"])
    header_format = lang_headers.get(category, lang_headers.get("WhatIf", "markers"))

    # Category-specific ordering rules (language-aware)
    order_rule = ""
    future_labels = {
        "vi": ["NĂM 2025", "NĂM 2030", "NĂM 2040", "NĂM 2050", "TƯƠNG LAI XA"],
        "ja": ["2025年", "2030年", "2040年", "2050年", "遠い未来"],
        "en": ["YEAR 2025", "YEAR 2030", "YEAR 2040", "YEAR 2050", "FAR FUTURE"],
    }
    fl = future_labels.get(language, future_labels["vi"])

    if category == "Evolution":
        order_rule = f"""
CRITICAL: Sections MUST be in STRICT CHRONOLOGICAL ORDER from oldest to newest.
Each header must use a UNIQUE time period. DO NOT repeat years. DO NOT go backwards.
ALL headers and content MUST be written in {lang_name}. DO NOT mix languages.

IMPORTANT: The LAST 8 CARDS (33-40) must be FUTURE PREDICTIONS:
- Card 33: {fl[0]} (near future, what's happening now)
- Card 34: {fl[1]} (5 years out)
- Card 35: {fl[2]} (10 years out)
- Card 36: {fl[3]} (20 years out)
- Card 37: {fl[4]} (50 years out — bold speculation)
- Card 38-40: Even further future — wild but grounded sci-fi predictions

The future cards should have exciting, speculative but scientifically plausible content."""
    elif category == "Ranking":
        order_rule = "\nSections MUST count down: TOP 20 → TOP 19 → ... → TOP 1. The #1 is the climax."
    elif category == "History":
        order_rule = "\nSections MUST be in chronological order from earliest to latest."
    elif category == "Celebrity":
        order_rule = f"""
This is a CELEBRITY DATA video. Each card = 1 famous person.

CRITICAL CARD FORMAT:
- header: Celebrity's FULL NAME in UPPERCASE (e.g. "ELON MUSK", "TAYLOR SWIFT")
- title: Their most famous role/title (e.g. "CEO Tesla & SpaceX", "Pop Queen")
- description: 3-4 key facts about them — birth year, nationality, career highlights, interesting facts. Include numbers (net worth, records, achievements).
- status_text: Their KEY STAT (e.g. "TÀI SẢN: $230 TỶ", "TUỔI: 35", "ALBUM: 14", "NET WORTH: $1.3B")
- image_query: "[Celebrity Name] portrait photo" — MUST be their real name for accurate photos

All text MUST be in {lang_name}.
Order celebrities from least to most famous/impactful (build up to the biggest name as climax).
Include a MIX of: actors, musicians, athletes, business leaders, historical figures, scientists.
Each person must be DIFFERENT — no repeats."""

    result = await ai_json(f"""
Write a YouTube video script in {lang_name} for: "{topic['title']}"
Category: {category}
Template: slide (horizontal card scroll)

IMPORTANT RULES FOR TRENDING:
1. Hook phải cực mạnh — câu đầu tiên khiến người xem KHÔNG THỂ lướt đi
2. Mỗi section phải có 1 fact gây sốc hoặc twist bất ngờ
3. Xây dựng tension tăng dần — section cuối phải là climax
4. Dùng số liệu cụ thể (con số gây ấn tượng)
5. Ngôn ngữ đơn giản, dễ hiểu, hấp dẫn
6. KHÔNG chào hỏi, KHÔNG "chào các bạn", vào thẳng vấn đề
7. CRITICAL: ALL text (titles, descriptions, headers, status_text, intro_cards) MUST be written ENTIRELY in {lang_name}. DO NOT mix languages. NO Vietnamese in Japanese/English videos. NO English in Vietnamese/Japanese videos.
{order_rule}

Return JSON:
{{
    "intro_cards": [
        {{
            "text": "Dòng hook cực mạnh — câu hỏi hoặc statement gây sốc, max 20 từ",
            "subtext": "Dòng phụ bổ sung context hoặc số liệu gây ấn tượng, max 15 từ",
            "image_query": "English search query (2-4 words) for a dramatic background image matching the hook"
        }},
        {{
            "text": "Fact gây sốc thứ 2 để giữ chân, max 20 từ",
            "subtext": "Số liệu hoặc so sánh bất ngờ, max 15 từ",
            "image_query": "English search query for background image"
        }},
        {{
            "text": "Teaser cho nội dung chính — tạo tò mò, max 20 từ",
            "subtext": "Hint về điều bất ngờ sắp tiết lộ, max 15 từ",
            "image_query": "English search query for background image"
        }}
    ],
    "sections": [
        {{
            "header": "{header_format}",
            "title": "bold catchy title, max 20 chars",
            "description": "3-4 câu súc tích. Phải có số liệu hoặc fact bất ngờ. Mỗi câu max 15 từ. Đủ nội dung cho 8 giây đọc.",
            "status_text": "metric display, e.g. 'DÂN SỐ: 1.4 TỶ'",
            "image_query": "PRIMARY English search query (2-4 words). Must be CONCRETE — name real objects/places/animals. NEVER abstract.",
            "image_query_alt1": "BACKUP query 1 — different angle, same subject.",
            "image_query_alt2": "BACKUP query 2 — broader or more generic version."
        }}
    ],
    "outro": "CTA ngắn gọn — subscribe + tease video tiếp theo. Max 2 câu."
}}

Generate exactly 3 intro_cards and exactly {section_count} sections.
""",
        system="You are a viral YouTube scriptwriter. Your scripts get millions of views because they're impossible to stop watching. Keep text SHORT and PUNCHY — every word must earn its place.",
    )

    sections = result.get("sections", [])
    log.info(f"   📝 Generated {len(sections)} sections")
    log.info(f"   🎬 Intro: {result.get('intro', '')[:80]}...")
    return result


# ── Step 3: Download Images ─────────────────────────────────
# Uses professional waterfall: Unsplash → Wikimedia → Wikipedia → Pexels → Pixabay

from core.image_search import download_all_images, search_and_download

async def download_images(sections: list[dict], output_dir: Path, intro_cards: list[dict] = None) -> list[str]:
    log.info("🖼️  Step 3: Downloading real images...")

    # Download intro card images first
    if intro_cards:
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        for i, ic in enumerate(intro_cards):
            query = ic.get("image_query", "")
            if query:
                file_path = images_dir / f"intro_{i}.jpg"
                log.info(f"  [hook {i+1}/{len(intro_cards)}] Searching: {query[:50]}...")
                result = await search_and_download(query, file_path)
                if result.get("success"):
                    log.info(f"  ✅ [hook {i+1}] {result['source']:8s} | {result.get('size_kb', 0):5.1f}KB | {query[:40]}")
                else:
                    log.warning(f"  ⚠️  [hook {i+1}] Placeholder: {query[:40]}")

    # Download main section images
    results = await download_all_images(sections, output_dir, delay=0.5)
    return [r["path"] for r in results]



# ── Step 4: Build Remotion Props & Render ───────────────────

async def render_video(
    topic: dict,
    script: dict,
    image_paths: list[str],
    category: str,
    language: str,
    output_dir: Path,
) -> Path:
    log.info("🎬 Step 4: Rendering video with Remotion...")

    template_name = "TimelineVideo"

    # Prepare public directory
    public_dir = VIDEO_ENGINE / "public"
    public_images = public_dir / "images"
    public_audio = public_dir / "audio"
    public_images.mkdir(parents=True, exist_ok=True)
    public_audio.mkdir(parents=True, exist_ok=True)

    # Copy section images to public/images/
    for i, img_path in enumerate(image_paths):
        src = Path(img_path)
        dst = public_images / f"section_{i}.jpg"
        if src.exists():
            shutil.copy2(src, dst)

    # Copy intro hook images to public/images/
    images_dir = output_dir / "images"
    for i in range(3):
        src = images_dir / f"intro_{i}.jpg"
        dst = public_images / f"intro_{i}.jpg"
        if src.exists():
            shutil.copy2(src, dst)

    # Create a simple logo if not exists
    logo_path = public_images / "logo.png"
    if not logo_path.exists():
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([20, 20, 180, 180], fill=(229, 45, 39, 200))
            draw.text((100, 100), "AI", fill=(255, 255, 255), anchor="mm")
            img.save(logo_path, "PNG")
        except ImportError:
            pass

    # Build video data JSON
    sections = script.get("sections", [])
    cards = []
    for i, section in enumerate(sections):
        cards.append({
            "header": section.get("header", f"#{i+1}"),
            "title": section.get("title", ""),
            "description": section.get("description", ""),
            "imagePath": f"images/section_{i}.jpg",
            "statusText": section.get("status_text", ""),
        })

    # Build intro cards from script
    intro_cards = script.get("intro_cards", [])
    intro_cards_data = [
        {
            "text": ic.get("text", ""),
            "subtext": ic.get("subtext", ""),
            "imagePath": f"images/intro_{i}.jpg",
        }
        for i, ic in enumerate(intro_cards)
    ]

    video_data = {
        "template": "timeline",
        "title": topic.get("title", "Test Video"),
        "subtitle": topic.get("subtitle", topic.get("title", "")[:40]),
        "language": language,
        "cards": cards,
        "introCards": intro_cards_data,
        "musicPath": "",  # No music for test (faster render)
        "sfxPaths": {"transition": "", "alert": "", "reveal": ""},
        "logoPath": "images/logo.png",
        "holdDurationFrames": 240,  # 8 seconds per card
        "transitionDurationFrames": 15,  # 0.5 second transition
    }

    # Write props file
    props_file = public_dir / "test_props.json"
    props_file.write_text(json.dumps(video_data, ensure_ascii=False, indent=2))

    # Calculate duration
    # Hook: stagger * (n-1) + slide_in + hold + morph = 2*12 + 20 + 90 + 30 = 164 frames (~5.5s)
    hook_cards = min(3, len(cards))
    hook_frames = (hook_cards - 1) * 45 + 60 + 180 + 30  # stagger(45) + slide(60) + hold(180) + morph(30) = 12s
    outro = 150  # 5 seconds
    hold_per_card = 240  # 8 seconds
    main = len(cards) * hold_per_card + max(0, len(cards) - 1) * 15
    total_frames = hook_frames + main + outro
    duration_sec = total_frames / 30

    log.info(f"   📊 {hook_cards} hook + {len(cards)} cards × 8s = ~{duration_sec:.0f}s ({duration_sec/60:.1f}min) video ({total_frames} frames)")
    log.info(f"   🎨 Template: {template_name}")

    # Render with Remotion
    output_path = output_dir / "test_output.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "npx", "remotion", "render",
        "src/index.tsx", template_name,
        str(output_path),
        f"--props={props_file}",
        "--codec=h264",
        "--crf=20",
    ]

    log.info(f"   ⏳ Rendering... (this may take 1-3 minutes)")

    process = subprocess.run(
        cmd,
        cwd=str(VIDEO_ENGINE),
        capture_output=True,
        text=True,
        timeout=600,
    )

    if process.returncode != 0:
        log.error(f"   ❌ Render failed:\n{process.stderr[-500:]}")
        # Save error for debugging
        (output_dir / "render_error.log").write_text(process.stderr)
        raise RuntimeError("Remotion render failed")

    log.info(f"   ✅ Video rendered: {output_path}")
    log.info(f"   📁 Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")

    return output_path


# ── Step 5: Score & Review ──────────────────────────────────

async def score_content(topic: dict, script: dict) -> dict:
    log.info("📊 Step 5: AI scoring content for viral potential...")

    sections_text = "\n".join([
        f"  [{s.get('header','')}] {s.get('title','')} — {s.get('description','')}"
        for s in script.get("sections", [])
    ])

    result = await ai_json(f"""
Score this YouTube video content for VIRAL POTENTIAL (trending/xu hướng) on a scale of 0-100.

TITLE: {topic.get('title', '')}
HOOK: {topic.get('hook', '')}
INTRO: {script.get('intro', '')}
SECTIONS:
{sections_text}
OUTRO: {script.get('outro', '')}

Score these dimensions:
1. hook_strength (25%): Does the first sentence make you NEED to watch?
2. curiosity_gap (25%): Does each section create tension that pulls you to the next?
3. shareability (25%): Would viewers share this with friends?
4. retention (25%): Would viewers watch until the end?

Return JSON:
{{
    "hook_strength": 0-100,
    "curiosity_gap": 0-100,
    "shareability": 0-100,
    "retention": 0-100,
    "total": 0-100,
    "verdict": "VIRAL / GOOD / NEEDS WORK / WEAK",
    "strengths": ["list of what works well"],
    "improvements": ["specific actionable improvements to make it trend"]
}}
""",
        system="You are a YouTube algorithm expert. You know exactly what makes videos trend. Be BRUTALLY honest.",
    )

    total = result.get("total", 0)
    verdict = result.get("verdict", "?")
    log.info(f"   🏆 Score: {total}/100 — {verdict}")
    log.info(f"   💪 Strengths: {', '.join(result.get('strengths', []))}")
    for imp in result.get("improvements", []):
        log.info(f"   📝 Improve: {imp}")

    return result


# ── Main ────────────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test video quality")
    parser.add_argument("--topic", type=str, default=None, help="Specific topic title")
    parser.add_argument("--category", type=str, default="WhatIf", help="Category: WhatIf, Ranking, History, etc.")
    parser.add_argument("--lang", type=str, default="vi", help="Language: vi, ja, en")
    parser.add_argument("--skip-render", action="store_true", help="Skip Remotion render (just script + score)")
    parser.add_argument("--subtopic", type=str, default=None, help="Specific subtopic (e.g. 'điện thoại di động')")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("🚀 YouTube AI — Video Quality Test")
    log.info("=" * 60)

    # Validate API key
    if not API_KEY or API_KEY == "CHANGE_ME":
        log.error("❌ API key not set! Edit .env file first.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Topic
    if args.topic:
        topic = {"title": args.topic, "subtitle": args.topic[:40], "hook": "", "category": args.category}
    else:
        topic = await generate_topic(args.category, args.lang, manual_subtopic=args.subtopic)

    # Step 2: Script
    script = await generate_script(topic, args.category, args.lang)

    # Save script for review
    script_file = OUTPUT_DIR / "script.json"
    script_file.write_text(json.dumps(
        {"topic": topic, "script": script},
        ensure_ascii=False, indent=2,
    ))
    log.info(f"   💾 Script saved: {script_file}")

    # Step 3: Score content BEFORE rendering (non-blocking)
    try:
        score = await score_content(topic, script)
    except Exception as e:
        log.warning(f"   ⚠️  Scoring failed ({e}), skipping...")
        score = {"total": 0, "verdict": "SKIP", "strengths": [], "improvements": []}
    score_file = OUTPUT_DIR / "score.json"
    score_file.write_text(json.dumps(score, ensure_ascii=False, indent=2))

    total = score.get("total", 0)
    MIN_SCORE = 70
    MAX_ATTEMPTS = 3
    attempt = 1

    while total < MIN_SCORE and attempt < MAX_ATTEMPTS:
        attempt += 1
        log.warning(f"   ⚠️  Score {total}/100 — Quá thấp! Tạo lại topic + script... (lần {attempt}/{MAX_ATTEMPTS})")
        topic = await generate_topic(args.category, args.lang)
        script = await generate_script(topic, args.category, args.lang)
        script_file.write_text(json.dumps(
            {"topic": topic, "script": script},
            ensure_ascii=False, indent=2,
        ))
        try:
            score = await score_content(topic, script)
        except Exception as e:
            log.warning(f"   ⚠️  Scoring failed ({e}), skipping...")
            score = {"total": 0, "verdict": "SKIP", "strengths": [], "improvements": []}
        score_file.write_text(json.dumps(score, ensure_ascii=False, indent=2))
        total = score.get("total", 0)

    if total < MIN_SCORE:
        log.error(f"   ❌ Score {total}/100 sau {MAX_ATTEMPTS} lần thử. Dừng lại — không render video chất lượng thấp.")
        return

    log.info(f"   ✅ Score {total}/100 — Đạt chuẩn! Tiếp tục render...")

    # Step 4: Download images
    if not args.skip_render:
        intro_cards_raw = script.get("intro_cards", [])
        image_paths = await download_images(script.get("sections", []), OUTPUT_DIR, intro_cards=intro_cards_raw)

        # Step 5: Render video
        video_path = await render_video(
            topic, script, image_paths, args.category, args.lang, OUTPUT_DIR,
        )

        log.info("")
        log.info("=" * 60)
        log.info("✅ TEST COMPLETE!")
        log.info(f"   🎬 Video: {video_path}")
        log.info(f"   📝 Script: {script_file}")
        log.info(f"   📊 Score: {score_file}")
        log.info(f"   🏆 Viral Score: {total}/100 — {score.get('verdict', '?')}")
        log.info("")
        log.info("   👉 Open video: open " + str(video_path))
        log.info("=" * 60)

        # Auto-open on macOS
        subprocess.run(["open", str(video_path)], check=False)
    else:
        log.info("")
        log.info("=" * 60)
        log.info("✅ SCRIPT TEST COMPLETE (render skipped)")
        log.info(f"   📝 Script: {script_file}")
        log.info(f"   📊 Score: {score_file}")
        log.info(f"   🏆 Viral Score: {total}/100 — {score.get('verdict', '?')}")
        log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
