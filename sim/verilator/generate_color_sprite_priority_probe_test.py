#!/usr/bin/env python3
"""Structural tests for the clean-room WSC Color sprite-priority probe."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import generate_color_sprite_priority_probe as probe


EXPECTED_SHA256 = "dd2493e9f936ce30df72bcee70f2e705bb92bc10bcfb749b96da6251aa03e450"
EXPECTED_PROGRAM_SIZE = 211
EXPECTED_MARKER = b"SWANSONG-WSC-COLOR-SPRITE-PRIORITY-V1\0"
EXPECTED_OAM_WORDS = (
    (0x1000, 0x0001),
    (0x1002, 0x4040),
    (0x1004, 0x2202),
    (0x1006, 0x6040),
    (0x1008, 0x0001),
    (0x100A, 0x7040),
    (0x100C, 0x2202),
    (0x100E, 0x7040),
    (0x1010, 0x0001),
    (0x1012, 0x5040),
    (0x1014, 0x2202),
    (0x1016, 0x5040),
)
EXPECTED_SCREEN2_MAP_WORDS = (
    (0x0210, 0x0003),
    (0x0214, 0x0003),
    (0x0218, 0x0003),
)
EXPECTED_PALETTE_WORDS = (
    (0xFE02, 0x00F),
    (0xFF04, 0xF00),
    (0xFF26, 0x0F0),
)
EXPECTED_RGB888 = {
    "screen2": (0, 0, 255),
    "earlier_low": (255, 0, 0),
    "later_high": (0, 255, 0),
}


def _direct_word_writes(machine_code: bytes) -> dict[int, int]:
    """Independently collect C7 06 [disp16], imm16 writes."""

    writes: dict[int, int] = {}
    offset = 0
    while True:
        offset = machine_code.find(b"\xC7\x06", offset)
        if offset < 0:
            return writes
        assert offset + 6 <= len(machine_code)
        address = int.from_bytes(machine_code[offset + 2 : offset + 4], "little")
        value = int.from_bytes(machine_code[offset + 4 : offset + 6], "little")
        assert address not in writes, f"duplicate direct write to {address:04x}h"
        writes[address] = value
        offset += 6


def _decode_packed(tile: bytes) -> tuple[tuple[int, ...], ...]:
    assert len(tile) == 32
    rows = []
    for start in range(0, 32, 4):
        row = []
        for value in tile[start : start + 4]:
            row.extend((value >> 4, value & 0x0F))
        rows.append(tuple(row))
    return tuple(rows)


def _assert_footer(rom: bytes) -> None:
    footer = rom[-16:]
    assert footer[:5] == b"\xEA\x00\x00\x00\xF0"
    assert footer[5:14] == b"\x00\x00\x01\x42\x01\x00\x00\x04\x00"
    assert int.from_bytes(footer[14:16], "little") == sum(rom[:-2]) & 0xFFFF


def _assert_program(rom: bytes) -> None:
    machine_code = probe.program()
    assert len(machine_code) == EXPECTED_PROGRAM_SIZE
    assert rom[0x10000 : 0x10000 + len(machine_code)] == machine_code
    assert machine_code.startswith(
        b"\xFA\xFC\x31\xC0\x8E\xD8\x8E\xC0\xB0\x00\xE6\x14\xB0\x00\xE6\x00"
    )
    assert machine_code.endswith(
        b"\xB0\x06\xE6\x00\xB0\x01\xE6\x14\xEB\xFE"
    )
    assert machine_code.count(b"\xE4\x60\x24\x1F\x0C\xE0\xE6\x60") == 1
    assert machine_code.count(b"\x31\xC0\x31\xFF\xB9\x00\x04\xF3\xAB") == 1

    writes = _direct_word_writes(machine_code)
    expected_writes = dict(
        EXPECTED_SCREEN2_MAP_WORDS + EXPECTED_OAM_WORDS + EXPECTED_PALETTE_WORDS
    )
    assert writes == expected_writes

    dma_sequence = b"".join(
        bytes((0xB0, value, 0xE6, port))
        for port, value in (
            (0x40, 0x00),
            (0x41, 0x02),
            (0x42, 0x0F),
            (0x44, 0x00),
            (0x45, 0x40),
            (0x46, 0x80),
            (0x47, 0x00),
            (0x48, 0x80),
        )
    )
    assert machine_code.count(dma_sequence) == 1
    assert machine_code.count(b"\xB0\x08\xE6\x04") == 1
    assert machine_code.count(b"\xB0\x00\xE6\x05") == 1
    assert machine_code.count(b"\xB0\x06\xE6\x06") == 1


def _assert_tiles(rom: bytes) -> None:
    payload = rom[0x10200 : 0x10280]
    assert len(payload) == 128
    expected_indices = (0, 2, 3, 1)
    for index, color_index in enumerate(expected_indices):
        tile = payload[index * 32 : (index + 1) * 32]
        assert _decode_packed(tile) == ((color_index,) * 8,) * 8


def _assert_priority_oracle() -> None:
    panels = (
        (64, EXPECTED_RGB888["screen2"]),
        (80, EXPECTED_RGB888["later_high"]),
        (96, EXPECTED_RGB888["later_high"]),
        (112, EXPECTED_RGB888["earlier_low"]),
    )
    expected_pixels = {
        (x, y): color
        for start_x, color in panels
        for y in range(64, 72)
        for x in range(start_x, start_x + 8)
    }
    assert len(expected_pixels) == 4 * 64
    assert {expected_pixels[(x, 64)] for x in (64, 80, 96, 112)} == {
        (0, 0, 255),
        (0, 255, 0),
        (255, 0, 0),
    }

    # The known divergent Color composition instead resolves every one of
    # these pixels to the opaque Screen 2 blue.  Keep that non-oracle result
    # explicit so a frame verifier cannot accidentally bless it.
    correct_critical_pixels = {
        point: color
        for point, color in expected_pixels.items()
        if 80 <= point[0] < 88
    }
    divergent_critical_pixels = {
        (x, y): EXPECTED_RGB888["screen2"]
        for y in range(64, 72)
        for x in range(80, 88)
    }
    assert set(correct_critical_pixels.values()) == {(0, 255, 0)}
    assert set(divergent_critical_pixels.values()) == {(0, 0, 255)}
    assert correct_critical_pixels != divergent_critical_pixels


def _assert_image(rom: bytes) -> None:
    assert len(rom) == 128 * 1024
    assert rom[0x10400 : 0x10400 + len(EXPECTED_MARKER)] == EXPECTED_MARKER
    assert rom.count(EXPECTED_MARKER) == 1
    _assert_footer(rom)
    _assert_program(rom)
    _assert_tiles(rom)
    assert hashlib.sha256(rom).hexdigest() == EXPECTED_SHA256


def main() -> int:
    # In a 128 KiB image, file offset 10200h maps to physical F0200h.
    assert probe.TILE_PAYLOAD_OFFSET == probe.ROM_SIZE - 0x100000 + 0xF0200
    assert probe.SCREEN2_MAP_WORDS == EXPECTED_SCREEN2_MAP_WORDS
    assert probe.SPRITE_POSITION_WORD == 0x5040

    with tempfile.TemporaryDirectory(
        prefix="wsc-color-sprite-priority-test-"
    ) as first_name:
        with tempfile.TemporaryDirectory(
            prefix="wsc-color-sprite-priority-test-"
        ) as second_name:
            first_path = probe.generate(Path(first_name))
            second_path = probe.generate(Path(second_name))
            assert first_path.name == "wsc_color_sprite_priority_probe.wsc"
            assert second_path.name == first_path.name
            first = first_path.read_bytes()
            second = second_path.read_bytes()
            assert first == second == probe.image()
            _assert_image(first)

    _assert_priority_oracle()
    print(
        "PASS generated WSC Color sprite-priority probe "
        f"sha256={EXPECTED_SHA256} controls=blue,green,green,red"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
