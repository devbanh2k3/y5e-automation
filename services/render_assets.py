"""Deterministic, render-only image derivatives for Remotion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from PIL import Image, ImageFilter, ImageOps

POLICY_VERSION = 1


@dataclass(frozen=True)
class RenderAsset:
    source_path: Path
    foreground_path: Path
    background_path: Path
    fingerprint: str
    cache_hit: bool


@dataclass(frozen=True)
class RenderAssetManifest:
    items: tuple[RenderAsset, ...]

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for item in self.items:
            digest.update(item.fingerprint.encode("ascii"))
        return digest.hexdigest()


def _fingerprint(
    source: Path,
    *,
    max_size: tuple[int, int],
    quality: int,
    fit: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(source.read_bytes())
    digest.update(
        json.dumps(
            {
                "policy_version": POLICY_VERSION,
                "max_size": max_size,
                "quality": quality,
                "fit": fit,
            },
            sort_keys=True,
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _atomic_save(image: Image.Image, path: Path, *, quality: int) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    image.save(temporary, format="WEBP", quality=quality, method=4)
    temporary.replace(path)


def normalize_card_image(
    *,
    source: str | Path,
    cache_dir: str | Path,
    max_size: tuple[int, int] = (1080, 1350),
    quality: int = 88,
    fit: Literal["contain", "cover"] = "contain",
) -> RenderAsset:
    """Create a bounded foreground and pre-blurred full-size background."""
    source_path = Path(source).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if fit not in {"contain", "cover"}:
        raise ValueError(f"unsupported image fit: {fit}")

    target_dir = Path(cache_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(
        source_path,
        max_size=max_size,
        quality=quality,
        fit=fit,
    )
    foreground_path = target_dir / f"{fingerprint}-fg.webp"
    background_path = target_dir / f"{fingerprint}-bg.webp"
    cache_hit = foreground_path.is_file() and background_path.is_file()
    if cache_hit:
        return RenderAsset(
            source_path=source_path,
            foreground_path=foreground_path,
            background_path=background_path,
            fingerprint=fingerprint,
            cache_hit=True,
        )

    with Image.open(source_path) as original:
        oriented = ImageOps.exif_transpose(original).convert("RGB")
        if fit == "cover":
            foreground = ImageOps.fit(oriented, max_size, method=Image.Resampling.LANCZOS)
        else:
            foreground = oriented.copy()
            foreground.thumbnail(max_size, Image.Resampling.LANCZOS, reducing_gap=3.0)
        background = ImageOps.fit(oriented, max_size, method=Image.Resampling.LANCZOS)
        background = background.filter(ImageFilter.GaussianBlur(radius=24))
        _atomic_save(foreground, foreground_path, quality=quality)
        _atomic_save(background, background_path, quality=quality)

    return RenderAsset(
        source_path=source_path,
        foreground_path=foreground_path,
        background_path=background_path,
        fingerprint=fingerprint,
        cache_hit=False,
    )


def build_render_asset_manifest(
    sources: Iterable[str | Path],
    *,
    cache_dir: str | Path,
    max_size: tuple[int, int] = (1080, 1350),
    quality: int = 88,
    fit: Literal["contain", "cover"] = "contain",
) -> RenderAssetManifest:
    """Normalize every source and return a stable ordered manifest."""
    return RenderAssetManifest(
        items=tuple(
            normalize_card_image(
                source=source,
                cache_dir=cache_dir,
                max_size=max_size,
                quality=quality,
                fit=fit,
            )
            for source in sources
        )
    )
