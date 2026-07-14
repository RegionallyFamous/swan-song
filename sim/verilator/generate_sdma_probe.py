#!/usr/bin/env python3
"""Generate a deterministic open WSC Sound-DMA provenance probe."""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 128 * 1024
PROGRAM_OFFSET = 0x10000
MARKER_OFFSET = 0x10100
FOOTER_SIZE = 16
ROM_NAME = "sdma_probe.wsc"
MARKER = bytes((0xA1, 0xB2, 0xC3, 0xD4))

# 80186 machine code entered at F000:0000. It explicitly enables Color mode,
# selects physical source F0100, configures a four-byte one-shot transfer
# incrementing toward Channel 2 at 24 kHz, then spins while SDMA performs the
# reads. This is open test code, not firmware.
PROGRAM = bytes(
    (
        0xFA,                    # cli
        0xB0, 0x80, 0xE6, 0x60,  # enable Color mode before Color-only SDMA
        0xB0, 0x00, 0xE6, 0x4A,  # source low
        0xB0, 0x01, 0xE6, 0x4B,  # source middle
        0xB0, 0x0F, 0xE6, 0x4C,  # source high
        0xB0, 0x04, 0xE6, 0x4E,  # length low
        0xB0, 0x00, 0xE6, 0x4F,  # length middle
        0xB0, 0x00, 0xE6, 0x50,  # length high
        0xB0, 0x83, 0xE6, 0x52,  # enable, increment, one-shot, Ch2, 24 kHz
        0xEB, 0xFE,              # hang: jmp hang
    )
)


def footer() -> bytes:
    return bytes(
        (
            0xEA, 0x00, 0x00, 0x00, 0xF0,  # jmp far F000:0000
            0x00,                          # maintenance / no splash bypass
            0x00,                          # developer/publisher ID
            0x01,                          # Color cartridge
            0x00,                          # game ID
            0x00,                          # game version
            0x00,                          # 1 Mbit / 128 KiB ROM
            0x00,                          # no cartridge save
            0x04,                          # 16-bit ROM bus flag
            0x00,                          # Bandai 2001 mapper
            0x00, 0x00,                    # checksum, filled below
        )
    )


def image() -> bytes:
    result = bytearray((0xFF,)) * ROM_SIZE
    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(PROGRAM)] = PROGRAM
    result[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] = MARKER
    result[-FOOTER_SIZE:] = footer()
    result[-2:] = (sum(result[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


def generate(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / ROM_NAME
    path.write_bytes(image())
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        path = generate(args.output_dir)
    except OSError as error:
        raise SystemExit(f"cannot generate SDMA probe: {error}") from error
    print(f"generated {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
