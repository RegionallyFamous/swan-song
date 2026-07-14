#!/usr/bin/env python3
"""Generate a deterministic WonderSwan ROM that writes cartridge mapper ports.

The generated ROM is a build artifact, not a checked-in binary. Its final
16-byte reset vector/header starts from a caller-supplied open test ROM; the
probe changes only the footer RTC/2003-selector byte and recomputes the checksum.
The regression uses testroms/spritepriority/spritepriority.ws, whose provenance
and licensing caveat are documented in UPSTREAMS.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 64 * 1024
FOOTER_SIZE = 16

# 80186 machine code, entered at F000:0000 by the carrier reset vector. The
# comments below record the exact reset-to-probe instruction-chain identity and
# physical origin PC expected by the regression verifier for each mapper write.
#   cli
#   mov al, 0x10; out 0xc0, al  # instruction 7,  PC 0xf0003
#   mov al, 0x21; out 0xc1, al  # instruction 9,  PC 0xf0007
#   mov al, 0x32; out 0xc2, al  # instruction 11, PC 0xf000b
#   mov al, 0x43; out 0xc3, al  # instruction 13, PC 0xf000f
#   mov ax, 0x6655
#   out 0xc0, ax                 # instruction 15, PC 0xf0014; C0 then C1
#   mov al, 0x54; out 0xcf, al   # instruction 17, PC 0xf0018
#   mov ax, 0x0103; out 0xd0, ax # instruction 19, PC 0xf001d; D0 low, D1 high
#   mov ax, 0x0204; out 0xd2, ax # instruction 21, PC 0xf0022; D2 low, D3 high
#   mov ax, 0x0305; out 0xd4, ax # instruction 23, PC 0xf0027; D4 low, D5 high
#   mov al, 0x01; out 0xce, al   # instruction 25, PC 0xf002b; self-flash control
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
        0xB8,
        0x55,
        0x66,
        0xE7,
        0xC0,
        0xB0,
        0x54,
        0xE6,
        0xCF,
        0xB8,
        0x03,
        0x01,
        0xE7,
        0xD0,
        0xB8,
        0x04,
        0x02,
        0xE7,
        0xD2,
        0xB8,
        0x05,
        0x03,
        0xE7,
        0xD4,
        0xB0,
        0x01,
        0xE6,
        0xCE,
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
    image[-3] = 0x01
    image[-2:] = (sum(image[:-2]) & 0xFFFF).to_bytes(2, "little")
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
