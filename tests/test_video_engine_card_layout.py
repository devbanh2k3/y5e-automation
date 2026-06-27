from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_flag_hero_card_does_not_overlay_country_label_on_flag():
    source = (ROOT / "video_engine" / "src" / "components" / "Card.tsx").read_text()
    flag_hero_section = source.split("const FlagHeroCard", 1)[1].split("const SplitDataCard", 1)[0]

    assert "props.countryLabel" not in flag_hero_section


def test_flag_block_uses_full_detail_flag_icons_assets():
    source = (ROOT / "video_engine" / "src" / "components" / "Card.tsx").read_text()

    assert "country-flag-icons/react/3x2" not in source
    assert "flag-icons/css/flag-icons.min.css" in source
    assert "fi fi-" in source


def test_timeline_scroll_centers_final_card_before_outro():
    source = (ROOT / "video_engine" / "src" / "compositions" / "TimelineVideo.tsx").read_text()

    assert "finalCardCenteredScrollDistance" in source
    assert "(width - CARD_WIDTH) / 2" in source


def test_timeline_hook_starts_scroll_after_third_card_slide_in():
    source = (ROOT / "video_engine" / "src" / "compositions" / "TimelineVideo.tsx").read_text()

    assert "hookEnd = Math.max(0, hookCardCount - 1) * HOOK_CARD_SLOT + HOOK_SLIDE_IN" in source
    assert "hookCardCount * HOOK_CARD_SLOT" not in source
