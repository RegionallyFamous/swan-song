#!/usr/bin/env python3
"""Focused grouping and writer-snapshot tests for correlate_bg_cells.py."""

from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path

from correlate_bg_cells import FIELDS_V5, correlate
from correlate_provenance import trace_fnv1a64


def event(cycle: int, kind: str, **values: object) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V5}
    row.update({"cycle": cycle, "event": kind})
    row.update(values)
    return row


def mem(cycle: int, address: int, value: int, pc: int) -> dict[str, object]:
    return event(
        cycle,
        "mem",
        address=address,
        value=value,
        initiator="cpu",
        access="write",
        byte_enable=3,
        space="iram",
        mapped_offset=address,
        instruction_id=pc,
        origin_pc=pc,
        origin_status="exact",
    )


def raw(cycle: int, role: str, address: int, value: int, collision: int = 0) -> dict[str, object]:
    return event(
        cycle,
        "vram",
        role=role,
        address=address,
        fetch_value=value,
        fetch_collision=collision,
    )


def cell(cycle: int, layer: str, **values: object) -> dict[str, object]:
    encoded_layer = {"screen1": 1, "screen2": 2}.get(layer, layer)
    defaults: dict[str, object] = {
        "bg_layer": encoded_layer,
        "packed": 0,
        "map_collision": 0,
        "tile_row_collision": 0,
    }
    defaults.update(values)
    return event(cycle, "bg_cell", **defaults)


def rows(
    collision: int = 0,
    bad_value: bool = False,
    unused_collision: int = 0,
) -> list[dict[str, object]]:
    map1, map2 = 0xAA12, 0x4625
    result = [
        mem(1, 0x1000, map1, 0x101),
        mem(1, 0x412C, 0x2211, 0x102),
        mem(1, 0x412E, 0xBBAA, 0x103),
        mem(1, 0x1200, map2, 0x201),
        mem(1, 0x44A8, 0x4433, 0x202),
        mem(1, 0x44AA, 0x6655, 0x203),
        # Both layer pipelines complete on one cycle, deliberately interleaved.
        raw(5, "screen1_map", 0x1000, map1),
        raw(5, "screen2_map", 0x1200, map2),
        raw(5, "screen1_tile", 0x412C, 0x2211, unused_collision),
        raw(5, "screen2_tile", 0x44A8, 0x4433),
        raw(5, "screen1_tile", 0x412E, 0xBBAA, collision),
        raw(5, "screen2_tile", 0x44AA, 0x6655),
        # Same-edge writes are applied after all DPRAM snapshots.
        mem(5, 0x1200, 0x0000, 0x888),
        # This overwrite is after the raw fetch but before activation. Output
        # must retain the 0x103 writer snapshot, never this writer.
        mem(6, 0x412E, 0xDDCC, 0x999),
        cell(
            7,
            "screen1",
            map_address=0x1000,
            map_value=map1,
            map_x=0,
            map_y=0,
            tile_bank_enabled=1,
            tile_index=0x212,
            palette=5,
            hflip=0,
            vflip=1,
            bpp=2,
            tile_row=7,
            tile_row_address=0x412E,
            tile_row_bytes=2,
            tile_row_value=0xBBAA if not bad_value else 0xBBA9,
            tile_row_collision=collision,
        ),
        cell(
            7,
            "screen2",
            map_address=0x1200,
            map_value=map2,
            map_x=0,
            map_y=8,
            tile_bank_enabled=0,
            tile_index=0x25,
            palette=3,
            hflip=1,
            vflip=0,
            bpp=4,
            tile_row=2,
            tile_row_address=0x44A8,
            tile_row_bytes=4,
            tile_row_value=0x66554433,
        ),
    ]
    return result


