#!/usr/bin/env python3
"""Focused failure tests for the Shift-JIS fixture verifier."""

from __future__ import annotations

import csv
import hashlib
import tempfile
from pathlib import Path

from report_glyphs import (
    OUTPUT_FIELDS as GLYPH_REPORT_FIELDS,
    encode_png,
    render_contact_sheet,
)
from verify_sjis_glyph_fixture import (
    BDF_SUBSET,
    GLYPHS,
    MAP_WRITE_IDS,
    MAP_WRITE_ORIGIN,
    PACKED,
    PACKED_OFFSET,
    PACKED_PHYSICAL,
    expected_frame,
    glyph_bitmap,
    verify_frame,
    verify_gdma,
    verify_glyph_report,
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


def glyph_report_rows() -> list[dict[str, str]]:
    rows = [{field: "" for field in GLYPH_REPORT_FIELDS} for _ in range(592)]
    blank = "/".join(("00000000",) * 8)
    blank_fingerprint = hashlib.sha256(blank.encode("ascii")).hexdigest()
    for index, row in enumerate(rows):
        row.update(
            {
                "epoch_index": str(index),
                "layer": "screen1",
                "tile_index": "0",
                "tile_bank_enabled": "1",
                "map_address": "0x0000",
                "map_value": "0x0000",
                "map_x": "0",
                "map_y": "0",
                "palette": "0",
                "bpp": "2",
                "packed": "0",
                "hflip": "0",
                "vflip": "0",
                "occurrence_count": "1",
                "complete": "1",
                "collision": "0",
                "mixed": "0",
                "confidence": "exact",
                "bitmap_rows": blank,
                "bitmap_fingerprint": blank_fingerprint,
            }
        )
    for index in [0, *range(559, 592)]:
        rows[index]["confidence"] = "incomplete"
    rows[32]["occurrence_count"] = "2"
    for index, glyph in enumerate(GLYPHS):
        bitmap = glyph_bitmap(glyph)
        iram_start = 0x2010 + index * 16
        source_start = PACKED_OFFSET + index * 16
        rows[197 + index].update(
            {
                "layer": "screen1",
                "tile_index": str(index + 1),
                "tile_bank_enabled": "1",
                "map_address": f"0x{0x1A14 + index * 2:04x}",
                "map_value": f"0x{index + 1:04x}",
                "map_x": str(10 + index),
                "map_y": "8",
                "palette": "0",
                "bpp": "2",
                "packed": "0",
                "hflip": "0",
                "vflip": "0",
                "occurrence_count": "2",
                "occurrence_cycles": "100-107;200-207",
                "first_cycle": "100",
                "last_cycle": "207",
                "rows_observed": "0,1,2,3,4,5,6,7",
                "complete": "1",
                "collision": "0",
                "mixed": "0",
                "bitmap_rows": bitmap,
                "bitmap_fingerprint": hashlib.sha256(bitmap.encode("ascii")).hexdigest(),
                "coverage_statuses": "complete_from_reset",
                "map_scoreboard_statuses": "match",
                "row_scoreboard_statuses": "match",
                "map_writer_summaries": "cpu_exact",
                "map_writer_initiators": "cpu",
                "map_writer_instruction_ids": str(MAP_WRITE_IDS[index]),
                "map_writer_origin_pcs": f"0x{MAP_WRITE_ORIGIN:05x}",
                "map_write_cycle_range": "90",
                "row_writer_summaries": "gdma",
                "row_writer_initiators": "gdma",
                "row_write_cycle_range": "80",
                "tile_iram_ranges": f"0x{iram_start:04x}-0x{iram_start + 15:04x}",
                "row_source_summaries": "gdma_rom",
                "row_source_ranges": (
                    f"cart_rom_linear:0x{source_start:06x}-0x{source_start + 15:06x}"
                ),
                "row_source_read_cycle_range": "70",
            }
        )
    return rows


def write_glyph_report(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=GLYPH_REPORT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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

        report = root / "glyph-epochs.csv"
        contact = root / "glyph-contact.png"
        valid_report = glyph_report_rows()
        write_glyph_report(report, valid_report)
        contact.write_bytes(render_contact_sheet(valid_report, 4, "unique-exact"))
        verify_glyph_report(report, contact, valid_report)

        wrong_report = [dict(row) for row in valid_report]
        wrong_report[0]["bitmap_fingerprint"] = "0" * 64
        write_glyph_report(report, wrong_report)
        must_fail(verify_glyph_report, report, contact, valid_report)
        write_glyph_report(report, valid_report)

        contact.write_bytes(encode_png(736, 136, b"\xff" * (736 * 136 * 3)))
        must_fail(verify_glyph_report, report, contact, valid_report)
        contact.write_bytes(render_contact_sheet(valid_report, 4, "unique-exact"))
        damaged_contact = bytearray(contact.read_bytes())
        damaged_contact[-1] ^= 1
        contact.write_bytes(damaged_contact)
        must_fail(verify_glyph_report, report, contact, valid_report)

    print("PASS Shift-JIS glyph fixture verifier failures")


if __name__ == "__main__":
    main()
