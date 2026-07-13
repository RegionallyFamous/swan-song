#!/usr/bin/env python3
"""Generate deterministic WonderSwan Color 4bpp format probes.

The fixtures are built entirely from repository-authored 80186 machine code and
data.  No assembler, SDK, carrier ROM, or checked-in binary is required.

The contract follows the repository RTL first (``gpu.vhd`` mode selection and
``gpu_bg.vhd`` 4bpp address/decode paths); pinned independent-core and hardware
references are recorded in ``UPSTREAMS.md``.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 128 * 1024
PROGRAM_OFFSET = 0x10000
PATTERN_OFFSET = PROGRAM_OFFSET + 0x0100
MARKER_OFFSET = PROGRAM_OFFSET + 0x0400
FOOTER_OFFSET = ROM_SIZE - 16

PLANAR = "planar"
PACKED = "packed"
VARIANTS = (PLANAR, PACKED)

OUTPUT_NAMES = {
    PLANAR: "wsc_4bpp_planar_probe.wsc",
    PACKED: "wsc_4bpp_packed_probe.wsc",
}
# Hardware-contract review trail and pinned sources: UPSTREAMS.md, paired 4bpp.
SYSTEM_CONTROL_2 = {
    PLANAR: 0xC0,  # Color, 4bpp, planar.
    PACKED: 0xE0,  # Color, 4bpp, packed/chunky.
}
GAME_IDS = {
    PLANAR: 0x40,
    PACKED: 0x41,
}

SCREEN_MAP_ADDRESS = 0x1800
TILE_INDEX = 1
TILE_ADDRESS = 0x4000 + TILE_INDEX * 32
PALETTE_ADDRESS = 0xFE00
MAP_ENTRIES = (
    (0x1A14, 0x0001),  # x=10, y=8, normal
    (0x1A16, 0x4001),  # x=11, y=8, horizontal flip
    (0x1A18, 0x8001),  # x=12, y=8, vertical flip
    (0x1A1A, 0xC001),  # x=13, y=8, horizontal + vertical flip
)

# Every nonzero nibble value is exercised, with asymmetric rows to expose bit,
# nibble, byte, and row-order mistakes. Index zero is deliberately omitted
# because it is transparent in all 4bpp palettes.
PIXELS = (
    (1, 2, 3, 4, 5, 6, 7, 8),
    (8, 7, 6, 5, 4, 3, 2, 1),
    (1, 1, 2, 2, 3, 3, 4, 4),
    (5, 5, 6, 6, 7, 7, 8, 8),
    (9, 10, 11, 12, 13, 14, 15, 1),
    (15, 14, 13, 12, 11, 10, 9, 8),
    (2, 4, 6, 8, 10, 12, 14, 1),
    (1, 3, 5, 7, 9, 11, 13, 15),
)

# RGB444 palette values. Entry zero remains black/transparent; the other
# entries make format failures visually obvious when the probe is displayed.
PALETTE = (
    0x000,
    0x00F,
    0x0F0,
    0xF00,
    0x0FF,
    0xF0F,
    0xFF0,
    0x888,
    0x444,
    0x08F,
    0x0F8,
    0x80F,
    0xF80,
    0x8F0,
    0xF08,
    0xFFF,
)


def _validate_variant(variant: str) -> None:
    if variant not in VARIANTS:
        raise ValueError(f"unsupported 4bpp variant: {variant!r}")


def _word(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def _mov_word(address: int, value: int) -> bytes:
    """Encode ``mov word [address], value`` using a 16-bit direct address."""

    return b"\xC7\x06" + _word(address) + _word(value)


def _encode_planar_row(pixels: tuple[int, ...]) -> bytes:
    planes = [0, 0, 0, 0]
    for x, pixel in enumerate(pixels):
        for plane in range(4):
            planes[plane] |= ((pixel >> plane) & 1) << (7 - x)
    return bytes(planes)


def _encode_packed_row(pixels: tuple[int, ...]) -> bytes:
    return bytes(
        (pixels[x] << 4) | pixels[x + 1]
        for x in range(0, len(pixels), 2)
    )


def tile_bytes(variant: str) -> bytes:
    """Return the 32-byte hardware tile payload for ``variant``."""

    _validate_variant(variant)
    encoder = _encode_planar_row if variant == PLANAR else _encode_packed_row
    return b"".join(encoder(row) for row in PIXELS)


def marker(variant: str) -> bytes:
    _validate_variant(variant)
    return f"SWANSONG-WSC-4BPP-{variant.upper()}-V1\0".encode("ascii")


def program(variant: str) -> bytes:
    """Build the raw 80186 program that displays the format probe."""

    _validate_variant(variant)
    code = bytearray()

    # Establish flat IRAM segments, keep interrupts off, and hide the display
    # while its state is constructed.
    code += b"\xFA"              # cli
    code += b"\xFC"              # cld
    code += b"\x31\xC0"          # xor ax, ax
    code += b"\x8E\xD8"          # mov ds, ax
    code += b"\x8E\xC0"          # mov es, ax
    code += b"\xB0\x00\xE6\x14"  # mov al, 0; out 14h, al (LCD off)
    code += b"\xB0\x00\xE6\x00"  # mov al, 0; out 00h, al (layers off)

    # Preserve the timing bits while selecting color 4bpp planar or packed.
    code += b"\xE4\x60"                          # in al, 60h
    code += b"\x24\x1F"                          # and al, 1fh
    code += bytes((0x0C, SYSTEM_CONTROL_2[variant]))  # or al, mode
    code += b"\xE6\x60"                          # out 60h, al

    code += b"\xB0\x03\xE6\x07"  # Screen 1 at 1800h, Screen 2 at 0000h.
    code += b"\xB0\x00\xE6\x01"  # Black background.
    code += b"\xE6\x10\xE6\x11"  # Screen 1 scroll X/Y = 0.

    # Clear the 32x32 Screen 1 map, then place one diagnostic tile in all four
    # flip orientations at x=10..13, y=8.
    code += b"\x31\xC0"            # xor ax, ax
    code += b"\xBF\x00\x18"      # mov di, 1800h
    code += b"\xB9\x00\x04"      # mov cx, 1024
    code += b"\xF3\xAB"          # rep stosw

    for address, value in MAP_ENTRIES:
        code += _mov_word(address, value)

    for index, color in enumerate(PALETTE):
        code += _mov_word(PALETTE_ADDRESS + index * 2, color)

    # Copy the exact format-specific 32-byte tile from linear ROM F0100 to
    # IRAM 4020h.  This makes every contributing tile byte independently
    # recoverable through the existing GDMA provenance tracker.
    for port, value in (
        (0x40, 0x00),  # source low
        (0x41, 0x01),  # source middle
        (0x42, 0x0F),  # source high: physical F0100
        (0x44, TILE_ADDRESS & 0xFF),
        (0x45, TILE_ADDRESS >> 8),
        (0x46, 0x20),  # length low: 32 bytes
        (0x47, 0x00),
        (0x48, 0x80),  # start, increment
    ):
        code += bytes((0xB0, value, 0xE6, port))

    code += b"\xB0\x01\xE6\x00"  # Enable Screen 1.
    code += b"\xB0\x01\xE6\x14"  # Enable LCD.
    code += b"\xEB\xFE"          # jmp $
    return bytes(code)


def footer(variant: str) -> bytes:
    """Build a standard 16-byte WonderSwan Color cartridge footer."""

    _validate_variant(variant)
    result = bytearray(16)
    result[0:5] = b"\xEA\x00\x00\x00\xF0"  # jmp far F000:0000
    result[5] = 0x00  # Maintenance byte.
    result[6] = 0x00  # Homebrew/test developer ID.
    result[7] = 0x01  # WonderSwan Color required.
    result[8] = GAME_IDS[variant]
    result[9] = 0x01  # Fixture format version.
    result[10] = 0x00  # 128 KiB ROM.
    result[11] = 0x00  # No save memory.
    result[12] = 0x04  # 16-bit ROM bus, horizontal orientation.
    result[13] = 0x00  # Standard mapper.
    return bytes(result)


def image(variant: str) -> bytes:
    """Construct one complete, checksummed WSC ROM image."""

    _validate_variant(variant)
    result = bytearray(b"\xFF" * ROM_SIZE)
    machine_code = program(variant)
    identity = marker(variant)

    pattern = tile_bytes(variant)

    if PROGRAM_OFFSET + len(machine_code) > PATTERN_OFFSET:
        raise ValueError("4bpp probe program overlaps its tile pattern")
    if PATTERN_OFFSET + len(pattern) > MARKER_OFFSET:
        raise ValueError("4bpp probe tile pattern overlaps its identity marker")
    if MARKER_OFFSET + len(identity) > FOOTER_OFFSET:
        raise ValueError("4bpp probe identity marker overlaps its footer")

    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(machine_code)] = machine_code
    result[PATTERN_OFFSET : PATTERN_OFFSET + len(pattern)] = pattern
    result[MARKER_OFFSET : MARKER_OFFSET + len(identity)] = identity
    result[FOOTER_OFFSET:] = footer(variant)
    checksum = sum(result[:-2]) & 0xFFFF
    result[-2:] = _word(checksum)
    return bytes(result)


def generate(output_dir: Path) -> tuple[Path, Path]:
    """Write both variants and return their paths in planar/packed order."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for variant in VARIANTS:
        path = output_dir / OUTPUT_NAMES[variant]
        path.write_bytes(image(variant))
        paths.append(path)
    return paths[0], paths[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "build/sim/4bpp-probe/roms",
        help="directory for generated .wsc probes",
    )
    args = parser.parse_args()

    for path in generate(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
