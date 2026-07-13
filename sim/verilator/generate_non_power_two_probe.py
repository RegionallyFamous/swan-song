#!/usr/bin/env python3
"""Generate the repository-authored 896 KiB compact-ROM regression image.

The executable payload is assembled from Swan Song's own generated packed
4bpp probe.  This script adds a distinct identity/footer and emits no borrowed
game, demo, firmware, or carrier-ROM bytes.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import generate_4bpp_probe as base


RAW_SIZE = 896 * 1024
APERTURE_SIZE = 1024 * 1024
PREFIX_SIZE = APERTURE_SIZE - RAW_SIZE
PAYLOAD_OFFSET = RAW_SIZE - base.ROM_SIZE
MARKER_OFFSET = PAYLOAD_OFFSET + base.MARKER_OFFSET
FOOTER_OFFSET = RAW_SIZE - 16
OUTPUT_NAME = "wsc_896k_compact_probe.wsc"
MARKER = b"SWANSONG-WSC-NP2-896K-V1\0"


def restamp_checksum(rom: bytearray) -> None:
    rom[-2:] = (sum(rom[:-2]) & 0xFFFF).to_bytes(2, "little")


def image() -> bytes:
    """Return one deterministic checksummed 896 KiB WSC image."""

    payload = base.image(base.PACKED)
    result = bytearray(b"\xFF" * RAW_SIZE)
    result[PAYLOAD_OFFSET:] = payload

    old_marker = base.marker(base.PACKED)
    result[MARKER_OFFSET : MARKER_OFFSET + len(old_marker)] = b"\xFF" * len(
        old_marker
    )
    result[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] = MARKER

    footer = result[FOOTER_OFFSET:]
    footer[5] = 0xA0  # Legal maintenance flags; reserved low nibble stays zero.
    footer[8] = 0x96  # Repository fixture ID.
    footer[9] = 0x01  # Fixture format version.
    footer[10] = 0x03  # The mapped image occupies a 1 MiB aperture.
    footer[11] = 0x00  # No save memory.
    footer[12] = 0x04  # 16-bit ROM bus, horizontal.
    footer[13] = 0x00  # Bandai 2001 mapper contract.
    footer[14:16] = b"\x00\x00"
    result[FOOTER_OFFSET:] = footer
    restamp_checksum(result)
    return bytes(result)


def validate(rom: bytes) -> None:
    if len(rom) < 16 or len(rom) > 16 * 1024 * 1024:
        raise ValueError("ROM size is outside 16 bytes..16 MiB")
    if len(rom) & (len(rom) - 1) == 0:
        return
    if len(rom) < 64 * 1024 or len(rom) % (64 * 1024):
        raise ValueError("non-power-of-two ROM size must be 64 KiB-aligned")
    aperture = 1 << (len(rom) - 1).bit_length()
    if rom[-16] != 0xEA:
        raise ValueError("footer entry must begin with 0xEA")
    if rom[-11] & 0x0F:
        raise ValueError("footer maintenance low bits must be zero")
    if rom[-9] & 0xFE:
        raise ValueError("footer color field is invalid")
    declared_sizes = {
        0x00: 128 * 1024,
        0x01: 256 * 1024,
        0x02: 512 * 1024,
        0x03: 1024 * 1024,
        0x04: 2 * 1024 * 1024,
        0x05: 3 * 1024 * 1024,
        0x06: 4 * 1024 * 1024,
        0x07: 6 * 1024 * 1024,
        0x08: 8 * 1024 * 1024,
        0x09: 16 * 1024 * 1024,
    }
    if declared_sizes.get(rom[-6]) not in (len(rom), aperture):
        raise ValueError("footer size does not match file or aperture")
    if rom[-5] not in (0, 1, 2, 3, 4, 5, 0x10, 0x20, 0x50):
        raise ValueError("footer save type is unsupported")
    if not rom[-4] & 0x04:
        raise ValueError("footer must select the 16-bit ROM bus")
    if rom[-3] > 1:
        raise ValueError("footer mapper is unsupported")
    stored = int.from_bytes(rom[-2:], "little")
    computed = sum(rom[:-2]) & 0xFFFF
    if stored != computed:
        raise ValueError("footer checksum mismatch")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--memh", type=Path)
    args = parser.parse_args()

    rom = image()
    validate(rom)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rom)
    if args.memh is not None:
        args.memh.parent.mkdir(parents=True, exist_ok=True)
        args.memh.write_text("\n".join(f"{byte:02x}" for byte in rom) + "\n")
    print(f"generated {args.output} ({len(rom)} bytes)")


if __name__ == "__main__":
    main()
