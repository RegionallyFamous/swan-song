#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Convert the approved Yokoi wordmark to WonderSwan 2bpp tile data."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


WIDTH = 64
HEIGHT = 64
TILE_SIZE = 8
PALETTE = (
    (255, 255, 255),
    (221, 221, 221),
    (34, 102, 204),
    (34, 51, 68),
)


def nearest_palette_index(rgb: tuple[int, int, int]) -> int:
    return min(
        range(len(PALETTE)),
        key=lambda index: sum((rgb[channel] - PALETTE[index][channel]) ** 2 for channel in range(3)),
    )


def render_logo(source: Image.Image) -> Image.Image:
    source = source.convert("RGBA")
    bounds = source.getbbox()
    if bounds is None:
        raise ValueError("logo image is empty")
    source = source.crop(bounds)

    alpha = source.getchannel("A")
    occupied_columns = [
        x for x in range(source.width)
        if alpha.crop((x, 0, x + 1, source.height)).getbbox() is not None
    ]
    gaps = [
        (left, right)
        for left, right in zip(occupied_columns, occupied_columns[1:])
        if right - left > 1
    ]
    if not gaps:
        raise ValueError("logo does not contain a transparent icon/wordmark split")
    gap_left, gap_right = max(gaps, key=lambda gap: gap[1] - gap[0])
    split = (gap_left + gap_right) // 2

    icon = source.crop((0, 0, split, source.height))
    wordmark = source.crop((split, 0, source.width, source.height))
    icon_bounds = icon.getbbox()
    wordmark_bounds = wordmark.getbbox()
    if icon_bounds is None or wordmark_bounds is None:
        raise ValueError("logo icon or wordmark is empty")
    icon = icon.crop(icon_bounds)
    wordmark = wordmark.crop(wordmark_bounds)
    icon.thumbnail((56, 32), Image.Resampling.LANCZOS)
    wordmark.thumbnail((60, 16), Image.Resampling.LANCZOS)

    rgba = Image.new("RGBA", (WIDTH, HEIGHT), (255, 255, 255, 255))
    content_height = icon.height + 2 + wordmark.height
    top = (HEIGHT - content_height) // 2
    rgba.alpha_composite(icon, ((WIDTH - icon.width) // 2, top))
    rgba.alpha_composite(wordmark, ((WIDTH - wordmark.width) // 2, top + icon.height + 2))

    indexed = Image.new("P", rgba.size)
    flat_palette = [component for color in PALETTE for component in color]
    indexed.putpalette(flat_palette + [0] * (768 - len(flat_palette)))
    pixels = rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata()
    indexed.putdata([nearest_palette_index(pixel[:3]) for pixel in pixels])
    return indexed


def encode_tiles(image: Image.Image) -> bytes:
    if image.size != (WIDTH, HEIGHT):
        raise ValueError(f"expected {WIDTH}x{HEIGHT} image")
    output = bytearray()
    for tile_y in range(0, HEIGHT, TILE_SIZE):
        for tile_x in range(0, WIDTH, TILE_SIZE):
            for row in range(TILE_SIZE):
                plane_0 = 0
                plane_1 = 0
                for column in range(TILE_SIZE):
                    value = image.getpixel((tile_x + column, tile_y + row))
                    shift = 7 - column
                    plane_0 |= (value & 1) << shift
                    plane_1 |= ((value >> 1) & 1) << shift
                output.extend((plane_0, plane_1))
    if len(output) != 64 * 16:
        raise AssertionError(f"unexpected tile payload size: {len(output)}")
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()

    image = render_logo(Image.open(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encode_tiles(image))
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        preview = image.convert("RGB").resize((WIDTH * 4, HEIGHT * 4), Image.Resampling.NEAREST)
        preview.save(args.preview)


if __name__ == "__main__":
    main()
