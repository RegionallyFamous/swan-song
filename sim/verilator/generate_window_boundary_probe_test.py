#!/usr/bin/env python3
"""Structural and determinism tests for the clean-room window probes."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import generate_window_boundary_probe as probe


EXPECTED_SHA256 = {
    probe.INSIDE: "34eec5463b9eb3f9d0b1c030c2d6d23e710f0abed7ec6188a3700352ccad03cd",
    probe.OUTSIDE: "ff1f0132454a8e192f09d80e53272a9f7468574dd811bbf5e1b602db2f017a75",
}
EXPECTED_PROGRAM_SIZE = 256
EXPECTED_PALETTE_WORDS = (
    (0xFE00, 0x00F),
    (0xFE06, 0xF00),
    (0xFF02, 0x0F0),
    (0xFF24, 0xF0F),
)
EXPECTED_OAM_WORDS = (
    (0x1000, 0x2001), (0x1002, 0x3F30),
    (0x1004, 0x2001), (0x1006, 0x9930),
    (0x1008, 0x2001), (0x100A, 0x5027),
    (0x100C, 0x2001), (0x100E, 0x5061),
    (0x1010, 0x3202), (0x1012, 0x3F40),
    (0x1014, 0x3202), (0x1016, 0x9940),
    (0x1018, 0x3202), (0x101A, 0x6827),
    (0x101C, 0x3202), (0x101E, 0x6861),
)


def _direct_word_writes(machine_code: bytes) -> dict[int, int]:
    writes: dict[int, int] = {}
    offset = 0
    while True:
        offset = machine_code.find(b"\xC7\x06", offset)
        if offset < 0:
            return writes
        assert offset + 6 <= len(machine_code)
        address = int.from_bytes(machine_code[offset + 2 : offset + 4], "little")
        value = int.from_bytes(machine_code[offset + 4 : offset + 6], "little")
        assert address not in writes
        writes[address] = value
        offset += 6


def _port_writes(machine_code: bytes) -> list[tuple[int, int]]:
    result = []
    for offset in range(len(machine_code) - 3):
        if machine_code[offset] == 0xB0 and machine_code[offset + 2] == 0xE6:
            result.append((machine_code[offset + 3], machine_code[offset + 1]))
    return result


def _assert_footer(rom: bytes, variant: str) -> None:
    footer = rom[-16:]
    assert footer[:5] == b"\xEA\x00\x00\x00\xF0"
    assert footer[5:8] == b"\x00\x00\x01"
    assert footer[8] == {probe.INSIDE: 0x46, probe.OUTSIDE: 0x47}[variant]
    assert footer[9:14] == b"\x01\x00\x00\x04\x00"
    assert int.from_bytes(footer[-2:], "little") == sum(rom[:-2]) & 0xFFFF


def _assert_program(rom: bytes, variant: str) -> None:
    code = probe.program(variant)
    assert len(code) == EXPECTED_PROGRAM_SIZE
    assert rom[probe.PROGRAM_OFFSET : probe.PROGRAM_OFFSET + len(code)] == code
    assert code.startswith(b"\xFA\xFC\x31\xC0\x8E\xD8\x8E\xC0")
    assert code.endswith(
        b"\xB0" + bytes((probe.DISPLAY_CONTROL[variant],))
        + b"\xE6\x00\xB0\x01\xE6\x14\xEB\xFE"
    )
    assert code.count(b"\xE4\x60\x24\x1F\x0C\xE0\xE6\x60") == 1
    assert code.count(b"\xB8\x03\x00\x31\xFF\xB9\x00\x04\xF3\xAB") == 1

    writes = _direct_word_writes(code)
    assert writes == dict(EXPECTED_OAM_WORDS + EXPECTED_PALETTE_WORDS)
    assert probe.oam_words() == EXPECTED_OAM_WORDS

    ports = _port_writes(code)
    for port, value in (
        (0x08, 64), (0x09, 40), (0x0A, 159), (0x0B, 103),
        (0x0C, 64), (0x0D, 40), (0x0E, 159), (0x0F, 103),
    ):
        assert ports.count((port, value)) == 1
    assert ports.count((0x04, 0x08)) == 1
    assert ports.count((0x05, 0x00)) == 1
    assert ports.count((0x06, 0x08)) == 1
    assert ports.count((0x00, probe.DISPLAY_CONTROL[variant])) == 1

    dma = ((0x40, 0), (0x41, 3), (0x42, 15), (0x44, 0),
           (0x45, 64), (0x46, 128), (0x47, 0), (0x48, 128))
    for port, value in dma:
        assert ports.count((port, value)) == 1


def _assert_image(rom: bytes, variant: str) -> None:
    assert len(rom) == probe.ROM_SIZE
    identity = f"SWANSONG-WSC-WINDOW-{variant.upper()}-V1\0".encode("ascii")
    assert rom[probe.MARKER_OFFSET : probe.MARKER_OFFSET + len(identity)] == identity
    assert rom.count(identity) == 1
    assert rom[probe.TILE_PAYLOAD_OFFSET : probe.TILE_PAYLOAD_OFFSET + 128] == (
        b"\x00" * 32 + b"\x11" * 32 + b"\x22" * 32 + b"\x33" * 32
    )
    _assert_footer(rom, variant)
    _assert_program(rom, variant)
    assert hashlib.sha256(rom).hexdigest() == EXPECTED_SHA256[variant]


def main() -> int:
    assert probe.TILE_PAYLOAD_OFFSET == probe.ROM_SIZE - 0x100000 + 0xF0300
    assert probe.WINDOW_RIGHT - probe.WINDOW_LEFT + 1 == 96
    assert probe.WINDOW_BOTTOM - probe.WINDOW_TOP + 1 == 64
    assert probe.INSIDE_SPRITE_ATTRIBUTE & 0x1000 == 0
    assert probe.OUTSIDE_SPRITE_ATTRIBUTE & 0x1000
    assert probe.INSIDE_SPRITE_ATTRIBUTE & 0x2000
    assert probe.OUTSIDE_SPRITE_ATTRIBUTE & 0x2000

    with tempfile.TemporaryDirectory(prefix="wsc-window-first-") as first_name:
        with tempfile.TemporaryDirectory(prefix="wsc-window-second-") as second_name:
            first_paths = probe.generate(Path(first_name))
            second_paths = probe.generate(Path(second_name))
            assert tuple(path.name for path in first_paths) == (
                "wsc_window_inside_probe.wsc",
                "wsc_window_outside_probe.wsc",
            )
            for variant, first_path, second_path in zip(
                probe.VARIANTS, first_paths, second_paths
            ):
                first = first_path.read_bytes()
                assert first == second_path.read_bytes() == probe.image(variant)
                _assert_image(first, variant)
            assert first_paths[0].read_bytes() != first_paths[1].read_bytes()

    for function in (probe.marker, probe.program, probe.footer, probe.image):
        try:
            function("not-a-window-mode")
        except ValueError:
            pass
        else:
            raise AssertionError(f"{function.__name__} accepted an invalid variant")

    print("PASS generated clean-room WSC inside/outside window-boundary probes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
