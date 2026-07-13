#!/usr/bin/env python3
"""Generate open mono/color boot-overlay stimuli and a tiny carrier ROM.

The generated boot images are simulation-only test programs, not WonderSwan
firmware.  All outputs stay under the caller's build directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 128 * 1024
ROM_PROGRAM_OFFSET = 0x10000
FOOTER_SIZE = 16
ROM_NAME = "boot_overlay_carrier.ws"
MONO_BIOS_NAME = "boot_overlay_mono.bin"
COLOR_BIOS_NAME = "boot_overlay_color.bin"

# The cartridge reset vector lands here after the test boot image locks itself
# out.  Display timing continues normally while the CPU remains in this loop.
ROM_PROGRAM = bytes((0xFA, 0xEB, 0xFE))  # cli; hang: jmp hang


def cartridge_footer() -> bytes:
    return bytes(
        (
            0xEA, 0x00, 0x00, 0x00, 0xF0,  # jmp far F000:0000
            0x00,                          # maintenance / no splash bypass
            0x00,                          # developer/publisher ID
            0x00,                          # mono cartridge
            0x00,                          # game ID
            0x00,                          # game version
            0x00,                          # 1 Mbit / 128 KiB ROM
            0x00,                          # no cartridge save
            0x04,                          # 16-bit ROM bus flag
            0x00,                          # Bandai 2001 mapper
            0x00, 0x00,                    # checksum, filled below
        )
    )


def carrier_rom() -> bytes:
    image = bytearray((0xFF,)) * ROM_SIZE
    image[ROM_PROGRAM_OFFSET : ROM_PROGRAM_OFFSET + len(ROM_PROGRAM)] = ROM_PROGRAM
    image[-FOOTER_SIZE:] = cartridge_footer()
    image[-2:] = (sum(image[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(image)


def boot_image(size: int, segment: int, marker: int) -> bytes:
    """Build a test image that reads its low-window marker then locks out."""

    if (size, segment) not in ((4096, 0xFF00), (8192, 0xFE00)):
        raise ValueError(f"unsupported test boot layout: {size}, {segment:#06x}")

    image = bytearray((0x90,)) * size
    program = bytes(
        (
            0xFA,                          # cli
            0xB8, segment & 0xFF, segment >> 8,  # mov ax, segment
            0x8E, 0xD8,                    # mov ds, ax
            0xA1, 0x00, 0x01,              # mov ax, [0x0100]
            0xB0, 0x01,                    # mov al, 1
            0xE6, 0xA0,                    # out 0xa0, al (boot lockout)
            0xEA, 0x00, 0x00, 0xFF, 0xFF,  # jmp far FFFF:0000
        )
    )
    image[: len(program)] = program
    image[0x100:0x102] = marker.to_bytes(2, "little")
    image[-FOOTER_SIZE : -FOOTER_SIZE + 5] = bytes(
        (0xEA, 0x00, 0x00, segment & 0xFF, segment >> 8)
    )
    return bytes(image)


def generate(output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rom = output_dir / ROM_NAME
    mono = output_dir / MONO_BIOS_NAME
    color = output_dir / COLOR_BIOS_NAME
    rom.write_bytes(carrier_rom())
    mono.write_bytes(boot_image(4096, 0xFF00, 0xB007))
    color.write_bytes(boot_image(8192, 0xFE00, 0xC007))
    return rom, mono, color


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        paths = generate(args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate boot-overlay probe: {error}") from error
    for path in paths:
        print(f"generated {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
