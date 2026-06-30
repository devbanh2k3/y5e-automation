from pathlib import Path

import pytest
from PIL import Image

from services.render_assets import build_render_asset_manifest, normalize_card_image


def _make_image(path: Path, *, size: tuple[int, int], color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_portrait_derivatives_preserve_full_subject_and_bake_blur(tmp_path: Path) -> None:
    source = _make_image(tmp_path / "portrait.jpg", size=(600, 1600))

    result = normalize_card_image(
        source=source,
        cache_dir=tmp_path / "cache",
        max_size=(1080, 1350),
        quality=88,
        fit="contain",
    )

    with Image.open(result.foreground_path) as foreground:
        assert foreground.width <= 1080
        assert foreground.height <= 1350
        assert foreground.width / foreground.height == pytest.approx(600 / 1600, rel=0.02)
    with Image.open(result.background_path) as background:
        assert background.size == (1080, 1350)


def test_asset_manifest_reuses_unchanged_derivative(tmp_path: Path) -> None:
    source = _make_image(tmp_path / "person.jpg", size=(1200, 1600))

    first = build_render_asset_manifest([source], cache_dir=tmp_path / "cache")
    second = build_render_asset_manifest([source], cache_dir=tmp_path / "cache")

    assert second.items[0].fingerprint == first.items[0].fingerprint
    assert first.items[0].cache_hit is False
    assert second.items[0].cache_hit is True


def test_asset_fingerprint_changes_when_source_changes(tmp_path: Path) -> None:
    source = _make_image(tmp_path / "person.jpg", size=(1200, 1600), color="red")
    first = build_render_asset_manifest([source], cache_dir=tmp_path / "cache")
    _make_image(source, size=(1200, 1600), color="blue")

    changed = build_render_asset_manifest([source], cache_dir=tmp_path / "cache")

    assert changed.items[0].fingerprint != first.items[0].fingerprint
    assert changed.items[0].cache_hit is False
