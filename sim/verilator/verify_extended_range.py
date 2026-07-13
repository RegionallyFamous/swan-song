#!/usr/bin/env python3
"""Verify the open WSC 2bpp extended screen/tile/sprite-range fixture."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

from verify_trace import FIELDS_V4, FIELDS_V5


ROM_SHA256 = "72bf0fca0b6e7d3a61cb8c93c7675b4c1ac4e744b39f64ecf63ee3095aaf4346"
WIDTH = 224
HEIGHT = 144
GREEN = bytes((0, 13 * 17, 0))
RED = bytes((12 * 17, 0, 0))


def verify_rom(path: Path) -> None:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != 131072 or digest != ROM_SHA256:
        raise ValueError(
            f"unexpected open fixture: size={len(data)} sha256={digest}"
        )


def verify_trace(path: Path) -> dict[str, int]:
    screen_maps: set[tuple[int, int]] = set()
    screen_tiles: set[tuple[int, int]] = set()
    sprite_addresses: set[int] = set()
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames not in (FIELDS_V4, FIELDS_V5):
            raise ValueError(f"expected exact v4/v5 trace header, got {reader.fieldnames!r}")
        for line, row in enumerate(reader, start=2):
            if row["event"] != "vram":
                continue
            try:
                address = int(row["address"])
                value = int(row["fetch_value"])
            except ValueError as error:
                raise ValueError(f"line {line}: invalid display address/value") from error
            if row["role"] == "screen1_map":
                screen_maps.add((address, value))
            elif row["role"] == "screen1_tile":
                screen_tiles.add((address, value))
            elif row["role"] == "sprite_table":
                sprite_addresses.add(address)

    if (0x5A20, 0x21FC) not in screen_maps:
        raise ValueError("missing extended map fetch 0x5a20=0x21fc")
    required_tiles = {(0x5FC0, 0x7C7C), (0x5FC2, 0x6666)}
    if missing := required_tiles - screen_tiles:
        raise ValueError(f"missing extended tile fetch(es): {sorted(missing)!r}")
    required_sprites = set(range(0x5600, 0x5610, 2))
    if missing := required_sprites - sprite_addresses:
        raise ValueError(
            "missing 2bpp Color extended sprite-table fetch(es): "
            + ", ".join(f"{address:#06x}" for address in sorted(missing))
        )
    aliased = sprite_addresses & set(range(0x1600, 0x1610, 2))
    if aliased:
        raise ValueError(
            "observed incorrect 16-KiB sprite-table alias(es): "
            + ", ".join(f"{address:#06x}" for address in sorted(aliased))
        )
    return {
        "map_words": len(screen_maps),
        "tile_words": len(screen_tiles),
        "sprite_words": len(sprite_addresses),
    }


def verify_frame(path: Path) -> dict[str, int]:
    frame = path.read_bytes()
    expected_size = WIDTH * HEIGHT * 3
    if len(frame) != expected_size:
        raise ValueError(f"expected {expected_size} frame bytes, got {len(frame)}")

    result: dict[str, int] = {}
    for label, tile_y in (("screen", 7), ("tile", 8), ("sprite", 9)):
        colors = []
        for y in range(tile_y * 8, tile_y * 8 + 8):
            for x in range(16 * 8, 20 * 8):
                offset = (y * WIDTH + x) * 3
                colors.append(frame[offset : offset + 3])
        green = colors.count(GREEN)
        red = colors.count(RED)
        if green < 16:
            raise ValueError(f"{label} PASS box has only {green} green pixels")
        if red:
            raise ValueError(f"{label} PASS box contains {red} red FAIL pixels")
        result[f"{label}_green"] = green
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("frame", type=Path)
    args = parser.parse_args()
    try:
        verify_rom(args.rom)
        counts = verify_trace(args.trace)
        counts.update(verify_frame(args.frame))
    except (OSError, ValueError) as error:
        raise SystemExit(f"extended-range fixture: {error}") from error
    print("PASS extended WSC 2bpp ranges " + " ".join(
        f"{name}={value}" for name, value in counts.items()
    ))


if __name__ == "__main__":
    main()
