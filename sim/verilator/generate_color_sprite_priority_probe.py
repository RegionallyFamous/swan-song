#!/usr/bin/env python3
"""Generate a clean-room WSC Color sprite-priority diagnostic ROM.

The generated image is a build artifact made only from repository-authored
80186 bytes and small synthetic color tiles.  It needs no assembler, SDK,
firmware, carrier ROM, font, or external asset.

The critical sample places two opaque sprites over an opaque Screen 2 tile.
The earlier sprite-table entry has low Screen 2 priority; the later entry has
high priority.  The pinned reference contract therefore skips the blocked
earlier sprite and shows the later high-priority sprite.  Three adjacent
control samples make that focused Color-compositor case resistant to palette
and ordering mistakes.

Pinned review trail (retrieved 2026-07-13):

* ares sprite selection and attributes, commit 449b93716fb162632de2fd43bf2eba2064fa43f2:
  https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/sprite.cpp#L1-L76
* Mednafen sprite composition, Debian source 1.32.1+dfsg-3:
  https://sources.debian.org/src/mednafen/1.32.1%2Bdfsg-3/src/wswan/gfx.cpp/#L784-L904
* WSdev sprite attributes/order, permanent revision 507:
  https://ws.nesdev.org/w/index.php?title=Display/Sprites&oldid=507
* WSdev layer order, permanent revision 555:
  https://ws.nesdev.org/w/index.php?title=Display&oldid=555
* ws-test-suite sprite scanline/list-order hardware test, commit 7dfa0e2e869d08386b685d6a56df0bcfaf181b47:
  https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/mono/display/sprite_scanline_limit/main.c#L8-L82

That open hardware test corroborates ordinary list ordering and the 32-sprite
limit, not the critical Color fallback.  No directly applicable reported
real-hardware result for that fallback was found; acceptance here is limited
to the translated RTL behavior against the pinned reference contract.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 128 * 1024
PROGRAM_OFFSET = 0x10000       # Physical F0000h in a 128 KiB image.
TILE_PAYLOAD_OFFSET = 0x10200  # Physical F0200h.
MARKER_OFFSET = 0x10400
FOOTER_OFFSET = ROM_SIZE - 16
OUTPUT_NAME = "wsc_color_sprite_priority_probe.wsc"
MARKER = b"SWANSONG-WSC-COLOR-SPRITE-PRIORITY-V1\0"

SCREEN2_MAP_ADDRESS = 0x0000
SPRITE_TABLE_ADDRESS = 0x1000
SPRITE_Y = 64
TILE_BASE_ADDRESS = 0x4000
TILE_PAYLOAD_ADDRESS = 0x4000       # Transparent tile 0 plus tiles 1..3.
TILE_PAYLOAD_SIZE = 4 * 32

SCREEN2_TILE = 3
EARLIER_LOW_TILE = 1
LATER_HIGH_TILE = 2

# Four-byte sprite descriptors are (attribute word, y byte, x byte).  Attribute
# palette values 0 and 1 select Color palettes 8 and 9 after the sprite offset.
EARLIER_LOW_ATTRIBUTE = 0x0001  # tile 1, palette 8, below opaque Screen 2.
LATER_HIGH_ATTRIBUTE = 0x2202   # tile 2, palette 9, above Screen 2.

LOW_OVER_SCREEN2_X = 64
CRITICAL_X = 80
HIGH_OVER_SCREEN2_X = 96
OVERLAP_NO_SCREEN2_X = 112
SPRITE_POSITION_WORD = (CRITICAL_X << 8) | SPRITE_Y

SCREEN2_MAP_WORDS = (
    (0x0210, SCREEN2_TILE),  # x=64: low sprite behind opaque Screen 2.
    (0x0214, SCREEN2_TILE),  # x=80: critical low+high+opaque Screen 2.
    (0x0218, SCREEN2_TILE),  # x=96: high sprite above opaque Screen 2.
)

# Descriptor order is intentional.  The two pairs each put the low-priority
# descriptor before the high-priority descriptor; the remaining samples have
# only the one sprite needed for their control case.
OAM_WORDS = (
    (SPRITE_TABLE_ADDRESS + 0, EARLIER_LOW_ATTRIBUTE),
    (SPRITE_TABLE_ADDRESS + 2, (LOW_OVER_SCREEN2_X << 8) | SPRITE_Y),
    (SPRITE_TABLE_ADDRESS + 4, LATER_HIGH_ATTRIBUTE),
    (SPRITE_TABLE_ADDRESS + 6, (HIGH_OVER_SCREEN2_X << 8) | SPRITE_Y),
    (SPRITE_TABLE_ADDRESS + 8, EARLIER_LOW_ATTRIBUTE),
    (SPRITE_TABLE_ADDRESS + 10, (OVERLAP_NO_SCREEN2_X << 8) | SPRITE_Y),
    (SPRITE_TABLE_ADDRESS + 12, LATER_HIGH_ATTRIBUTE),
    (SPRITE_TABLE_ADDRESS + 14, (OVERLAP_NO_SCREEN2_X << 8) | SPRITE_Y),
    (SPRITE_TABLE_ADDRESS + 16, EARLIER_LOW_ATTRIBUTE),
    (SPRITE_TABLE_ADDRESS + 18, SPRITE_POSITION_WORD),
    (SPRITE_TABLE_ADDRESS + 20, LATER_HIGH_ATTRIBUTE),
    (SPRITE_TABLE_ADDRESS + 22, SPRITE_POSITION_WORD),
)

# Native RGB444 palette words and the RGB888 values emitted by the simulator.
SCREEN2_BLUE = 0x00F
EARLIER_LOW_RED = 0xF00
LATER_HIGH_GREEN = 0x0F0
PALETTE_WORDS = (
    (0xFE02, SCREEN2_BLUE),       # Background palette 0, color index 1.
    (0xFF04, EARLIER_LOW_RED),    # Sprite palette 8, color index 2.
    (0xFF26, LATER_HIGH_GREEN),   # Sprite palette 9, color index 3.
)


def _word(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def _mov_word(address: int, value: int) -> bytes:
    """Encode 80186 ``mov word [disp16], imm16`` with DS fixed at zero."""

    return b"\xC7\x06" + _word(address) + _word(value)


def _out(port: int, value: int) -> bytes:
    """Encode ``mov al, imm8; out imm8, al``."""

    return bytes((0xB0, value, 0xE6, port))


def tile_payload() -> bytes:
    """Return transparent tile 0 and three original solid packed tiles."""

    # Packed pixels use high nibble then low nibble.  Solid tiles make the
    # compositor result independent of flip state and expose priority alone.
    # Tile 0 is explicitly cleared so empty Screen 2 map cells are deterministic
    # on hardware as well as in a zero-initialized simulator.
    return (
        bytes((0x00,)) * 32
        + bytes((0x22,)) * 32
        + bytes((0x33,)) * 32
        + bytes((0x11,)) * 32
    )


def program() -> bytes:
    """Build the complete raw 80186 program entered at physical F0000h."""

    code = bytearray()

    # Flat IRAM segments, interrupts disabled, display hidden during setup.
    code += b"\xFA"              # cli
    code += b"\xFC"              # cld
    code += b"\x31\xC0"          # xor ax, ax
    code += b"\x8E\xD8"          # mov ds, ax
    code += b"\x8E\xC0"          # mov es, ax
    code += _out(0x14, 0x00)      # LCD off.
    code += _out(0x00, 0x00)      # All display layers off.

    # Preserve timing bits and select Color 4bpp packed mode.
    code += b"\xE4\x60"          # in al, 60h
    code += b"\x24\x1F"          # and al, 1fh
    code += b"\x0C\xE0"          # or al, e0h
    code += b"\xE6\x60"          # out 60h, al

    code += _out(0x07, 0x03)      # Screen 1 map 1800h, Screen 2 map 0000h.
    code += _out(0x01, 0x00)      # Black fallback color.
    code += _out(0x12, 0x00)      # Screen 2 scroll X = 0.
    code += _out(0x13, 0x00)      # Screen 2 scroll Y = 0.

    # Clear the entire Screen 2 map, then install three opaque sample tiles.
    code += b"\x31\xC0"          # xor ax, ax
    code += b"\x31\xFF"          # xor di, di
    code += b"\xB9\x00\x04"      # mov cx, 1024
    code += b"\xF3\xAB"          # rep stosw

    # Install the six descriptors and their three distinct sample colors.
    for address, value in SCREEN2_MAP_WORDS + OAM_WORDS + PALETTE_WORDS:
        code += _mov_word(address, value)

    # Copy the authored 128-byte packed tile payload from physical F0200h to
    # tiles 0..3 at IRAM 4000h.  Keeping it in ROM makes every byte recoverable
    # by the simulator's existing GDMA provenance trace.
    for port, value in (
        (0x40, 0x00),  # Source F0200h, low.
        (0x41, 0x02),  # Source F0200h, middle.
        (0x42, 0x0F),  # Source F0200h, high.
        (0x44, TILE_PAYLOAD_ADDRESS & 0xFF),
        (0x45, TILE_PAYLOAD_ADDRESS >> 8),
        (0x46, TILE_PAYLOAD_SIZE & 0xFF),
        (0x47, TILE_PAYLOAD_SIZE >> 8),
        (0x48, 0x80),  # Start, increment source and destination.
    ):
        code += _out(port, value)

    code += _out(0x04, SPRITE_TABLE_ADDRESS >> 9)
    code += _out(0x05, 0x00)      # First descriptor 0.
    code += _out(0x06, 0x06)      # Six descriptors.
    code += _out(0x00, 0x06)      # Screen 2 + sprites.
    code += _out(0x14, 0x01)      # LCD on.
    code += b"\xEB\xFE"          # jmp $
    return bytes(code)


def footer() -> bytes:
    """Return the authored 16-byte WSC footer before checksum insertion."""

    result = bytearray(16)
    result[0:5] = b"\xEA\x00\x00\x00\xF0"  # jmp far F000:0000
    result[5] = 0x00  # Maintenance byte.
    result[6] = 0x00  # Homebrew/test developer ID.
    result[7] = 0x01  # WonderSwan Color required.
    result[8] = 0x42  # Repository-authored diagnostic ID.
    result[9] = 0x01  # Fixture format version.
    result[10] = 0x00  # 128 KiB ROM.
    result[11] = 0x00  # No save memory.
    result[12] = 0x04  # 16-bit ROM bus, horizontal orientation.
    result[13] = 0x00  # Standard mapper.
    return bytes(result)


def image() -> bytes:
    """Construct the deterministic, checksummed WSC image."""

    result = bytearray(b"\xFF" * ROM_SIZE)
    machine_code = program()
    tiles = tile_payload()

    if PROGRAM_OFFSET + len(machine_code) > TILE_PAYLOAD_OFFSET:
        raise ValueError("sprite-priority program overlaps its tile payload")
    if TILE_PAYLOAD_OFFSET + len(tiles) > MARKER_OFFSET:
        raise ValueError("sprite-priority tiles overlap the identity marker")
    if MARKER_OFFSET + len(MARKER) > FOOTER_OFFSET:
        raise ValueError("sprite-priority marker overlaps the footer")

    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(machine_code)] = machine_code
    result[TILE_PAYLOAD_OFFSET : TILE_PAYLOAD_OFFSET + len(tiles)] = tiles
    result[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] = MARKER
    result[FOOTER_OFFSET:] = footer()
    result[-2:] = _word(sum(result[:-2]) & 0xFFFF)
    return bytes(result)


def generate(output_dir: Path) -> Path:
    """Write the diagnostic under ``output_dir`` and return its path."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / OUTPUT_NAME
    path.write_bytes(image())
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            Path(__file__).resolve().parents[2]
            / "build/sim/color-sprite-priority-probe/roms"
        ),
        help="directory for the generated build-only .wsc diagnostic",
    )
    args = parser.parse_args()
    print(generate(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
