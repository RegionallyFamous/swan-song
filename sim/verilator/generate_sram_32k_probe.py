#!/usr/bin/env python3
"""Generate paired type-01/type-02 WonderSwan 32 KiB SRAM probes."""

from __future__ import annotations

import argparse
from pathlib import Path

from generate_mapper_memory_probe import bootstrap_image


ROM_SIZE = 2 * 1024 * 1024
PROGRAM_OFFSET = 0x1F0000
FOOTER_SIZE = 16
BOOTSTRAP_NAME = "sram_32k_boot.bin"
ROM_NAMES = {
    1: "sram_type01_32k.ws",
    2: "sram_type02_32k.ws",
}

# Entered at F000:0000 after the open bootstrap locks out the boot ROM.  Each
# type writes three distinct bytes within the documented 32 KiB SRAM, reads
# them back, then reads offset 0x8000 to prove it mirrors offset 0x0000.
PROGRAM = bytes(
    (
        0xFA,                          # cli
        0xB8, 0x00, 0x10,             # mov ax, 0x1000
        0x8E, 0xD8,                   # mov ds, ax
        0xC6, 0x06, 0x00, 0x00, 0x11, # mov byte [0x0000], 0x11
        0xC6, 0x06, 0x00, 0x20, 0x22, # mov byte [0x2000], 0x22
        0xC6, 0x06, 0xFF, 0x7F, 0x33, # mov byte [0x7fff], 0x33
        0xA0, 0x00, 0x00,             # mov al, [0x0000]
        0xA0, 0x00, 0x20,             # mov al, [0x2000]
        0xA0, 0xFF, 0x7F,             # mov al, [0x7fff]
        0xA0, 0x00, 0x80,             # mov al, [0x8000]
        0xEB, 0xFE,                   # hang: jmp hang
    )
)


def footer(ram_type: int) -> bytes:
    if ram_type not in ROM_NAMES:
        raise ValueError(f"unsupported SRAM type {ram_type}")
    return bytes(
        (
            0xEA, 0x00, 0x00, 0x00, 0xF0, # jmp far F000:0000
            0x00,                         # maintenance
            0x00,                         # developer/publisher ID
            0x00,                         # mono cartridge
            0x00,                         # game ID
            0x00,                         # game version
            0x04,                         # 16 Mbit / 2 MiB ROM
            ram_type,                     # paired SRAM declaration
            0x04,                         # 16-bit ROM bus
            0x00,                         # Bandai 2001 mapper
            0x00, 0x00,                   # checksum, filled below
        )
    )


def image(ram_type: int) -> bytes:
    result = bytearray((0xFF,)) * ROM_SIZE
    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(PROGRAM)] = PROGRAM
    result[-FOOTER_SIZE:] = footer(ram_type)
    result[-2:] = (sum(result[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


def generate(output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    type01 = output_dir / ROM_NAMES[1]
    type02 = output_dir / ROM_NAMES[2]
    bootstrap = output_dir / BOOTSTRAP_NAME
    type01.write_bytes(image(1))
    type02.write_bytes(image(2))
    bootstrap.write_bytes(bootstrap_image())
    return type01, type02, bootstrap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        paths = generate(args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate 32 KiB SRAM probes: {error}") from error
    for path in paths:
        print(f"generated {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
