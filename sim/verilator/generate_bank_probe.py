#!/usr/bin/env python3
"""Generate a deterministic WonderSwan ROM that writes cartridge bank ports.

The generated ROM is a build artifact, not a checked-in binary. Its final
16-byte reset vector/header is copied verbatim from a caller-supplied open test
ROM; the regression uses testroms/spritepriority/spritepriority.ws, whose
provenance and licensing caveat are documented in UPSTREAMS.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 64 * 1024
FOOTER_SIZE = 16

# 80186 machine code, entered at F000:0000 by the carrier reset vector:
#   cli
#   mov al, 0x10; out 0xc0, al
#   mov al, 0x21; out 0xc1, al
#   mov al, 0x32; out 0xc2, al
#   mov al, 0x43; out 0xc3, al
# hang: jmp hang
PROGRAM = bytes(
    (
        0xFA,
        0xB0,
        0x10,
        0xE6,
        0xC0,
        0xB0,
        0x21,
        0xE6,
        0xC1,
        0xB0,
        0x32,
        0xE6,
        0xC2,
        0xB0,
        0x43,
        0xE6,
        0xC3,
        0xEB,
        0xFE,
    )
)


def generate(carrier_path: Path, output_path: Path) -> None:
    carrier = carrier_path.read_bytes()
    if len(carrier) < FOOTER_SIZE:
        raise ValueError(f"carrier is shorter than {FOOTER_SIZE} bytes")

    footer = carrier[-FOOTER_SIZE:]
    # A WonderSwan reset vector is a far jump at offset 0xfff0. The checked-in
    # carrier jumps to F000:0000, where PROGRAM is placed in this 64 KiB image.
    if footer[0] != 0xEA or footer[1:5] != bytes((0x00, 0x00, 0x00, 0xF0)):
        raise ValueError("carrier footer does not reset-jump to F000:0000")

    image = bytearray((0xFF,)) * ROM_SIZE
    image[: len(PROGRAM)] = PROGRAM
    image[-FOOTER_SIZE:] = footer
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("carrier", type=Path, help="open ROM supplying the final 16 bytes")
    parser.add_argument("output", type=Path, help="generated 64 KiB probe ROM")
    args = parser.parse_args()

    try:
        generate(args.carrier, args.output)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate {args.output}: {error}") from error

    print(f"generated {args.output} ({ROM_SIZE} bytes)")


if __name__ == "__main__":
    main()
