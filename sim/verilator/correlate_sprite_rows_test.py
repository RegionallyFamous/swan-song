#!/usr/bin/env python3
"""Adversarial pairing and fetch-time tests for correlate_sprite_rows.py."""

from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from correlate_provenance import trace_fnv1a64
from correlate_sprite_rows import COUNT_NAMES, correlate, expected_count
from verify_trace import FIELDS_V5, FIELDS_V6


def event(cycle: int, kind: str, **values: object) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V6}
    row.update({"cycle": cycle, "event": kind})
    row.update(values)
    return row


def mem(
    cycle: int,
    address: int,
    value: int,
    pc: int,
    byte_enable: int = 3,
) -> dict[str, object]:
    return event(
        cycle,
        "mem",
        address=address,
        value=value,
        initiator="cpu",
        access="write",
        byte_enable=byte_enable,
        space="iram",
        mapped_offset=address,
        instruction_id=pc,
        origin_pc=pc,
        origin_status="exact",
    )


def raw(
    cycle: int,
    role: str,
    address: int,
    value: int,
    collision: int = 0,
) -> dict[str, object]:
    return event(
        cycle,
        "vram",
        role=role,
        address=address,
        fetch_value=value,
        fetch_collision=collision,
    )


def descriptor(
    tile: int,
    palette: int,
    y: int,
    x: int = 0,
    hflip: int = 0,
    vflip: int = 0,
    priority: int = 0,
    window: int = 0,
) -> int:
    return (
        tile
        | ((palette & 7) << 9)
        | (window << 12)
        | (priority << 13)
        | (hflip << 14)
        | (vflip << 15)
        | (y << 16)
        | (x << 24)
    )


def sprite_row(
    cycle: int,
    table_address: int,
    table_value: int,
    line_y: int,
    line_slot: int,
    bpp: int,
    packed: int,
    row_value: int,
    table_collision: int = 0,
    row_collision: int = 0,
    table_generation: int = 0,
    line_epoch: int = 0,
) -> dict[str, object]:
    tile = table_value & 0x1FF
    palette = 8 | ((table_value >> 9) & 7)
    hflip = (table_value >> 14) & 1
    vflip = (table_value >> 15) & 1
    sprite_y = (table_value >> 16) & 0xFF
    delta = (line_y - sprite_y) & 0xFF
    tile_row = 7 - delta if vflip else delta
    row_bytes = 2 if bpp == 2 else 4
    row_address = (
        (0x2000 if bpp == 2 else 0x4000)
        + tile * row_bytes * 8
        + tile_row * row_bytes
    )
    return event(
        cycle,
        "sprite_row",
        sprite_table_address=table_address,
        sprite_table_value=table_value,
        sprite_table_collision=table_collision,
        sprite_line_y=line_y,
        sprite_line_slot=line_slot,
        sprite_table_generation=table_generation,
        sprite_line_epoch=line_epoch,
        tile_index=tile,
        palette=palette,
        hflip=hflip,
        vflip=vflip,
        bpp=bpp,
        packed=packed,
        tile_row=tile_row,
        tile_row_address=row_address,
        tile_row_bytes=row_bytes,
        tile_row_value=row_value,
        tile_row_collision=row_collision,
    )


def table_writes(cycle: int, address: int, value: int, pc: int) -> list[dict[str, object]]:
    return [
        mem(cycle, address, value & 0xFFFF, pc),
        mem(cycle, address + 2, value >> 16, pc + 1),
    ]


def table_reads(cycle: int, address: int, value: int) -> list[dict[str, object]]:
    return [
        raw(cycle, "sprite_table", address, value & 0xFFFF),
        raw(cycle, "sprite_table", address + 2, value >> 16),
    ]


