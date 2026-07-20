#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Regionally Famous contributors
"""Build the four-color mascot and native UI glyph sheet used by the ROM."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/source-art/swanframe-sd-mobile-suit-imagegen-v5.png"
OUTPUT = ROOT / "assets/runtime/swanframe-sd-mascot-v5.png"
PREVIEW = ROOT / "assets/runtime/swanframe-sd-mascot-v5-preview.png"
UI_TILES = ROOT / "assets/runtime/swanframe-ui-tiles.png"
UI_TILES_PREVIEW = ROOT / "assets/runtime/swanframe-ui-tiles-preview.png"

EXPECTED_SOURCE_SHA256 = (
    "228164e1875b03bd006ee8c6f64f48f205874facb3fce5f486e7c9cac6d5cf18"
)

# The crop isolates the complete SD mobile suit and its antenna. The 72x64
# result occupies exactly 9x8 WonderSwan tiles.
CROP = (120, 70, 1135, 1220)
OUTPUT_SIZE = (72, 64)
MASCOT_SIZE = (64, 64)

# Night Drive colorway: midnight violet, smoky indigo, hot orchid armor, and
# phosphor-mint sensors. Keeping a fixed four-color palette makes the runtime
# derivative exactly reproducible while allowing the source master to remain
# the approved amber/cyan identity artwork.
COLORS = (
	(0x08, 0x06, 0x1C),
	(0x29, 0x24, 0x51),
	(0xF0, 0x4A, 0xA6),
	(0x65, 0xF3, 0xC3),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixed_palette() -> Image.Image:
    palette = Image.new("P", (1, 1))
    values = [component for color in COLORS for component in color]
    values.extend([0] * (768 - len(values)))
    palette.putpalette(values)
    return palette


def build_ui_tiles() -> None:
    """Create eight monochrome 8x8 glyphs recolored by runtime palettes."""
    sheet = Image.new("P", (64, 8), 0)
    palette = [component for color in (COLORS[0], (255, 255, 255)) for component in color]
    palette.extend([0] * (768 - len(palette)))
    sheet.putpalette(palette)
    draw = ImageDraw.Draw(sheet)

    def pixel(tile: int, x: int, y: int) -> None:
        draw.point((tile * 8 + x, y), fill=1)

    # 0: chunky dot-matrix cell used by the large track digits and volume bar.
    draw.rectangle((1, 1, 6, 6), fill=1)
    # 1: clean lead-channel segment.
    draw.rectangle((9, 3, 14, 4), fill=1)
    # 2: pulse/bass segment.
    for x, y in ((0, 4), (1, 4), (2, 4), (2, 2), (3, 2), (4, 2),
                 (4, 5), (5, 5), (6, 5), (7, 5)):
        pixel(2, x, y)
    # 3: dotted arpeggio segment.
    for x, y in ((0, 4), (1, 3), (2, 4), (3, 5), (4, 4), (5, 3), (6, 4), (7, 5)):
        pixel(3, x, y)
    # 4: compact drum transient.
    for x, y in ((0, 4), (1, 4), (2, 3), (3, 1), (3, 6), (4, 1),
                 (4, 6), (5, 3), (6, 4), (7, 4)):
        pixel(4, x, y)
    # 5: play.
    for x in range(2, 6):
        for y in range(1 + (x - 2), 7 - (x - 2)):
            pixel(5, x, y)
    # 6: pause.
    draw.rectangle((6 * 8 + 1, 1, 6 * 8 + 2, 6), fill=1)
    draw.rectangle((6 * 8 + 5, 1, 6 * 8 + 6, 6), fill=1)
    # 7: restart/loop arrow.
    for x, y in ((2, 1), (3, 1), (4, 1), (5, 2), (6, 3), (6, 4),
                 (5, 5), (4, 6), (3, 6), (2, 5), (1, 4), (1, 3),
                 (0, 2), (1, 2), (2, 2), (0, 3)):
        pixel(7, x, y)

    UI_TILES.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(UI_TILES, optimize=False)
    sheet.resize((512, 64), Image.Resampling.NEAREST).save(UI_TILES_PREVIEW, optimize=False)
    print(f"wrote {UI_TILES.relative_to(ROOT)} (8 native glyphs)")


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
    build_ui_tiles()
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT_SIZE[0]}x{OUTPUT_SIZE[1]})")
    print(f"sha256 {sha256(OUTPUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
