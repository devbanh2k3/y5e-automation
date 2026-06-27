from pathlib import Path


TIMELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "video_engine"
    / "src"
    / "compositions"
    / "TimelineVideo.tsx"
)


def test_timeline_hook_starts_scroll_after_final_hook_card_slides_in() -> None:
    source = TIMELINE_PATH.read_text()

    assert "const HOOK_CARD_SLOT = 120;" in source
    assert "const HOOK_SLIDE_IN = 60;" in source
    assert "const hookEnd = Math.max(0, hookCardCount - 1) * HOOK_CARD_SLOT + HOOK_SLIDE_IN;" in source
    assert "const hookEnd = hookCardCount * HOOK_CARD_SLOT;" not in source
    assert "const HOOK_SETTLE" not in source
    assert "const activeHookCardIndex = Math.min(" in source
    assert "if (isHook && index > activeHookCardIndex) return null;" in source
    assert "index !== activeHookCardIndex" not in source
    assert "index * HOOK_CARD_SLOT" in source
    assert "HOOK_STAGGER" not in source
    assert "HOOK_HOLD" not in source
