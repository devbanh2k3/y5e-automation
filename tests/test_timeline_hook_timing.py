from pathlib import Path


TIMELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "video_engine"
    / "src"
    / "compositions"
    / "TimelineVideo.tsx"
)


def test_timeline_hook_uses_three_sequential_four_second_slots() -> None:
    source = TIMELINE_PATH.read_text()

    assert "const HOOK_CARD_SLOT = 120;" in source
    assert "const HOOK_SLIDE_IN = 60;" in source
    assert "const HOOK_SETTLE = HOOK_CARD_SLOT - HOOK_SLIDE_IN;" in source
    assert "const hookEnd = hookCardCount * HOOK_CARD_SLOT;" in source
    assert "const activeHookCardIndex = Math.min(" in source
    assert "if (isHook && index > activeHookCardIndex) return null;" in source
    assert "index !== activeHookCardIndex" not in source
    assert "index * HOOK_CARD_SLOT" in source
    assert "HOOK_STAGGER" not in source
    assert "HOOK_HOLD" not in source
