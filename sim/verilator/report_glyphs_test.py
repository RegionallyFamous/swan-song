#!/usr/bin/env python3
"""Focused tests for the title-agnostic glyph provenance reporter."""

from __future__ import annotations

import csv
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from correlate_bg_cells import OUTPUT_FIELDS as BG_OUTPUT_FIELDS
from report_glyphs import OUTPUT_FIELDS, contact_indices, decode_pixels, generate_report


def encode_row(pixels: list[int], bpp: int, packed: int) -> list[int]:
    if packed:
        if bpp == 2:
            return [
                sum(pixels[index + offset] << (6 - 2 * offset) for offset in range(4))
                for index in range(0, 8, 4)
            ]
        return [
            (pixels[index] << 4) | pixels[index + 1]
            for index in range(0, 8, 2)
        ]
    return [
        sum(((pixel >> plane) & 1) << (7 - index) for index, pixel in enumerate(pixels))
        for plane in range(bpp)
    ]


def displayed_rows(
    stored: list[list[int]], *, hflip: int = 0, vflip: int = 0
) -> list[list[int]]:
    result = []
    for visual_row in range(8):
        source = stored[7 - visual_row if vflip else visual_row]
        result.append(list(reversed(source)) if hflip else source)
    return result


def bitmap_text(rows: list[list[int]], observed: tuple[int, ...] = tuple(range(8))) -> str:
    selected = set(observed)
    return "/".join(
        "".join(format(value, "X") for value in row) if index in selected else "????????"
        for index, row in enumerate(rows)
    )


def make_occurrence(
    *,
    start: int,
    layer: str,
    map_address: int,
    map_x: int,
    map_y: int,
    tile: int,
    stored_pixels: list[list[int]],
    bpp: int,
    packed: int = 0,
    hflip: int = 0,
    vflip: int = 0,
    source_base: int = 0x1000,
    write_base: int = 20,
    observed: tuple[int, ...] = tuple(range(8)),
    mixed: bool = False,
    collision: bool = False,
    dynamic: bool = False,
) -> list[dict[str, str]]:
    result = []
    byte_count = 2 if bpp == 2 else 4
    map_value = tile | (0x4000 if hflip else 0) | (0x8000 if vflip else 0)
    for order, visual_row in enumerate(observed):
        stored_row = 7 - visual_row if vflip else visual_row
        row_bytes = encode_row(stored_pixels[stored_row], bpp, packed)
        row = {field: "" for field in BG_OUTPUT_FIELDS}
        row.update(
            {
                "cell_index": str(start + order),
                "line": str(start + order + 1),
                "cycle": str(start + order),
                "bg_layer": layer,
                "map_x": str(map_x),
                "map_y": str(map_y),
                "map_address": str(map_address),
                "map_value": str(map_value),
                "tile_bank_enabled": "1",
                "tile_index": str(tile),
                "palette": "3",
                "hflip": str(hflip),
                "vflip": str(vflip),
                "bpp": str(bpp),
                "packed": str(packed),
                "tile_row": str(stored_row),
                "tile_row_address": str(
                    (0x2000 if bpp == 2 else 0x4000)
                    + tile * (16 if bpp == 2 else 32)
                    + stored_row * byte_count
                ),
                "tile_row_bytes": str(byte_count),
                "tile_row_value": str(
                    sum(value << (8 * index) for index, value in enumerate(row_bytes))
                ),
                "map_collision": "0",
                "tile_row_collision": "1" if collision and visual_row == 0 else "0",
                "coverage_status": "complete_from_reset",
                "map_raw_line": str(start + order),
                "map_raw_cycle": str(start + order - 3),
                "map_raw_collision": "0",
                "map_scoreboard_status": "match",
                "map_writer_summary": "cpu_exact",
                "map_source_summary": "cpu_write",
                "tile0_raw_line": str(start + order),
                "tile0_raw_cycle": str(start + order - 2),
                "tile0_raw_address": "0",
                "tile0_raw_value": "0",
                "tile0_raw_collision": "1" if collision and visual_row == 0 else "0",
                "tile1_raw_line": str(start + order),
                "tile1_raw_cycle": str(start + order - 1),
                "tile1_raw_address": "2",
                "tile1_raw_value": "0",
                "tile1_raw_collision": "0",
                "contributing_raw_lines": str(start + order),
                "contributing_raw_cycles": str(start + order - 2),
                "row_scoreboard_status": "match",
                "row_writer_summary": "mixed" if mixed and visual_row == 3 else "gdma",
                "row_source_summary": "mixed_or_partial_dma_sources"
                if mixed and visual_row == 3
                else "gdma_rom",
            }
        )
        for index, prefix in enumerate(("map_lo", "map_hi")):
            row.update(
                {
                    f"{prefix}_value": str((map_value >> (8 * index)) & 0xFF),
                    f"{prefix}_write_line": "10",
                    f"{prefix}_write_cycle": "10",
                    f"{prefix}_initiator": "cpu",
                    f"{prefix}_instruction_id": "77",
                    f"{prefix}_origin_pc": str(0x8000),
                }
            )
        for index, value in enumerate(row_bytes):
            prefix = f"row_b{index}"
            # Exercise the raw-fetch/atomic-promotion gap: this rewrite is
            # before the first cell event but after the first map raw fetch.
            write_cycle = start - 2 if dynamic and visual_row == 4 else write_base + stored_row
            initiator = "cpu" if mixed and visual_row == 3 and index == 1 else "gdma"
            row.update(
                {
                    f"{prefix}_value": str(value),
                    f"{prefix}_write_line": str(100 + stored_row),
                    f"{prefix}_write_cycle": str(write_cycle),
                    f"{prefix}_initiator": initiator,
                    f"{prefix}_instruction_id": "91" if initiator == "cpu" else "",
                    f"{prefix}_origin_pc": str(0x8123) if initiator == "cpu" else "",
                    f"{prefix}_source_space": "cart_rom_linear"
                    if initiator == "gdma"
                    else "",
                    f"{prefix}_source_offset": str(
                        source_base + stored_row * byte_count + index
                    )
                    if initiator == "gdma"
                    else "",
                    f"{prefix}_source_read_cycle": str(write_cycle - 1)
                    if initiator == "gdma"
                    else "",
                }
            )
        result.append(row)
    return result


