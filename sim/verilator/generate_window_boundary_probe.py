#!/usr/bin/env python3
"""Generate clean-room WSC Screen 2 and sprite-window boundary probes.

The two generated test scenes differ functionally only in Screen 2's
window-region selector; distinct markers and footer IDs bind their identities.
Each image uses repository-authored 80186 bytes, synthetic solid-color tiles,
an original identity marker, and an original cartridge footer.  No assembler,
SDK, firmware, carrier ROM, font, or external graphic is used.

The fixture follows the inclusive window-coordinate contract documented by
WSdev.  Screen 2 is rendered inside the rectangle in one variant and outside
it in the other.  Eight high-priority sprites cross the four edges: four use
the normal (inside) sprite-window region and four set attribute bit 12 to use
the inverse (outside) region.

Pinned review trail (retrieved 2026-07-14):

* WSdev display ports and inclusive coordinate examples, revision 582:
  https://ws.nesdev.org/w/index.php?title=Display/IO_Ports&oldid=582
* WSdev window selection tables, revision 517:
  https://ws.nesdev.org/w/index.php?title=Display/Windows&oldid=517
* WSdev sprite attribute bit 12 and per-sprite selection, revision 507:
  https://ws.nesdev.org/w/index.php?title=Display/Sprites&oldid=507
* ares inclusive window predicates and layer application,
  commit 449b93716fb162632de2fd43bf2eba2064fa43f2:
  https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/ppu/window.cpp#L1-L26
* Mednafen Screen 2/sprite window composition, Debian source 1.32.1+dfsg-3:
  https://sources.debian.org/src/mednafen/1.32.1%2Bdfsg-3/src/wswan/gfx.cpp/#L704-L904

The generated ROMs are build/test artifacts, not redistributable game data.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 128 * 1024
PROGRAM_OFFSET = 0x10000       # Physical F0000h in a 128 KiB image.
TILE_PAYLOAD_OFFSET = 0x10300  # Physical F0300h.
MARKER_OFFSET = 0x10500
FOOTER_OFFSET = ROM_SIZE - 16

INSIDE = "inside"
OUTSIDE = "outside"
VARIANTS = (INSIDE, OUTSIDE)
OUTPUT_NAMES = {
    INSIDE: "wsc_window_inside_probe.wsc",
    OUTSIDE: "wsc_window_outside_probe.wsc",
}
GAME_IDS = {INSIDE: 0x46, OUTSIDE: 0x47}

WINDOW_LEFT = 64
WINDOW_TOP = 40
WINDOW_RIGHT = 159
WINDOW_BOTTOM = 103

SCREEN2_MAP_ADDRESS = 0x0000
SPRITE_TABLE_ADDRESS = 0x1000
TILE_PAYLOAD_ADDRESS = 0x4000
TILE_PAYLOAD_SIZE = 4 * 32

# Tiles 1/2 are the normal/inverse sprite-window colors. Tile 3 fills Screen 2.
INSIDE_SPRITE_TILE = 1
OUTSIDE_SPRITE_TILE = 2
SCREEN2_TILE = 3

# Screen 2 global window mode differs by variant.  Both keep Screen 2, sprites,
# and the sprite window enabled.  Bit 4 selects Screen 2 outside when set.
DISPLAY_CONTROL = {
    INSIDE: 0x2E,
    OUTSIDE: 0x3E,
}

# Every sprite straddles exactly one window edge.  Safe coordinates along the
# other axis keep all eight descriptors disjoint.  The first four descriptors
# select the inside region; the last four set bit 12 and select the outside.
INSIDE_SPRITES = (
    (63, 48, "left"),
    (153, 48, "right"),
    (80, 39, "top"),
    (80, 97, "bottom"),
)
OUTSIDE_SPRITES = (
    (63, 64, "left"),
    (153, 64, "right"),
    (104, 39, "top"),
    (104, 97, "bottom"),
)

# Attribute bit 13 puts each diagnostic sprite above Screen 2.  Palette fields
# 0/1 select Color sprite palettes 8/9; bit 12 inverts the window region.
INSIDE_SPRITE_ATTRIBUTE = 0x2000 | INSIDE_SPRITE_TILE
OUTSIDE_SPRITE_ATTRIBUTE = 0x3000 | 0x0200 | OUTSIDE_SPRITE_TILE

PALETTE_WORDS = (
    (0xFE00, 0x00F),  # Backdrop: blue.
    (0xFE06, 0xF00),  # Screen palette 0, index 3: red.
    (0xFF02, 0x0F0),  # Sprite palette 8, index 1: green.
    (0xFF24, 0xF0F),  # Sprite palette 9, index 2: magenta.
)


def _validate_variant(variant: str) -> None:
    if variant not in VARIANTS:
        raise ValueError(f"unsupported window-boundary variant: {variant!r}")


def _word(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def _mov_word(address: int, value: int) -> bytes:
    """Encode 80186 ``mov word [disp16], imm16`` with DS fixed at zero."""

    return b"\xC7\x06" + _word(address) + _word(value)


def _out(port: int, value: int) -> bytes:
    """Encode ``mov al, imm8; out imm8, al``."""

    return bytes((0xB0, value, 0xE6, port))


def marker(variant: str) -> bytes:
    _validate_variant(variant)
    return f"SWANSONG-WSC-WINDOW-{variant.upper()}-V1\0".encode("ascii")


def tile_payload() -> bytes:
    """Return four original solid packed-color tiles."""

    # Tile zero is explicitly transparent.  Solid tiles make every edge sample
    # independent of flip state while retaining distinct layer identities.
    return b"".join(bytes((index * 0x11,)) * 32 for index in range(4))


def oam_words() -> tuple[tuple[int, int], ...]:
    """Return the exact eight authored sprite descriptors."""

    result: list[tuple[int, int]] = []
    for index, (x, y, _edge) in enumerate(INSIDE_SPRITES + OUTSIDE_SPRITES):
        attribute = (
            INSIDE_SPRITE_ATTRIBUTE
            if index < len(INSIDE_SPRITES)
            else OUTSIDE_SPRITE_ATTRIBUTE
        )
        address = SPRITE_TABLE_ADDRESS + index * 4
        result.extend(((address, attribute), (address + 2, (x << 8) | y)))
    return tuple(result)


def program(variant: str) -> bytes:
    """Build the complete raw 80186 program entered at physical F0000h."""

    _validate_variant(variant)
    code = bytearray()

    # Flat IRAM segments, interrupts disabled, display hidden during setup.
    code += b"\xFA\xFC"          # cli; cld
    code += b"\x31\xC0"          # xor ax, ax
    code += b"\x8E\xD8\x8E\xC0"  # mov ds, ax; mov es, ax
    code += _out(0x14, 0x00)       # LCD off.
    code += _out(0x00, 0x00)       # All layers off.

    # Preserve timing bits and select WSC 4bpp packed mode.
    code += b"\xE4\x60\x24\x1F\x0C\xE0\xE6\x60"
    code += _out(0x07, 0x03)       # Screen 2 map 0000h; Screen 1 map 1800h.
    code += _out(0x01, 0x00)       # Backdrop palette 0, index 0.
    code += _out(0x12, 0x00)       # Screen 2 scroll X.
    code += _out(0x13, 0x00)       # Screen 2 scroll Y.

    # The 32x32 Screen 2 map is a solid field of tile 3.
    code += b"\xB8\x03\x00"      # mov ax, 3
    code += b"\x31\xFF"          # xor di, di
    code += b"\xB9\x00\x04"      # mov cx, 1024
    code += b"\xF3\xAB"          # rep stosw

    for address, value in oam_words() + PALETTE_WORDS:
        code += _mov_word(address, value)

    # Both hardware windows use the same rectangle so layer-specific outcomes
    # can be compared at identical inclusive coordinates.
    for port, value in (
        (0x08, WINDOW_LEFT),
        (0x09, WINDOW_TOP),
        (0x0A, WINDOW_RIGHT),
        (0x0B, WINDOW_BOTTOM),
        (0x0C, WINDOW_LEFT),
        (0x0D, WINDOW_TOP),
        (0x0E, WINDOW_RIGHT),
        (0x0F, WINDOW_BOTTOM),
    ):
        code += _out(port, value)

    # Copy all four tiles from physical F0300h into Color tile memory.
    for port, value in (
        (0x40, 0x00),
        (0x41, 0x03),
        (0x42, 0x0F),
        (0x44, TILE_PAYLOAD_ADDRESS & 0xFF),
        (0x45, TILE_PAYLOAD_ADDRESS >> 8),
        (0x46, TILE_PAYLOAD_SIZE & 0xFF),
        (0x47, TILE_PAYLOAD_SIZE >> 8),
        (0x48, 0x80),
    ):
        code += _out(port, value)

    code += _out(0x04, SPRITE_TABLE_ADDRESS >> 9)
    code += _out(0x05, 0x00)
    code += _out(0x06, 0x08)
    code += _out(0x00, DISPLAY_CONTROL[variant])
    code += _out(0x14, 0x01)
    code += b"\xEB\xFE"          # jmp $
    return bytes(code)


def footer(variant: str) -> bytes:
    """Return the authored 16-byte WSC footer before checksum insertion."""

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
    """Construct one deterministic, checksummed WSC image."""

    _validate_variant(variant)
    result = bytearray(b"\xFF" * ROM_SIZE)
    machine_code = program(variant)
    tiles = tile_payload()
    identity = marker(variant)

    if PROGRAM_OFFSET + len(machine_code) > TILE_PAYLOAD_OFFSET:
        raise ValueError("window-boundary program overlaps its tile payload")
    if TILE_PAYLOAD_OFFSET + len(tiles) > MARKER_OFFSET:
        raise ValueError("window-boundary tiles overlap the identity marker")
    if MARKER_OFFSET + len(identity) > FOOTER_OFFSET:
        raise ValueError("window-boundary marker overlaps the footer")

    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(machine_code)] = machine_code
    result[TILE_PAYLOAD_OFFSET : TILE_PAYLOAD_OFFSET + len(tiles)] = tiles
    result[MARKER_OFFSET : MARKER_OFFSET + len(identity)] = identity
    result[FOOTER_OFFSET:] = footer(variant)
    result[-2:] = _word(sum(result[:-2]) & 0xFFFF)
    return bytes(result)


def generate(output_dir: Path) -> tuple[Path, Path]:
    """Write both variants and return their paths in inside/outside order."""

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
        default=Path(__file__).resolve().parents[2] / "build/sim/window-boundary-probe/roms",
        help="directory for the generated build-only .wsc diagnostics",
    )
    args = parser.parse_args()
    for path in generate(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
