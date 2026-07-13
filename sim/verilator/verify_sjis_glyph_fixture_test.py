#!/usr/bin/env python3
"""Focused failure tests for the Shift-JIS fixture verifier."""

from __future__ import annotations

import tempfile
from pathlib import Path

from verify_sjis_glyph_fixture import (
    BDF_SUBSET,
    GLYPHS,
    MAP_WRITE_IDS,
    MAP_WRITE_ORIGIN,
    PACKED,
    PACKED_OFFSET,
    PACKED_PHYSICAL,
    expected_frame,
    verify_frame,
    verify_gdma,
    verify_map_writes,
    verify_rom,
)
from verify_trace import FIELDS_V5


ROOT = Path(__file__).resolve().parents[2]
ROM = ROOT / "testroms/swan-song/sjis_glyph_provenance/sjis_glyph_provenance.wsc"


def must_fail(function, *args) -> None:
    try:
        function(*args)
    except ValueError:
        return
    raise AssertionError(f"invalid fixture passed {function.__name__}")


def mem_row(**values: object) -> dict[str, str]:
    row = {field: "" for field in FIELDS_V5}
    row.update({field: str(value) for field, value in values.items()})
    return row


def gdma_rows() -> list[dict[str, str]]:
    rows = []
    cycle = 100
    for word_index in range(len(PACKED) // 2):
        value = PACKED[word_index * 2] | (PACKED[word_index * 2 + 1] << 8)
        source_offset = PACKED_OFFSET + word_index * 2
        destination = 0x2010 + word_index * 2
        rows.append(
            mem_row(
                cycle=cycle,
                event="mem",
                address=PACKED_PHYSICAL + word_index * 2,
                value=value,
                initiator="gdma",
                access="read",
                byte_enable=3,
                space="cart_rom_linear",
                mapped_offset=source_offset,
                origin_status="not_applicable",
            )
        )
        rows.append(
            mem_row(
                cycle=cycle + 1,
                event="mem",
                address=destination,
                value=value,
                initiator="gdma",
                access="write",
                byte_enable=3,
                space="iram",
                mapped_offset=destination,
                origin_status="not_applicable",
            )
        )
        cycle += 2
    return rows


def map_rows() -> list[dict[str, str]]:
    return [
        mem_row(
            cycle=500 + index,
            event="mem",
            address=0x1A14 + index * 2,
            value=index + 1,
            initiator="cpu",
            access="write",
            byte_enable=3,
            space="iram",
            mapped_offset=0x1A14 + index * 2,
            instruction_id=MAP_WRITE_IDS[index],
            origin_pc=MAP_WRITE_ORIGIN,
            origin_status="exact",
        )
        for index in range(len(GLYPHS))
    ]


def main() -> None:
    verify_rom(ROM)
    valid_gdma = gdma_rows()
    verify_gdma(valid_gdma)
    valid_maps = map_rows()
    verify_map_writes(valid_maps)

    wrong_source = [dict(row) for row in valid_gdma]
    wrong_source[0]["mapped_offset"] = str(PACKED_OFFSET + 2)
    must_fail(verify_gdma, wrong_source)

    wrong_map_id = [dict(row) for row in valid_maps]
    wrong_map_id[0]["instruction_id"] = str(MAP_WRITE_IDS[0] + 1)
    must_fail(verify_map_writes, wrong_map_id)

    with tempfile.TemporaryDirectory(prefix="swansong-sjis-verifier-") as directory:
        root = Path(directory)
        frame = root / "frame.rgb"
        frame.write_bytes(expected_frame())
        verify_frame(frame)
        damaged_frame = bytearray(frame.read_bytes())
        damaged_frame[0] ^= 0xFF
        frame.write_bytes(damaged_frame)
        must_fail(verify_frame, frame)

        rom = root / "fixture.wsc"
        bdf = root / BDF_SUBSET
        rom.write_bytes(ROM.read_bytes())
        bdf.write_bytes((ROM.parent / BDF_SUBSET).read_bytes())
        verify_rom(rom)
        bdf.write_bytes(bdf.read_bytes() + b"\n")
        must_fail(verify_rom, rom)

        damaged_rom = bytearray(ROM.read_bytes())
        damaged_rom[PACKED_OFFSET] ^= 1
        rom.write_bytes(damaged_rom)
        must_fail(verify_rom, rom)

    print("PASS Shift-JIS glyph fixture verifier failures")


if __name__ == "__main__":
    main()
