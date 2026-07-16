#!/usr/bin/env python3
"""Generate carrier ROMs for all eight built-in Open IPL footer variants.

The ROMs cover mono/color, 8/16-bit bus, and protected/writable owner-area
policy through normal cartridge footers. No boot image or firmware input is
generated.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 128 * 1024
ROM_PROGRAM_OFFSET = 0x10000
FOOTER_SIZE = 16
VARIANTS = tuple(
    (
        f"{model}-word{16 if word_width else 8}-owner-"
        f"{'protected' if protect_owner_area else 'writable'}",
        color,
        word_width,
        protect_owner_area,
    )
    for model, color in (("mono", False), ("color", True))
    for word_width in (False, True)
    for protect_owner_area in (False, True)
)


def rom_name(variant: str, color: bool, word_width: bool, protect_owner_area: bool) -> str:
    if word_width and protect_owner_area:
        return f"boot_overlay_{'color' if color else 'mono'}.{ 'wsc' if color else 'ws'}"
    return f"boot_overlay_{variant.replace('-', '_')}.{ 'wsc' if color else 'ws'}"


ROM_NAMES = {
    variant: rom_name(variant, color, word_width, protect_owner_area)
    for variant, color, word_width, protect_owner_area in VARIANTS
}

# The cartridge reset vector lands here after Open IPL locks itself out.
# Display timing continues normally while the CPU remains in this loop.
ROM_PROGRAM = bytes((0xFA, 0xEB, 0xFE))  # cli; hang: jmp hang


def cartridge_footer(
    *, color: bool, word_width: bool, protect_owner_area: bool
) -> bytes:
    return bytes(
        (
            0xEA, 0x00, 0x00, 0x00, 0xF0,  # jmp far F000:0000
            0x00,                          # maintenance / no splash bypass
            0x00,                          # developer/publisher ID
            0x01 if color else 0x00,       # minimum system
            0x00,                          # game ID
            0x00 if protect_owner_area else 0x80,  # owner-area policy
            0x00,                          # 1 Mbit / 128 KiB ROM
            0x00,                          # no cartridge save
            0x04 if word_width else 0x00,  # ROM bus-width flag
            0x00,                          # Bandai 2001 mapper
            0x00, 0x00,                    # checksum, filled below
        )
    )


def carrier_rom(
    *, color: bool, word_width: bool = True, protect_owner_area: bool = True
) -> bytes:
    image = bytearray((0xFF,)) * ROM_SIZE
    image[ROM_PROGRAM_OFFSET : ROM_PROGRAM_OFFSET + len(ROM_PROGRAM)] = ROM_PROGRAM
    image[-FOOTER_SIZE:] = cartridge_footer(
        color=color,
        word_width=word_width,
        protect_owner_area=protect_owner_area,
    )
    image[-2:] = (sum(image[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(image)


def generate(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for variant, color, word_width, protect_owner_area in VARIANTS:
        path = output_dir / ROM_NAMES[variant]
        path.write_bytes(
            carrier_rom(
                color=color,
                word_width=word_width,
                protect_owner_area=protect_owner_area,
            )
        )
        paths[variant] = path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        paths = generate(args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate boot-overlay probe: {error}") from error
    for path in paths.values():
        print(f"generated {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