def cpu_copy_cell_rows() -> list[dict[str, object]]:
    instruction_id = 50
    origin = 0xF0100
    return [
        mem(1, 0x1000, 0, 0x101),
        event(
            1,
            "mem",
            address=origin,
            value=0xA4F3,
            initiator="cpu",
            access="read",
            byte_enable=0,
            space="cart_rom_linear",
            mapped_offset=0x100,
            origin_status="unattributed",
        ),
        event(
            2,
            "mem",
            address=0xF0200,
            value=0x3412,
            initiator="cpu",
            access="read",
            byte_enable=0,
            space="cart_rom_linear",
            mapped_offset=0x200,
            instruction_id=instruction_id,
            origin_pc=origin,
            origin_status="exact",
        ),
        event(
            3,
            "mem",
            address=0x2000,
            value=0x12,
            initiator="cpu",
            access="write",
            byte_enable=1,
            space="iram",
            mapped_offset=0x2000,
            instruction_id=instruction_id,
            origin_pc=origin,
            origin_status="exact",
        ),
        event(
            4,
            "mem",
            address=0xF0201,
            value=0x0034,
            initiator="cpu",
            access="read",
            byte_enable=0,
            space="cart_rom_linear",
            mapped_offset=0x201,
            instruction_id=instruction_id,
            origin_pc=origin,
            origin_status="exact",
        ),
        event(
            5,
            "mem",
            address=0x2001,
            value=0x34,
            initiator="cpu",
            access="write",
            byte_enable=1,
            space="iram",
            mapped_offset=0x2001,
            instruction_id=instruction_id,
            origin_pc=origin,
            origin_status="exact",
        ),
        raw(10, "screen1_map", 0x1000, 0),
        raw(10, "screen1_tile", 0x2000, 0x3412),
        raw(10, "screen1_tile", 0x2002, 0),
        cell(
            11,
            "screen1",
            map_address=0x1000,
            map_value=0,
            map_x=0,
            map_y=0,
            tile_bank_enabled=1,
            tile_index=0,
            palette=0,
            hflip=0,
            vflip=0,
            bpp=2,
            tile_row=0,
            tile_row_address=0x2000,
            tile_row_bytes=2,
            tile_row_value=0x3412,
        ),
    ]


def write_trace(path: Path, trace_rows: list[dict[str, object]], manifest: bool = True) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        writer.writerows(trace_rows)
    if manifest:
        data = {
            "schema": "swan-song-trace-manifest-v1",
            "trace_schema": 5,
            "trace_size_bytes": path.stat().st_size,
            "trace_fnv1a64": trace_fnv1a64(path),
            "capture_start": "reset_release",
            "capture_completed": True,
            "capture_cycles": max(int(row["cycle"]) for row in trace_rows),
            "completed_frames": 1,
            "rom_size": 65536,
            "events": {"mem": True, "vram": True, "bg_cell": True},
            "memory_filters_active": False,
            "display_filters_active": False,
            "complete_memory_history": True,
            "complete_display_history": True,
            "complete_bg_cell_history": True,
            "savestate_inputs_asserted": False,
            "iram_initial_state": "zero",
        }
        Path(f"{path}.manifest.json").write_text(json.dumps(data), encoding="utf-8")