def main_rows() -> list[dict[str, object]]:
    even_desc = descriptor(0, 1, 20, x=40)
    odd_desc = descriptor(1, 2, 19, x=50, hflip=1)
    color_desc = descriptor(2, 3, 18, x=60, vflip=1, priority=1)
    unused_desc = descriptor(3, 0, 70)
    result: list[dict[str, object]] = []

    for index, value in enumerate((even_desc, odd_desc, color_desc, unused_desc)):
        result.extend(table_writes(1, 0x1000 + index * 4, value, 0x100 + index * 2))
    result.extend(
        [
            mem(1, 0x2000, 0x2211, 0x200),
            mem(1, 0x2002, 0x4433, 0x201),
            mem(1, 0x2012, 0x6655, 0x210),
            mem(1, 0x4054, 0xA2A1, 0x220),
            mem(1, 0x4056, 0xA4A3, 0x221),
        ]
    )
    for index, value in enumerate((even_desc, odd_desc, color_desc, unused_desc)):
        result.extend(table_reads(5, 0x1000 + index * 4, value))

    # These writes happen after descriptor DMA.  The atomic event and audit
    # must retain the fetched generation and its original writer snapshots.
    result.extend(table_writes(6, 0x1000, descriptor(9, 0, 99), 0x900))

    # 2bpp even row: the second read goes to A+2.  It is deliberately collided
    # and disagrees with the scoreboard, but is noncontributing.
    result.extend(
        [
            raw(10, "sprite_tile", 0x2000, 0x2211),
            raw(10, "sprite_tile", 0x2002, 0xDEAD, 1),
            sprite_row(11, 0x1000, even_desc, 20, 0, 2, 0, 0x2211),
        ]
    )

    # 2bpp odd row: the forced address bit repeats A.  A same-cycle post-fetch
    # write changes the repeated read, but cannot change the promoted first word.
    result.extend(
        [
            raw(20, "sprite_tile", 0x2012, 0x6655),
            mem(20, 0x2012, 0x8877, 0x777),
            raw(21, "sprite_tile", 0x2012, 0x8877),
            mem(21, 0x2012, 0xAA99, 0x778),
            sprite_row(
                22, 0x1004, odd_desc, 20, 1, 2, 1, 0x6655,
                table_generation=1,
            ),
        ]
    )

    # 4bpp consumes both words.  A write after the second raw fetch must not
    # replace that word's captured provenance.
    result.extend(
        [
            raw(30, "sprite_tile", 0x4054, 0xA2A1),
            raw(31, "sprite_tile", 0x4056, 0xA4A3),
            mem(31, 0x4056, 0xC6C5, 0x888),
            sprite_row(
                32, 0x1008, color_desc, 20, 2, 4, 1, 0xA4A3A2A1,
                table_generation=2,
            ),
            # One complete group and one first word are left beyond the last
            # atomic handoff to exercise explicit end-of-capture accounting.
            raw(40, "sprite_tile", 0x2100, 0),
            raw(40, "sprite_tile", 0x2102, 0),
            raw(41, "sprite_tile", 0x2200, 0),
            raw(41, "sprite_table", 0x1100, 0),
        ]
    )
    return result


def cpu_copy_rows() -> list[dict[str, object]]:
    instruction_id = 50
    origin = 0xF0100
    return [
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
        mem(3, 0x2000, 0x12, origin, byte_enable=1)
        | {"instruction_id": instruction_id},
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
        mem(5, 0x2001, 0x34, origin, byte_enable=1)
        | {"instruction_id": instruction_id},
        raw(7, "sprite_table", 0x1000, 0),
        raw(7, "sprite_table", 0x1002, 0),
        raw(8, "sprite_tile", 0x2000, 0x3412),
        raw(9, "sprite_tile", 0x2002, 0),
        sprite_row(10, 0x1000, 0, 0, 0, 2, 0, 0x3412),
    ]


def wrapped_y_rows() -> list[dict[str, object]]:
    wrapped_desc = descriptor(0, 1, 0xFE)
    return [
        *table_writes(1, 0x1000, wrapped_desc, 0x300),
        mem(1, 0x2004, 0xBBAA, 0x302),
        *table_reads(5, 0x1000, wrapped_desc),
        raw(10, "sprite_tile", 0x2004, 0xBBAA),
        raw(10, "sprite_tile", 0x2006, 0),
        sprite_row(11, 0x1000, wrapped_desc, 0, 0, 2, 0, 0xBBAA),
    ]


def repeated_line_after_table_refresh_rows() -> list[dict[str, object]]:
    rows = wrapped_y_rows()
    wrapped_desc = descriptor(0, 1, 0xFE)
    rows.extend(
        [
            *table_reads(20, 0x1000, wrapped_desc),
            raw(30, "sprite_tile", 0x2004, 0xBBAA),
            raw(30, "sprite_tile", 0x2006, 0),
            sprite_row(
                31, 0x1000, wrapped_desc, 0, 0, 2, 0, 0xBBAA,
                table_generation=1,
                line_epoch=3,
            ),
        ]
    )
    return rows