class GlyphReporterTest(unittest.TestCase):
    def test_documented_row_decoding(self) -> None:
        # First rows of the WSdev 2bpp, 4bpp planar, and 4bpp packed examples.
        self.assertEqual(
            decode_pixels([0x01, 0x7C], 2, 0, 0),
            (0, 2, 2, 2, 2, 2, 0, 1),
        )
        self.assertEqual(
            decode_pixels([0x1B, 0xE4], 2, 1, 0),
            (0, 1, 2, 3, 3, 2, 1, 0),
        )
        expected_4bpp = (0, 1, 2, 3, 0, 1, 2, 4)
        self.assertEqual(decode_pixels([0x54, 0x32, 0x01, 0x00], 4, 0, 0), expected_4bpp)
        self.assertEqual(decode_pixels([0x01, 0x23, 0x01, 0x24], 4, 1, 0), expected_4bpp)
        self.assertEqual(
            decode_pixels([0x01, 0x23, 0x01, 0x24], 4, 1, 1),
            tuple(reversed(expected_4bpp)),
        )

    def test_formats_epochs_uncertainty_and_determinism(self) -> None:
        two_bpp = [[(x + y) % 4 for x in range(8)] for y in range(8)]
        two_bpp_changed = [[(3 - x + y) % 4 for x in range(8)] for y in range(8)]
        planar = [[(x + 2 * y) % 16 for x in range(8)] for y in range(8)]
        packed = [[(2 * x + y) % 16 for x in range(8)] for y in range(8)]
        flat = [[(x // 2 + y) % 4 for x in range(8)] for y in range(8)]

        rows: list[dict[str, str]] = []
        # Two identical observations coalesce; changing the same tile/map slot
        # creates a new provenance-sensitive epoch.
        rows += make_occurrence(
            start=100,
            layer="screen1",
            map_address=0x1A14,
            map_x=10,
            map_y=8,
            tile=1,
            stored_pixels=two_bpp,
            bpp=2,
            source_base=0x1000,
            write_base=20,
        )
        rows += make_occurrence(
            start=200,
            layer="screen1",
            map_address=0x1A14,
            map_x=10,
            map_y=8,
            tile=1,
            stored_pixels=two_bpp,
            bpp=2,
            source_base=0x1000,
            write_base=20,
        )
        rows += make_occurrence(
            start=300,
            layer="screen1",
            map_address=0x1A14,
            map_x=10,
            map_y=8,
            tile=1,
            stored_pixels=two_bpp_changed,
            bpp=2,
            source_base=0x1100,
            write_base=80,
        )
        # Identical pixels copied from a new source are still a distinct epoch;
        # fingerprints describe pictures, while epochs preserve provenance.
        rows += make_occurrence(
            start=350,
            layer="screen1",
            map_address=0x1A14,
            map_x=10,
            map_y=8,
            tile=1,
            stored_pixels=two_bpp_changed,
            bpp=2,
            source_base=0x1200,
            write_base=90,
        )
        rows += make_occurrence(
            start=400,
            layer="screen1",
            map_address=0x1A16,
            map_x=11,
            map_y=8,
            tile=2,
            stored_pixels=planar,
            bpp=4,
            hflip=1,
            source_base=0x2000,
            write_base=120,
        )
        rows += make_occurrence(
            start=450,
            layer="screen1",
            map_address=0x1A18,
            map_x=12,
            map_y=8,
            tile=7,
            stored_pixels=two_bpp,
            bpp=2,
            packed=1,
            source_base=0x2800,
            write_base=140,
        )
        rows += make_occurrence(
            start=500,
            layer="screen2",
            map_address=0x3218,
            map_x=12,
            map_y=6,
            tile=3,
            stored_pixels=packed,
            bpp=4,
            packed=1,
            hflip=1,
            vflip=1,
            source_base=0x3000,
            write_base=160,
        )
        rows += make_occurrence(
            start=600,
            layer="screen2",
            map_address=0x321A,
            map_x=13,
            map_y=6,
            tile=4,
            stored_pixels=flat,
            bpp=2,
            observed=(0, 1, 2, 3),
            source_base=0x4000,
            write_base=200,
        )
        rows += make_occurrence(
            start=700,
            layer="screen2",
            map_address=0x321C,
            map_x=14,
            map_y=6,
            tile=5,
            stored_pixels=flat,
            bpp=2,
            mixed=True,
            dynamic=True,
            source_base=0x5000,
            write_base=240,
        )
        rows += make_occurrence(
            start=800,
            layer="screen2",
            map_address=0x321E,
            map_x=15,
            map_y=6,
            tile=6,
            stored_pixels=flat,
            bpp=2,
            collision=True,
            source_base=0x6000,
            write_base=280,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "bg-cells.csv"
            with source.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=BG_OUTPUT_FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)

            csv_a, csv_b = root / "a.csv", root / "b.csv"
            png_a, png_b = root / "a.png", root / "b.png"
            records_a = generate_report(source, csv_a, png_a, columns=3)
            records_b = generate_report(source, csv_b, png_b, columns=3)

            self.assertEqual(records_a, records_b)
            self.assertEqual(csv_a.read_bytes(), csv_b.read_bytes())
            self.assertEqual(png_a.read_bytes(), png_b.read_bytes())
            self.assertEqual(csv_a.read_text().splitlines()[0], ",".join(OUTPUT_FIELDS))
            self.assertTrue(png_a.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(struct.unpack(">II", png_a.read_bytes()[16:24]), (552, 204))
            self.assertEqual(len(records_a), 9)

            (
                static,
                changed,
                rewritten,
                planar_row,
                packed_2bpp_row,
                packed_row,
                incomplete,
                mixed,
                collision,
            ) = records_a
            self.assertEqual(static["occurrence_count"], "2")
            self.assertEqual(static["occurrence_cycles"], "100-107;200-207")
            self.assertEqual(static["confidence"], "exact")
            self.assertEqual(static["tile_bank_enabled"], "1")
            self.assertEqual(static["tile_iram_ranges"], "0x2010-0x201f")
            self.assertEqual(static["bitmap_rows"], bitmap_text(two_bpp))
            self.assertEqual(
                static["bitmap_fingerprint"],
                hashlib.sha256(bitmap_text(two_bpp).encode("ascii")).hexdigest(),
            )
            self.assertEqual(static["map_writer_origin_pcs"], "0x08000")
            self.assertEqual(
                static["row_source_ranges"],
                "cart_rom_linear:0x001000-0x00100f",
            )

            self.assertEqual(changed["occurrence_count"], "1")
            self.assertNotEqual(changed["bitmap_fingerprint"], static["bitmap_fingerprint"])
            self.assertEqual(changed["row_source_ranges"], "cart_rom_linear:0x001100-0x00110f")
            self.assertEqual(rewritten["bitmap_fingerprint"], changed["bitmap_fingerprint"])
            self.assertEqual(rewritten["row_source_ranges"], "cart_rom_linear:0x001200-0x00120f")

            self.assertEqual(planar_row["bpp"], "4")
            self.assertEqual(planar_row["packed"], "0")
            self.assertEqual(planar_row["hflip"], "1")
            self.assertEqual(
                planar_row["bitmap_rows"],
                bitmap_text(displayed_rows(planar, hflip=1)),
            )
            self.assertEqual(
                planar_row["row_source_ranges"],
                "cart_rom_linear:0x002000-0x00201f",
            )

            self.assertEqual(packed_2bpp_row["bpp"], "2")
            self.assertEqual(packed_2bpp_row["packed"], "1")
            self.assertEqual(packed_2bpp_row["bitmap_rows"], bitmap_text(two_bpp))

            self.assertEqual(packed_row["bpp"], "4")
            self.assertEqual(packed_row["packed"], "1")
            self.assertEqual(packed_row["vflip"], "1")
            self.assertEqual(
                packed_row["bitmap_rows"],
                bitmap_text(displayed_rows(packed, hflip=1, vflip=1)),
            )

            self.assertEqual(incomplete["complete"], "0")
            self.assertEqual(incomplete["confidence"], "incomplete")
            self.assertEqual(incomplete["missing_rows"], "4,5,6,7")
            self.assertIn("????????", incomplete["bitmap_rows"])

            self.assertEqual(mixed["mixed"], "1")
            self.assertEqual(mixed["confidence"], "mixed")
            self.assertIn("mixed_provenance", mixed["flags"])
            self.assertIn("dynamic_during_occurrence", mixed["flags"])
            self.assertIn("cpu", mixed["row_writer_initiators"])
            self.assertIn("gdma", mixed["row_writer_initiators"])

            self.assertEqual(collision["collision"], "1")
            self.assertEqual(collision["confidence"], "collision")
            self.assertIn("collision", collision["flags"])

            csv_compact, png_compact = root / "compact.csv", root / "compact.png"
            compact_records = generate_report(
                source,
                csv_compact,
                png_compact,
                columns=3,
                contact_mode="unique-exact",
            )
            self.assertEqual(compact_records, records_a)
            self.assertEqual(csv_compact.read_bytes(), csv_a.read_bytes())
            self.assertEqual(contact_indices(compact_records, "unique-exact"), [0, 1, 3, 5])
            self.assertEqual(
                struct.unpack(">II", png_compact.read_bytes()[16:24]),
                (552, 136),
            )

    def test_blank_status_cannot_be_reported_exact(self) -> None:
        pixels = [[(x + y) % 4 for x in range(8)] for y in range(8)]
        rows = make_occurrence(
            start=100,
            layer="screen1",
            map_address=0x1A14,
            map_x=10,
            map_y=8,
            tile=1,
            stored_pixels=pixels,
            bpp=2,
        )
        rows[3]["coverage_status"] = ""
        rows[4]["map_scoreboard_status"] = ""
        rows[5]["row_scoreboard_status"] = ""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "bg-cells.csv"
            with source.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(
                    output, fieldnames=BG_OUTPUT_FIELDS, lineterminator="\n"
                )
                writer.writeheader()
                writer.writerows(rows)
            records = generate_report(source, root / "report.csv", root / "report.png")
        self.assertEqual(records[0]["confidence"], "uncertain")
        self.assertEqual(
            set(records[0]["flags"].split(";")),
            {
                "incomplete_coverage",
                "map_scoreboard_uncertain",
                "row_scoreboard_uncertain",
            },
        )


if __name__ == "__main__":
    unittest.main()
