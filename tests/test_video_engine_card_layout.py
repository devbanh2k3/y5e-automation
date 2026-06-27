from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_flag_hero_card_does_not_overlay_country_label_on_flag():
    source = (ROOT / "video_engine" / "src" / "components" / "Card.tsx").read_text()
    flag_hero_section = source.split("const FlagHeroCard", 1)[1].split("const SplitDataCard", 1)[0]

    assert "props.countryLabel" not in flag_hero_section
