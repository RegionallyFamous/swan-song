#!/usr/bin/env python3
"""Generate an open, deterministic WSC general-DMA provenance probe."""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 64 * 1024
FOOTER_SIZE = 16

# 80186 machine code, entered at F000:0000 by the carrier reset vector:
#   cli
#   mov al,0x80; out 0x60,al   ; enable Color mode before Color-only GDMA
#   mov al,0x00; out 0x40,al   ; source f0100
#   mov al,0x01; out 0x41,al
#   mov al,0x0f; out 0x42,al
#   mov al,0x00; out 0x44,al   ; destination 4000
#   mov al,0x40; out 0x45,al
#   mov al,0x04; out 0x46,al   ; four bytes
#   mov al,0x00; out 0x47,al
#   mov al,0x80; out 0x48,al   ; start, increment
# hang: jmp hang
PROGRAM = bytes(
    (
        0xFA,
        0xB0, 0x80, 0xE6, 0x60,
        0xB0, 0x00, 0xE6, 0x40,
        0xB0, 0x01, 0xE6, 0x41,
        0xB0, 0x0F, 0xE6, 0x42,
        0xB0, 0x00, 0xE6, 0x44,
        0xB0, 0x40, 0xE6, 0x45,
        0xB0, 0x04, 0xE6, 0x46,
        0xB0, 0x00, 0xE6, 0x47,
        0xB0, 0x80, 0xE6, 0x48,
        0xEB, 0xFE,
    )
)


def generate(carrier_path: Path, output_path: Path) -> None:
    carrier = carrier_path.read_bytes()
    if len(carrier) < FOOTER_SIZE:
        raise ValueError(f"carrier is shorter than {FOOTER_SIZE} bytes")
    footer = bytearray(carrier[-FOOTER_SIZE:])
    if footer[0] != 0xEA or footer[1:5] != bytes((0x00, 0x00, 0x00, 0xF0)):
        raise ValueError("carrier footer does not reset-jump to F000:0000")

    # The simulator reads the standard color flag from footer byte 7. The
    # generated artifact is intentionally WSC so the color-only GDMA starts.
    footer[7] = 1

    image = bytearray((0xFF,)) * ROM_SIZE
    image[: len(PROGRAM)] = PROGRAM
    image[0x0100:0x0104] = bytes((0x34, 0x12, 0x78, 0x56))
    image[-FOOTER_SIZE:] = footer
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("carrier", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        generate(args.carrier, args.output)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate {args.output}: {error}") from error
    print(f"generated {args.output} ({ROM_SIZE} bytes)")


if __name__ == "__main__":
    main()
