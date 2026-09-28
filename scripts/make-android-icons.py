#!/usr/bin/env python
"""Generate the circular Android launcher icon set from an image-generated draft.

Run from the repository root:

    python scripts/make-android-icons.py

The draft supplies the brand mark. This script removes generative gradients,
recolors the artwork to the Android client's exact theme colors, constrains the
mark to the Android safe zone, and applies a mathematically circular silhouette.
The density PNGs are referenced by android/manifest.json for HBuilderX builds.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except ImportError:  # pragma: no cover
    print("Pillow is required: pip install pillow", file=sys.stderr)
    raise SystemExit(1)


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "android" / "static" / "icons"
SOURCE = OUT_DIR / "pharmrelate-round-imagegen-source.png"

CANVAS = 1024
SAFE_MARK = 570  # 55.7% of the canvas, inside Android's 66/108 safe zone.
PRIMARY = (14, 110, 122, 255)  # #0E6E7A, android/uni.scss $c-primary
FOREGROUND = (228, 241, 243, 255)  # #E4F1F3, $c-primary-soft
PAGE_BG = (241, 244, 246, 255)  # #F1F4F6, app page background

ANDROID_SIZES = {
    "ldpi": 48,
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}


def normalized_foreground(source: Image.Image) -> Image.Image:
    """Extract the pale mark from the generated draft and flatten its color."""
    source = source.convert("RGBA")
    red, green, blue, source_alpha = source.split()

    # The generated draft contains a light mark over a teal circle.  The minimum
    # RGB channel separates that near-white mark from every teal highlight while
    # retaining anti-aliased edges.  This also removes the draft's gradients.
    whiteness = ImageChops.darker(ImageChops.darker(red, green), blue)
    alpha = whiteness.point(
        lambda value: max(0, min(255, round((value - 170) * 255 / 60)))
    )
    alpha = ImageChops.multiply(alpha, source_alpha)

    # Close tiny generation pinholes without affecting the intentional node holes.
    alpha = alpha.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    alpha = alpha.point(
        lambda value: 0 if value < 10 else (255 if value > 230 else value)
    )
    bbox = alpha.getbbox()
    if bbox is None:
        raise SystemExit(f"Foreground source has no visible pixels: {SOURCE}")

    cropped_alpha = alpha.crop(bbox)
    scale = SAFE_MARK / max(cropped_alpha.size)
    target = tuple(max(1, round(value * scale)) for value in cropped_alpha.size)
    resized_alpha = cropped_alpha.resize(target, Image.Resampling.LANCZOS)

    layer = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    mark = Image.new("RGBA", target, FOREGROUND)
    mark.putalpha(resized_alpha)
    offset = ((CANVAS - target[0]) // 2, (CANVAS - target[1]) // 2)
    layer.alpha_composite(mark, offset)
    return layer


def circular_master(foreground: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Create a true circular background plus the composited launcher icon."""
    background = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(background)
    margin = 32  # 960 px diameter: 93.75% of the 1024 px canvas.
    draw.ellipse((margin, margin, CANVAS - margin - 1, CANVAS - margin - 1), fill=PRIMARY)
    master = background.copy()
    master.alpha_composite(foreground)
    return background, master


def masked_preview(master: Image.Image) -> Image.Image:
    """Preview the icon under common OEM launcher masks."""
    tile = 300
    preview = Image.new("RGBA", (tile * 3, tile), PAGE_BG)
    scaled = master.resize((240, 240), Image.Resampling.LANCZOS)

    for index, shape in enumerate(("circle", "squircle", "rounded")):
        mask = Image.new("L", (240, 240), 0)
        draw = ImageDraw.Draw(mask)
        if shape == "circle":
            draw.ellipse((0, 0, 239, 239), fill=255)
        elif shape == "squircle":
            draw.rounded_rectangle((0, 0, 239, 239), radius=70, fill=255)
        else:
            draw.rounded_rectangle((0, 0, 239, 239), radius=42, fill=255)
        masked = scaled.copy()
        masked.putalpha(ImageChops.multiply(scaled.getchannel("A"), mask))
        preview.alpha_composite(masked, (index * tile + 30, 30))
    return preview


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"Missing image-generated foreground source: {SOURCE}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE)
    foreground = normalized_foreground(source)
    background, master = circular_master(foreground)

    foreground.save(OUT_DIR / "app-icon-round-foreground-1024.png", optimize=True)
    background.save(OUT_DIR / "app-icon-round-background-1024.png", optimize=True)
    master.save(OUT_DIR / "app-icon-round-master-1024.png", optimize=True)

    monochrome = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 255))
    monochrome.putalpha(foreground.getchannel("A"))
    monochrome.save(OUT_DIR / "app-icon-round-monochrome-1024.png", optimize=True)

    for density, size in ANDROID_SIZES.items():
        target = OUT_DIR / f"app-icon-round-{density}-{size}.png"
        master.resize((size, size), Image.Resampling.LANCZOS).save(target, optimize=True)
        print(f"generated {target.relative_to(ROOT)}")

    masked_preview(master).save(OUT_DIR / "app-icon-round-mask-preview.png", optimize=True)
    print(f"generated {(OUT_DIR / 'app-icon-round-master-1024.png').relative_to(ROOT)}")
    print(f"generated {(OUT_DIR / 'app-icon-round-mask-preview.png').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