def identical_descriptor_refresh_rows() -> list[dict[str, object]]:
    value = descriptor(0, 1, 20, x=40)
    return [
        *table_writes(1, 0x1000, value, 0x500),
        mem(1, 0x2000, 0x2211, 0x502),
        *table_reads(5, 0x1000, value),
        # A later raw refresh has the same descriptor bytes but a new writer
        # generation. Its collision makes a forged reference observably wrong.
        *table_writes(6, 0x1000, value, 0x900),
        raw(7, "sprite_table", 0x1000, value & 0xFFFF),
        raw(7, "sprite_table", 0x1002, value >> 16, collision=1),
        raw(10, "sprite_tile", 0x2000, 0x2211),
        raw(10, "sprite_tile", 0x2002, 0),
        sprite_row(11, 0x1000, value, 20, 0, 2, 0, 0x2211),
    ]


def full_slot_line_rows() -> list[dict[str, object]]:
    value = descriptor(0, 1, 20, x=40)
    rows = [
        *table_writes(1, 0x1000, value, 0x400),
        mem(1, 0x2000, 0x2211, 0x402),
        *table_reads(5, 0x1000, value),
    ]
    for slot in range(32):
        fetch_cycle = 10 + slot * 3
        rows.extend(
            [
                raw(fetch_cycle, "sprite_tile", 0x2000, 0x2211),
                raw(fetch_cycle, "sprite_tile", 0x2002, 0),
                sprite_row(
                    fetch_cycle + 1,
                    0x1000,
                    value,
                    20,
                    slot,
                    2,
                    0,
                    0x2211,
                ),
            ]
        )
    return rows


def write_trace(
    path: Path,
    trace_rows: list[dict[str, object]],
    manifest: bool = True,
    complete: bool = True,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V6, lineterminator="\n")
        writer.writeheader()
        writer.writerows(trace_rows)
    if not manifest:
        return
    data = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 6,
        "trace_size_bytes": path.stat().st_size,
        "trace_fnv1a64": trace_fnv1a64(path),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": max(int(row["cycle"]) for row in trace_rows),
        "completed_frames": 1,
        "rom_size": 65536,
        "events": {"mem": True, "vram": True, "sprite_row": True},
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": True,
        "complete_sprite_row_history": complete,
        "savestate_inputs_asserted": False,
        "iram_initial_state": "zero",
    }
    Path(f"{path}.manifest.json").write_text(json.dumps(data), encoding="utf-8")


def expect_error(path: Path, expected: str, complete: bool = False) -> None:
    try:
        correlate(path, io.StringIO(), require_complete_coverage=complete)
    except ValueError as error:
        assert expected in str(error), error
    else:
        raise AssertionError(f"expected error containing {expected!r}")