def expect_error(path: Path, expected: str) -> None:
    try:
        correlate(path, io.StringIO())
    except ValueError as error:
        assert expected in str(error), error
    else:
        raise AssertionError(f"expected error containing {expected!r}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-bg-cell-") as directory:
        root = Path(directory)
        trace = root / "events.csv"
        write_trace(trace, rows())
        output = io.StringIO()
        counts = correlate(trace, output, require_complete_coverage=True)
        assert counts == {
            "cells": 2,
            "screen1": 1,
            "screen2": 1,
            "bpp2": 1,
            "bpp4": 1,
            "raw_superseded": 0,
            "raw_unpromoted": 0,
            "raw_inflight": 0,
            "raw_prefix_truncated": 0,
            "cpu_rom_movsb_cells": 0,
            "cpu_rom_movsb_bytes": 0,
            "cpu_rom_movsb_origins": 0,
        }
        records = list(csv.DictReader(io.StringIO(output.getvalue())))
        assert [record["bg_layer"] for record in records] == ["screen1", "screen2"]
        assert records[0]["contributing_raw_lines"] == "12"
        assert records[0]["row_b0_origin_pc"] == str(0x103)
        assert records[0]["row_b1_origin_pc"] == str(0x103)
        assert records[0]["row_b2_origin_pc"] == ""
        assert records[1]["contributing_raw_lines"] == "11;13"
        assert records[1]["row_b0_origin_pc"] == str(0x202)
        assert records[1]["row_b2_origin_pc"] == str(0x203)
        assert records[1]["map_lo_origin_pc"] == str(0x201)
        assert records[0]["coverage_status"] == "complete_from_reset"

        # A reset-release capture can begin with the second word of the GPU
        # fetch group that reset interrupted. Exactly one such leading tile
        # fragment per layer is ignored; normal grouping remains strict.
        reset_prefix_trace = root / "reset-prefix.csv"
        reset_prefix_rows = sorted(
            [
                raw(0, "screen1_tile", 0x2002, 0),
                raw(0, "screen2_tile", 0x2002, 0),
                *rows(),
            ],
            key=lambda item: int(item["cycle"]),
        )
        write_trace(reset_prefix_trace, reset_prefix_rows)
        reset_prefix_counts = correlate(
            reset_prefix_trace, io.StringIO(), require_complete_coverage=True
        )
        assert reset_prefix_counts == {**counts, "raw_prefix_truncated": 2}

        malformed_prefix_trace = root / "malformed-reset-prefix.csv"
        malformed_prefix_rows = sorted(
            [
                raw(0, "screen1_tile", 0x2000, 0),
                raw(0, "screen1_tile", 0x2006, 0),
                *rows(),
            ],
            key=lambda item: int(item["cycle"]),
        )
        write_trace(malformed_prefix_trace, malformed_prefix_rows)
        expect_error(malformed_prefix_trace, "malformed screen1 reset-boundary")

        unbound_prefix_trace = root / "unbound-reset-prefix.csv"
        write_trace(unbound_prefix_trace, reset_prefix_rows, manifest=False)
        expect_error(unbound_prefix_trace, "requires a complete reset-release manifest")

        late_orphan_trace = root / "late-orphan.csv"
        late_orphan_rows = [*rows(), raw(8, "screen1_tile", 0x2002, 0)]
        write_trace(late_orphan_trace, late_orphan_rows)
        expect_error(late_orphan_trace, "tile fetch has no preceding map")

        cpu_copy_trace = root / "cpu-copy.csv"
        write_trace(cpu_copy_trace, cpu_copy_cell_rows())
        cpu_copy_output = io.StringIO()
        cpu_copy_counts = correlate(
            cpu_copy_trace, cpu_copy_output, require_complete_coverage=True
        )
        assert cpu_copy_counts["cpu_rom_movsb_cells"] == 1
        assert cpu_copy_counts["cpu_rom_movsb_bytes"] == 2
        assert cpu_copy_counts["cpu_rom_movsb_origins"] == 1
        cpu_copy_record = next(
            csv.DictReader(io.StringIO(cpu_copy_output.getvalue()))
        )
        assert cpu_copy_record["row_source_summary"] == "cpu_rom_movsb"
        assert cpu_copy_record["row_b0_source_offset"] == str(0x200)
        assert cpu_copy_record["row_b1_source_offset"] == str(0x201)
        assert cpu_copy_record["row_b0_origin_pc"] == str(0xF0100)

        superseded_trace = root / "superseded.csv"
        superseded_rows = sorted(
            [
                *rows(),
                raw(3, "screen1_map", 0x0000, 0),
                raw(3, "screen1_tile", 0x2000, 0),
                raw(3, "screen1_tile", 0x2002, 0),
            ],
            key=lambda item: int(item["cycle"]),
        )
        write_trace(superseded_trace, superseded_rows)
        superseded_output = io.StringIO()
        superseded_counts = correlate(superseded_trace, superseded_output)
        assert superseded_counts["cells"] == 2
        assert superseded_counts["raw_superseded"] == 1
        superseded_records = list(
            csv.DictReader(io.StringIO(superseded_output.getvalue()))
        )
        assert superseded_records[0]["map_raw_cycle"] == "5"

        unused_collision_trace = root / "unused-collision.csv"
        write_trace(unused_collision_trace, rows(unused_collision=1))
        unused_output = io.StringIO()
        unused_counts = correlate(unused_collision_trace, unused_output)
        assert unused_counts["cells"] == 2
        unused_records = list(csv.DictReader(io.StringIO(unused_output.getvalue())))
        assert unused_records[0]["tile0_raw_collision"] == "1"

        collision_trace = root / "collision.csv"
        write_trace(collision_trace, rows(collision=1))
        expect_error(collision_trace, "collided")

        mismatch_trace = root / "mismatch.csv"
        write_trace(mismatch_trace, rows(bad_value=True))
        expect_error(mismatch_trace, "atomic tile-row fields")

        incomplete_trace = root / "incomplete.csv"
        write_trace(incomplete_trace, rows()[:-1])
        incomplete_counts = correlate(incomplete_trace, io.StringIO())
        assert incomplete_counts["raw_unpromoted"] == 1

        orphan_trace = root / "orphan.csv"
        orphan_rows = [
            row
            for row in rows()
            if row.get("role") not in {"screen2_map", "screen2_tile"}
        ]
        write_trace(orphan_trace, orphan_rows)
        expect_error(orphan_trace, "atomic cell has no completed raw fetch group")

    print("PASS atomic background-cell correlator")


if __name__ == "__main__":
    main()
