#!/usr/bin/env python3
"""Focused structural tests for the generated WSC 4bpp probes."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import generate_4bpp_probe as probe


EXPECTED_PIXELS = (
    (1, 2, 3, 4, 5, 6, 7, 8),
    (8, 7, 6, 5, 4, 3, 2, 1),
    (1, 1, 2, 2, 3, 3, 4, 4),
    (5, 5, 6, 6, 7, 7, 8, 8),
    (9, 10, 11, 12, 13, 14, 15, 1),
    (15, 14, 13, 12, 11, 10, 9, 8),
    (2, 4, 6, 8, 10, 12, 14, 1),
    (1, 3, 5, 7, 9, 11, 13, 15),
)

EXPECTED_PALETTE = (
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

EXPECTED_MAP_ENTRIES = (
    (0x1A14, 0x0001),
    (0x1A16, 0x4001),
    (0x1A18, 0x8001),
    (0x1A1A, 0xC001),
)

EXPECTED_SHA256 = {
    # These values pin the complete deterministic fixture identity, including
    # the authored program, payload, marker, footer, and checksum.
    probe.PLANAR: "31731d330004bcb54338096654c7f4bb75c2ba8d186e139f8a4724f5d700bd42",
    probe.PACKED: "9525d1de59e902745f0f7c8acd2229235bd6343ddedc17acb03f62411be28959",
}


def _direct_word_writes(machine_code: bytes) -> dict[int, int]:
    """Independently collect C7 06 [disp16], imm16 writes from the program."""

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


def _written_bytes(writes: dict[int, int], start: int, size: int) -> bytes:
    result = bytearray()
    for address in range(start, start + size, 2):
        assert address in writes, f"missing direct write to {address:04x}h"
        result += writes[address].to_bytes(2, "little")
    return bytes(result)


def _decode_planar(tile: bytes) -> tuple[tuple[int, ...], ...]:
    rows = []
    for row_start in range(0, len(tile), 4):
        planes = tile[row_start : row_start + 4]
        rows.append(
            tuple(
                sum(((planes[plane] >> (7 - x)) & 1) << plane for plane in range(4))
                for x in range(8)
            )
        )
    return tuple(rows)


def _decode_packed(tile: bytes) -> tuple[tuple[int, ...], ...]:
    rows = []
    for row_start in range(0, len(tile), 4):
        row = []
        for value in tile[row_start : row_start + 4]:
            row.extend((value >> 4, value & 0x0F))
        rows.append(tuple(row))
    return tuple(rows)


def _assert_footer(rom: bytes, variant: str) -> None:
    footer = rom[-16:]
    assert footer[:5] == b"\xEA\x00\x00\x00\xF0"
    assert footer[5:8] == b"\x00\x00\x01"
    assert footer[8] == {probe.PLANAR: 0x40, probe.PACKED: 0x41}[variant]
    assert footer[9:14] == b"\x01\x00\x00\x04\x00"
    assert int.from_bytes(footer[14:16], "little") == sum(rom[:-2]) & 0xFFFF


def _assert_program(rom: bytes, variant: str) -> None:
    machine_code = probe.program(variant)
    assert rom[probe.PROGRAM_OFFSET : probe.PROGRAM_OFFSET + len(machine_code)] == machine_code
    assert machine_code.endswith(b"\xB0\x01\xE6\x00\xB0\x01\xE6\x14\xEB\xFE")

    mode = {probe.PLANAR: 0xC0, probe.PACKED: 0xE0}[variant]
    mode_sequence = b"\xE4\x60\x24\x1F\x0C" + bytes((mode,)) + b"\xE6\x60"
    assert machine_code.count(mode_sequence) == 1
    assert machine_code.count(b"\xB0\x03\xE6\x07") == 1
    assert machine_code.count(b"\x31\xC0\xBF\x00\x18\xB9\x00\x04\xF3\xAB") == 1
    assert machine_code.count(b"\xE6\x10\xE6\x11") == 1

    dma_sequence = b"".join(
        bytes((0xB0, value, 0xE6, port))
        for port, value in (
            (0x40, 0x00),
            (0x41, 0x01),
            (0x42, 0x0F),
            (0x44, 0x20),
            (0x45, 0x40),
            (0x46, 0x20),
            (0x47, 0x00),
            (0x48, 0x80),
        )
    )
    assert machine_code.count(dma_sequence) == 1

    writes = _direct_word_writes(machine_code)
    assert len(writes) == 20

    assert probe.MAP_ENTRIES == EXPECTED_MAP_ENTRIES
    assert tuple(
        (address, writes[address]) for address, _ in EXPECTED_MAP_ENTRIES
    ) == EXPECTED_MAP_ENTRIES

    palette = _written_bytes(writes, 0xFE00, 32)
    assert tuple(
        int.from_bytes(palette[offset : offset + 2], "little")
        for offset in range(0, len(palette), 2)
    ) == EXPECTED_PALETTE

    tile = rom[probe.PATTERN_OFFSET : probe.PATTERN_OFFSET + 32]
    decoded = _decode_planar(tile) if variant == probe.PLANAR else _decode_packed(tile)
    assert decoded == EXPECTED_PIXELS


def _assert_image(rom: bytes, variant: str) -> None:
    assert len(rom) == 128 * 1024
    identity = f"SWANSONG-WSC-4BPP-{variant.upper()}-V1\0".encode("ascii")
    assert rom[0x10400 : 0x10400 + len(identity)] == identity
    assert rom.count(identity) == 1
    _assert_footer(rom, variant)
    _assert_program(rom, variant)
    assert hashlib.sha256(rom).hexdigest() == EXPECTED_SHA256[variant]


def main() -> int:
    # A 128 KiB image occupies physical E0000h-FFFFFh. Bind the GDMA source
    # address F0100h to the exact file byte where the format payload is stored.
    assert probe.PATTERN_OFFSET == probe.ROM_SIZE - 0x100000 + 0xF0100

    with tempfile.TemporaryDirectory(prefix="wsc-4bpp-probe-test-") as first_dir_name:
        with tempfile.TemporaryDirectory(prefix="wsc-4bpp-probe-test-") as second_dir_name:
            first_paths = probe.generate(Path(first_dir_name))
            second_paths = probe.generate(Path(second_dir_name))

            assert tuple(path.name for path in first_paths) == (
                "wsc_4bpp_planar_probe.wsc",
                "wsc_4bpp_packed_probe.wsc",
            )
            images = {}
            for variant, first_path, second_path in zip(
                probe.VARIANTS, first_paths, second_paths
            ):
                first = first_path.read_bytes()
                second = second_path.read_bytes()
                assert first == second
                assert first == probe.image(variant)
                _assert_image(first, variant)
                images[variant] = first

            assert images[probe.PLANAR] != images[probe.PACKED]

    for function in (probe.tile_bytes, probe.marker, probe.program, probe.footer, probe.image):
        try:
            function("not-a-format")
        except ValueError:
            pass
        else:
            raise AssertionError(f"{function.__name__} accepted an invalid variant")

    print("PASS: generated WSC planar and packed 4bpp probes are deterministic and valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