def changed(
    source: list[dict[str, object]],
    predicate,
    **updates: object,
) -> list[dict[str, object]]:
    result = copy.deepcopy(source)
    matches = [row for row in result if predicate(row)]
    assert len(matches) == 1, len(matches)
    matches[0].update(updates)
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-sprite-rows-") as directory:
        root = Path(directory)
        rows = main_rows()
        trace = root / "events.csv"
        write_trace(trace, rows)
        output = io.StringIO()
        counts = correlate(trace, output, require_complete_coverage=True)
        assert counts == {
            "sprite_rows": 3,
            "bpp2": 2,
            "bpp4": 1,
            "packed": 2,
            "planar": 1,
            "raw_table_groups": 4,
            "raw_table_unused": 1,
            "raw_tile_groups": 4,
            "raw_tile_unpromoted": 1,
            "raw_table_inflight": 1,
            "raw_tile_inflight": 1,
            "descriptor_cpu_exact": 3,
            "row_cpu_exact": 3,
            "row_gdma": 0,
            "row_source_gdma_rom": 0,
            "descriptor_collision": 0,
            "row_collision": 0,
            "cpu_rom_movsb_rows": 0,
            "cpu_rom_movsb_bytes": 0,
            "cpu_rom_movsb_origins": 0,
        }
        records = list(csv.DictReader(io.StringIO(output.getvalue())))
        assert len(records) == 3

        even, odd, color = records
        assert even["tile1_contributes"] == "0"
        assert even["tile1_raw_collision"] == "1"
        assert even["tile1_scoreboard_status"] == "unspecified_collision"
        assert even["contributing_raw_lines"] == even["tile0_raw_line"]
        assert even["row_b2_origin_pc"] == ""
        assert even["table_b0_origin_pc"] == str(0x100)
        assert even["table_b2_origin_pc"] == str(0x101)

        assert odd["tile0_raw_address"] == str(0x2012)
        assert odd["tile1_raw_address"] == str(0x2012)
        assert odd["tile0_raw_value"] == str(0x6655)
        assert odd["tile1_raw_value"] == str(0x8877)
        assert odd["row_b0_origin_pc"] == str(0x210)

        assert color["tile1_contributes"] == "1"
        assert color["contributing_raw_lines"] == (
            f"{color['tile0_raw_line']};{color['tile1_raw_line']}"
        )
        assert color["row_b2_origin_pc"] == str(0x221)
        assert color["row_b2_origin_pc"] != str(0x888)

        wrap_trace = root / "wrapped-y.csv"
        write_trace(wrap_trace, wrapped_y_rows())
        wrap_output = io.StringIO()
        wrap_counts = correlate(
            wrap_trace, wrap_output, require_complete_coverage=True
        )
        assert wrap_counts["sprite_rows"] == 1
        wrap_record = next(csv.DictReader(io.StringIO(wrap_output.getvalue())))
        assert wrap_record["sprite_line_y"] == "0"
        assert wrap_record["tile_row"] == "2"

        repeated_line_trace = root / "repeated-line-after-table-refresh.csv"
        write_trace(
            repeated_line_trace, repeated_line_after_table_refresh_rows()
        )
        repeated_line_counts = correlate(
            repeated_line_trace, io.StringIO(), require_complete_coverage=True
        )
        assert repeated_line_counts["sprite_rows"] == 2

        interleaved_table_trace = root / "interleaved-table-same-line-epoch.csv"
        interleaved_table_rows = copy.deepcopy(rows)
        second_tile = next(
            index
            for index, row in enumerate(interleaved_table_rows)
            if row["event"] == "vram"
            and row["role"] == "sprite_tile"
            and row["cycle"] == 20
        )
        interleaved_table_rows[second_tile:second_tile] = table_reads(15, 0x1100, 0)
        write_trace(interleaved_table_trace, interleaved_table_rows)
        interleaved_counts = correlate(
            interleaved_table_trace,
            io.StringIO(),
            require_complete_coverage=True,
        )
        assert interleaved_counts["sprite_rows"] == 3
        assert interleaved_counts["raw_table_groups"] == 5
        assert interleaved_counts["raw_table_unused"] == 2

        epoch_rollback = root / "line-epoch-rollback.csv"
        epoch_rollback_rows = changed(
            repeated_line_after_table_refresh_rows(),
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 11,
            sprite_line_epoch=4,
        )
        write_trace(epoch_rollback, epoch_rollback_rows)
        expect_error(epoch_rollback, "line epoch moved backwards from 4 to 3")

        same_epoch_line_change = root / "same-epoch-line-change.csv"
        same_epoch_line_change_rows = changed(
            rows,
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 22,
            sprite_line_y=21,
            tile_row=2,
            tile_row_address=0x2014,
        )
        write_trace(same_epoch_line_change, same_epoch_line_change_rows)
        expect_error(same_epoch_line_change, "changed target line from 20 to 21")

        missing_epoch_start = root / "missing-line-epoch-start.csv"
        missing_epoch_start_rows = changed(
            rows,
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 22,
            sprite_line_epoch=1,
        )
        write_trace(missing_epoch_start, missing_epoch_start_rows)
        expect_error(missing_epoch_start, "line epoch 1 must start at slot 0")

        identical_refresh_trace = root / "identical-descriptor-refresh.csv"
        write_trace(
            identical_refresh_trace, identical_descriptor_refresh_rows()
        )
        identical_refresh_output = io.StringIO()
        identical_refresh_counts = correlate(
            identical_refresh_trace,
            identical_refresh_output,
            require_complete_coverage=True,
        )
        assert identical_refresh_counts["raw_table_groups"] == 2
        assert identical_refresh_counts["raw_table_unused"] == 1
        identical_refresh_record = next(
            csv.DictReader(io.StringIO(identical_refresh_output.getvalue()))
        )
        assert identical_refresh_record["table_group_index"] == "0"
        assert identical_refresh_record["table_b0_origin_pc"] == str(0x500)
        assert identical_refresh_record["table_b0_origin_pc"] != str(0x900)

        wrong_refresh_generation = root / "wrong-refresh-generation.csv"
        wrong_refresh_generation_rows = changed(
            identical_descriptor_refresh_rows(),
            lambda row: row["event"] == "sprite_row",
            sprite_table_generation=1,
        )
        write_trace(wrong_refresh_generation, wrong_refresh_generation_rows)
        expect_error(
            wrong_refresh_generation,
            "does not match its exact raw table generation",
        )

        full_slot_trace = root / "full-slot-line.csv"
        write_trace(full_slot_trace, full_slot_line_rows())
        full_slot_output = io.StringIO()
        full_slot_counts = correlate(
            full_slot_trace, full_slot_output, require_complete_coverage=True
        )
        full_slot_records = list(
            csv.DictReader(io.StringIO(full_slot_output.getvalue()))
        )
        assert full_slot_counts["sprite_rows"] == 32
        assert [int(row["sprite_line_slot"]) for row in full_slot_records] == list(
            range(32)
        )

        cpu_trace = root / "cpu-copy.csv"
        write_trace(cpu_trace, cpu_copy_rows())
        cpu_output = io.StringIO()
        cpu_counts = correlate(cpu_trace, cpu_output, require_complete_coverage=True)
        assert cpu_counts["cpu_rom_movsb_rows"] == 1
        assert cpu_counts["cpu_rom_movsb_bytes"] == 2
        assert cpu_counts["cpu_rom_movsb_origins"] == 1
        cpu_record = next(csv.DictReader(io.StringIO(cpu_output.getvalue())))
        assert cpu_record["row_source_summary"] == "cpu_rom_movsb"
        assert cpu_record["row_b0_source_offset"] == str(0x200)
        assert cpu_record["row_b1_source_offset"] == str(0x201)

        no_manifest = root / "no-manifest.csv"
        write_trace(no_manifest, rows, manifest=False)
        expect_error(no_manifest, "does not prove complete", complete=True)
        observed = io.StringIO()
        correlate(no_manifest, observed)
        assert next(csv.DictReader(io.StringIO(observed.getvalue())))[
            "coverage_status"
        ] == "observed_only"

        incomplete = root / "incomplete.csv"
        write_trace(incomplete, rows, complete=False)
        expect_error(incomplete, "does not prove complete", complete=True)

        wrong_table = root / "wrong-table.csv"
        wrong_table_rows = changed(
            rows,
            lambda row: row["event"] == "vram"
            and row["role"] == "sprite_table"
            and row["address"] == 0x1000,
            fetch_value=0x0009,
        )
        write_trace(wrong_table, wrong_table_rows)
        expect_error(wrong_table, "atomic sprite descriptor")

        overlapping_table = root / "overlapping-table-generation.csv"
        overlapping_table_rows = copy.deepcopy(rows)
        first_tile = next(
            index
            for index, row in enumerate(overlapping_table_rows)
            if row["event"] == "vram"
            and row["role"] == "sprite_tile"
            and row["cycle"] == 10
        )
        overlapping_table_rows[first_tile:first_tile] = table_reads(
            9, 0x1000, descriptor(9, 0, 99)
        )
        write_trace(overlapping_table, overlapping_table_rows)
        overlapping_output = io.StringIO()
        overlapping_counts = correlate(overlapping_table, overlapping_output)
        assert overlapping_counts["raw_table_groups"] == 5
        assert overlapping_counts["raw_table_unused"] == 2
        assert next(csv.DictReader(io.StringIO(overlapping_output.getvalue())))[
            "table_group_index"
        ] == "0"

        wrong_even_second = root / "wrong-even-second.csv"
        wrong_even_rows = changed(
            rows,
            lambda row: row["event"] == "vram"
            and row["role"] == "sprite_tile"
            and row["cycle"] == 10
            and row["address"] == 0x2002,
            address=0x2000,
        )
        write_trace(wrong_even_second, wrong_even_rows)
        expect_error(wrong_even_second, "second-read address")

        wrong_odd_second = root / "wrong-odd-second.csv"
        wrong_odd_rows = changed(
            rows,
            lambda row: row["event"] == "vram"
            and row["role"] == "sprite_tile"
            and row["cycle"] == 21,
            address=0x2014,
        )
        write_trace(wrong_odd_second, wrong_odd_rows)
        expect_error(wrong_odd_second, "second-read address")

        same_cycle_tile = root / "same-cycle-tile-handoff.csv"
        same_cycle_tile_rows = changed(
            rows,
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 11,
            cycle=10,
        )
        write_trace(same_cycle_tile, same_cycle_tile_rows)
        expect_error(same_cycle_tile, "follow the second raw tile read by exactly one cycle")

        late_tile = root / "late-tile-handoff.csv"
        late_tile_rows = changed(
            rows,
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 11,
            cycle=12,
        )
        write_trace(late_tile, late_tile_rows)
        expect_error(late_tile, "follow the second raw tile read by exactly one cycle")

        nonzero_start = root / "nonzero-slot-start.csv"
        nonzero_start_rows = changed(
            rows,
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 11,
            sprite_line_slot=1,
        )
        write_trace(nonzero_start, nonzero_start_rows)
        expect_error(nonzero_start, "must start at slot 0, got 1")

        slot_gap = root / "slot-gap.csv"
        slot_gap_rows = changed(
            rows,
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 22,
            sprite_line_slot=2,
        )
        write_trace(slot_gap, slot_gap_rows)
        expect_error(slot_gap, "expected contiguous slot 1, got 2")

        duplicate_slot = root / "duplicate-or-reordered-slot.csv"
        duplicate_slot_rows = changed(
            rows,
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 32,
            sprite_line_slot=1,
        )
        write_trace(duplicate_slot, duplicate_slot_rows)
        expect_error(duplicate_slot, "expected contiguous slot 2, got 1")

        same_cycle_table = root / "same-cycle-table-handoff.csv"
        same_cycle_table_rows = changed(
            cpu_copy_rows(),
            lambda row: row["event"] == "vram"
            and row["role"] == "sprite_table"
            and row["address"] == 0x1002,
            cycle=10,
        )
        same_cycle_table_rows.sort(key=lambda row: int(row["cycle"]))
        write_trace(same_cycle_table, same_cycle_table_rows)
        expect_error(same_cycle_table, "descriptor must be fetched before")

        color_collision = root / "color-collision.csv"
        color_collision_rows = changed(
            rows,
            lambda row: row["event"] == "vram"
            and row["role"] == "sprite_tile"
            and row["cycle"] == 31,
            fetch_collision=1,
        )
        color_collision_rows = changed(
            color_collision_rows,
            lambda row: row["event"] == "sprite_row" and row["cycle"] == 32,
            tile_row_collision=1,
        )
        write_trace(color_collision, color_collision_rows)
        expect_error(color_collision, "contributing sprite fetch collided")

        no_table = root / "no-table.csv"
        no_table_rows = [
            row
            for row in rows
            if not (
                row["event"] == "vram"
                and row["role"] == "sprite_table"
                and row["address"] in {0x1000, 0x1002}
            )
        ]
        write_trace(no_table, no_table_rows)
        expect_error(no_table, "does not match its exact raw table generation")

        v5 = root / "v5.csv"
        with v5.open("w", newline="", encoding="utf-8") as output_file:
            csv.DictWriter(output_file, fieldnames=FIELDS_V5).writeheader()
        expect_error(v5, "exact v6 header")

        assert expected_count("sprite_rows=0x3") == ("sprite_rows", 3)
        assert {
            "descriptor_cpu_exact",
            "row_cpu_exact",
            "row_gdma",
            "row_source_gdma_rom",
            "descriptor_collision",
            "row_collision",
        } <= COUNT_NAMES
        try:
            expected_count("bogus=1")
        except argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError("unknown count name was accepted")

        audit_path = root / "audit.csv"
        command = [
            sys.executable,
            str(Path(__file__).with_name("correlate_sprite_rows.py")),
            str(trace),
            "--output",
            str(audit_path),
            "--require-complete-coverage",
            "--expect-count",
            "sprite_rows=3",
            "--expect-count",
            "descriptor_cpu_exact=3",
            "--expect-count",
            "row_collision=0",
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        assert completed.returncode == 0, completed.stderr
        failed = subprocess.run(
            [*command, "--expect-count", "sprite_rows=4"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert failed.returncode != 0
        assert "expected sprite_rows=4, got 3" in failed.stderr

    print("PASS atomic sprite-row correlator")


if __name__ == "__main__":
    main()
