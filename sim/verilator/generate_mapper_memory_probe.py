#!/usr/bin/env python3
"""Generate deterministic mono WonderSwan mapper-memory probe ROMs.

The ROMs boot through the core's built-in Open IPL, share one small 80186
program, and differ only in whether their cartridge footer declares 128 KiB
of SRAM or no SRAM.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 2 * 1024 * 1024
PROGRAM_OFFSET = 0x1F0000
ROM0_MARKER_OFFSET = 0x151234
ROM1_MARKER_OFFSET = 0x161234
LINEAR_MARKER_OFFSET = 0x171234
ROM0_MARKER = bytes((0x0F, 0xA1))
ROM1_MARKER = bytes((0x0E, 0xB2))
LINEAR_MARKER = bytes((0x0D, 0xC3))
FOOTER_SIZE = 16
PRESENT_NAME = "mapper_memory_present.ws"
ABSENT_NAME = "mapper_memory_absent.ws"

# 80186 machine code, entered at F000:0000 by the reset vector.  The probe:
#
# * selects ROM linear bank 1, SRAM bank 1, ROM0 bank 0x15, and ROM1 bank 0x16;
# * writes then reads an even word and odd byte in the 0x1 SRAM window;
# * selects SRAM bank 3 and re-reads the bank-1 data through the 128 KiB mask;
# * writes then reads an even word and odd byte in mono-only unmapped IRAM;
# * reads distinct ROM0, ROM1, and linear sentinels; and
# * reads the ROM0 and ROM1 sentinels again through their linear aliases.
#
# A 2 MiB image preserves C0 bit 0 in mapped offsets.  The program is in the
# top mapped bank selected at reset; writing C0=1 keeps that mapping stable.
PROGRAM = bytes(
    (
        0xFA,                    # cli
        0xB0, 0x01,             # mov al, 1
        0xE6, 0xC0,             # out 0xc0, al
        0xB0, 0x01,             # mov al, 1
        0xE6, 0xC1,             # out 0xc1, al
        0xB0, 0x15,             # mov al, 0x15
        0xE6, 0xC2,             # out 0xc2, al
        0xB0, 0x16,             # mov al, 0x16
        0xE6, 0xC3,             # out 0xc3, al
        0xB8, 0x00, 0x10,       # mov ax, 0x1000
        0x8E, 0xD8,             # mov ds, ax
        0xB8, 0x5A, 0xA5,       # mov ax, 0xa55a
        0xA3, 0x34, 0x12,       # mov [0x1234], ax
        0xA1, 0x34, 0x12,       # mov ax, [0x1234]
        0xC6, 0x06, 0x35, 0x12, 0x7E,  # mov byte [0x1235], 0x7e
        0xA0, 0x35, 0x12,       # mov al, [0x1235]
        0xB0, 0x03,             # mov al, 3
        0xE6, 0xC1,             # out 0xc1, al
        0xA1, 0x34, 0x12,       # mov ax, [0x1234]
        0xB8, 0x00, 0x04,       # mov ax, 0x0400
        0x8E, 0xD8,             # mov ds, ax
        0xB8, 0xC3, 0x3C,       # mov ax, 0x3cc3
        0xA3, 0x00, 0x00,       # mov [0x0000], ax
        0xA1, 0x00, 0x00,       # mov ax, [0x0000]
        0xC6, 0x06, 0x01, 0x00, 0x7D,  # mov byte [0x0001], 0x7d
        0xA0, 0x01, 0x00,       # mov al, [0x0001]
        0xB8, 0x00, 0x20,       # mov ax, 0x2000
        0x8E, 0xD8,             # mov ds, ax
        0xA1, 0x34, 0x12,       # mov ax, [0x1234]
        0xB8, 0x00, 0x30,       # mov ax, 0x3000
        0x8E, 0xD8,             # mov ds, ax
        0xA1, 0x34, 0x12,       # mov ax, [0x1234]
        0xB8, 0x00, 0x50,       # mov ax, 0x5000
        0x8E, 0xD8,             # mov ds, ax
        0xA1, 0x34, 0x12,       # mov ax, [0x1234]
        0xB8, 0x00, 0x60,       # mov ax, 0x6000
        0x8E, 0xD8,             # mov ds, ax
        0xA1, 0x34, 0x12,       # mov ax, [0x1234]
        0xB8, 0x00, 0x70,       # mov ax, 0x7000
        0x8E, 0xD8,             # mov ds, ax
        0xA1, 0x34, 0x12,       # mov ax, [0x1234]
        0xEB, 0xFE,             # hang: jmp hang
    )
)


def footer(ram_type: int) -> bytes:
    """Return a mono cartridge footer with a reset jump and blank checksum."""

    if ram_type not in (0, 3):
        raise ValueError(f"unsupported RAM type {ram_type}")
    return bytes(
        (
            0xEA, 0x00, 0x00, 0x00, 0xF0,  # jmp far F000:0000
            0x00,                          # maintenance / no splash bypass
            0x00,                          # developer/publisher ID
            0x00,                          # mono cartridge
            0x00,                          # game ID
            0x00,                          # game version
            0x04,                          # 16 Mbit / 2 MiB ROM
            ram_type,                      # 0 none, 3 = 128 KiB SRAM
            0x04,                          # 16-bit ROM bus flag
            0x00,                          # Bandai 2001 mapper
            0x00, 0x00,                    # checksum, filled below
        )
    )


def image(ram_type: int) -> bytes:
    result = bytearray((0xFF,)) * ROM_SIZE
    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(PROGRAM)] = PROGRAM
    result[ROM0_MARKER_OFFSET : ROM0_MARKER_OFFSET + len(ROM0_MARKER)] = ROM0_MARKER
    result[ROM1_MARKER_OFFSET : ROM1_MARKER_OFFSET + len(ROM1_MARKER)] = ROM1_MARKER
    result[
        LINEAR_MARKER_OFFSET : LINEAR_MARKER_OFFSET + len(LINEAR_MARKER)
    ] = LINEAR_MARKER
    result[-FOOTER_SIZE:] = footer(ram_type)
    result[-2:] = (sum(result[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


def generate(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    present = output_dir / PRESENT_NAME
    absent = output_dir / ABSENT_NAME
    present.write_bytes(image(3))
    absent.write_bytes(image(0))
    return present, absent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        paths = generate(args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate mapper-memory probes: {error}") from error
    for path in paths:
        print(f"generated {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
