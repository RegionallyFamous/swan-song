#!/usr/bin/env python3
"""Build the four-color, tile-aligned mascot used by the WonderSwan ROM."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/source-art/dialbug-sd-mobile-suit-imagegen-v5.png"
OUTPUT = ROOT / "assets/runtime/dialbug-sd-mascot-v5.png"
PREVIEW = ROOT / "assets/runtime/dialbug-sd-mascot-v5-preview.png"

EXPECTED_SOURCE_SHA256 = (
    "228164e1875b03bd006ee8c6f64f48f205874facb3fce5f486e7c9cac6d5cf18"
)

# The crop isolates the complete SD mobile suit and its antenna. The 72x64
# result occupies exactly 9x8 WonderSwan tiles.
CROP = (120, 70, 1135, 1220)
OUTPUT_SIZE = (72, 64)
MASCOT_SIZE = (64, 64)

# Midnight navy, gunmetal inner frame, amber armor, and cyan sensors. Keeping a
# fixed four-color palette makes the runtime derivative exactly reproducible.
COLORS = (
    (0x00, 0x09, 0x1E),
    (0x28, 0x35, 0x43),
    (0xDC, 0x76, 0x0A),
    (0x22, 0xCF, 0xDC),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed_palette() -> Image.Image:
    palette = Image.new("P", (1, 1))
    values = [component for color in COLORS for component in color]
    values.extend([0] * (768 - len(values)))
    palette.putpalette(values)
    return palette


def main() -> int:
    if sha256(SOURCE) != EXPECTED_SOURCE_SHA256:
        raise SystemExit("ImageGen source master changed; review the crop before rebuilding")

    source = Image.open(SOURCE).convert("RGB")
    crop = source.crop(CROP)
    # The SD source is normalized to a square runtime field so the head,
    # shoulders, tuner core, and feet remain bold at hardware scale.
    reduced = crop.resize(MASCOT_SIZE, Image.Resampling.LANCZOS)

    # Preserve the cyan eyes, tuner core, and mixer lamps through the aggressive
    # downsample. The v5 source deliberately makes these accents large enough
    # to survive without expanding the mask into neighboring armor pixels.
    cyan_mask = Image.new("L", crop.size)
    cyan_mask.putdata([
        255 if green > 105 and blue > 120 and red < 110 and blue > red + 35 else 0
        for red, green, blue in crop.get_flattened_data()
    ])
    cyan_mask = cyan_mask.resize(MASCOT_SIZE, Image.Resampling.BOX)
    cyan_mask = cyan_mask.point(lambda value: 255 if value >= 8 else 0)
    reduced.paste(COLORS[3], mask=cyan_mask)

    canvas = Image.new("RGB", OUTPUT_SIZE, COLORS[0])
    canvas.paste(
        reduced,
        ((OUTPUT_SIZE[0] - reduced.width) // 2, (OUTPUT_SIZE[1] - reduced.height) // 2),
    )
    indexed = canvas.quantize(
        palette=fixed_palette(),
        dither=Image.Dither.NONE,
    )
    # Pillow may choose a duplicate black entry beyond the four meaningful
    # slots in the padded palette. Collapse every padded entry back to color 0
    # so each 8x8 source tile is genuinely 2bpp-compatible.
    indexed = indexed.point([0, 1, 2, 3] + [0] * 252)
    indexed.putpalette(fixed_palette().getpalette())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    indexed.save(OUTPUT, optimize=False)
    indexed.resize((288, 256), Image.Resampling.NEAREST).save(PREVIEW, optimize=False)
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT_SIZE[0]}x{OUTPUT_SIZE[1]})")
    print(f"sha256 {sha256(OUTPUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
