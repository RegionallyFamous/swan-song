#!/usr/bin/env python3
"""Correlate v5 atomic background cells with their raw reads and IRAM writers.

Every atomic cell must have an exact completed raw group. Raw groups may remain
unpromoted when a disabled layer replaces its prefetch buffer or when capture
ends with display read-ahead in flight; those outcomes are counted explicitly.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

from correlate_provenance import (
    ByteVersion,
    MemorySourceTracker,
    POWERUP_ZERO,
    ROM_SPACES,
    TraceRow,
    byte_fields,
    summarize_versions,
    source_lane,
    trace_fnv1a64,
)
from verify_trace import BG_FIELDS as BG_CELL_FIELDS
from verify_trace import FIELDS_V5


BYTE_SUFFIXES = (
    "value",
    "write_line",
    "write_cycle",
    "initiator",
    "instruction_id",
    "origin_pc",
    "source_space",
    "source_offset",
    "source_read_cycle",
)
BYTE_PREFIXES = ("map_lo", "map_hi", "row_b0", "row_b1", "row_b2", "row_b3")
OUTPUT_FIELDS = [
    "cell_index",
    "line",
    "cycle",
    "bg_layer",
    "map_x",
    "map_y",
    "map_address",
    "map_value",
    "tile_bank_enabled",
    "tile_index",
    "palette",
    "hflip",
    "vflip",
    "bpp",
    "packed",
    "tile_row",
    "tile_row_address",
    "tile_row_bytes",
    "tile_row_value",
    "map_collision",
    "tile_row_collision",
    "coverage_status",
    "map_raw_line",
    "map_raw_cycle",
    "map_raw_collision",
    "map_scoreboard_status",
    "map_writer_summary",
    "map_source_summary",
    "tile0_raw_line",
    "tile0_raw_cycle",
    "tile0_raw_address",
    "tile0_raw_value",
    "tile0_raw_collision",
    "tile1_raw_line",
    "tile1_raw_cycle",
    "tile1_raw_address",
    "tile1_raw_value",
    "tile1_raw_collision",
    "contributing_raw_lines",
    "contributing_raw_cycles",
    "row_scoreboard_status",
    "row_writer_summary",
    "row_source_summary",
    *[f"{prefix}_{suffix}" for prefix in BYTE_PREFIXES for suffix in BYTE_SUFFIXES],
]


@dataclass(frozen=True)
class FetchSnapshot:
    row: TraceRow
    address: int
    value: int
    collision: int
    low: ByteVersion | None
    high: ByteVersion | None
    scoreboard_status: str
    writer_summary: str
    source_summary: str


@dataclass
class FetchGroup:
    layer: str
    map_fetch: FetchSnapshot
    tile_fetches: list[FetchSnapshot]


def read_manifest(trace: Path) -> tuple[str, list[ByteVersion | None]]:
    path = Path(f"{trace}.manifest.json")
    if not path.exists():
        return "observed_only", [None] * 0x10000
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        binding_matches = (
            manifest.get("trace_size_bytes") == trace.stat().st_size
            and manifest.get("trace_fnv1a64") == trace_fnv1a64(trace)
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {path}: {error}") from error
    events = manifest.get("events")
    positive = lambda value: (
        isinstance(value, int) and not isinstance(value, bool) and value > 0
    )
    complete = (
        manifest.get("schema") == "swan-song-trace-manifest-v1"
        and manifest.get("trace_schema") == 5
        and binding_matches
        and manifest.get("capture_start") == "reset_release"
        and manifest.get("capture_completed") is True
        and positive(manifest.get("capture_cycles"))
        and positive(manifest.get("completed_frames"))
        and positive(manifest.get("rom_size"))
        and manifest.get("complete_memory_history") is True
        and manifest.get("complete_display_history") is True
        and manifest.get("complete_bg_cell_history") is True
        and manifest.get("memory_filters_active") is False
        and manifest.get("display_filters_active") is False
        and isinstance(events, dict)
        and events.get("mem") is True
        and events.get("vram") is True
        and events.get("bg_cell") is True
        and manifest.get("savestate_inputs_asserted") is False
        and manifest.get("iram_initial_state") == "zero"
    )
    if complete:
        return "complete_from_reset", [POWERUP_ZERO] * 0x10000
    return "observed_only", [None] * 0x10000


def iter_rows(source: TextIO) -> Iterable[TraceRow]:
    reader = csv.DictReader(source)
    if reader.fieldnames != FIELDS_V5:
        raise ValueError(
            "background-cell correlation requires exact v5 header, "
            f"got {reader.fieldnames!r}"
        )
    previous_cycle = -1
    for line, values in enumerate(reader, start=2):
        try:
            cycle = int(values["cycle"])
        except ValueError as error:
            raise ValueError(f"line {line}: invalid cycle") from error
        if cycle < previous_cycle:
            raise ValueError(f"line {line}: cycles are not monotonic")
        previous_cycle = cycle
        yield TraceRow(line, values)


def decimal(row: TraceRow, field: str, maximum: int) -> int:
    try:
        value = int(row.values[field])
    except ValueError as error:
        raise ValueError(f"line {row.line}: invalid {field}") from error
    if not 0 <= value <= maximum:
        raise ValueError(f"line {row.line}: {field} outside 0..{maximum}")
    return value


def layer_name(row: TraceRow) -> str:
    value = decimal(row, "bg_layer", 2)
    if value not in (1, 2):
        raise ValueError(f"line {row.line}: bg_layer must be 1 or 2")
    return f"screen{value}"


def snapshot_fetch(row: TraceRow, iram: list[ByteVersion | None]) -> FetchSnapshot:
    address = decimal(row, "address", 0xFFFF)
    if address & 1 or address == 0xFFFF:
        raise ValueError(f"line {row.line}: invalid display word address")
    value = decimal(row, "fetch_value", 0xFFFF)
    collision = decimal(row, "fetch_collision", 1)
    low, high = iram[address], iram[address + 1]
    ram_status, writer_summary, source_summary = summarize_versions(low, high)
    del ram_status
    reconstructed = None if low is None or high is None else low.value | (high.value << 8)
    if collision:
        status = "unspecified_collision"
    elif reconstructed is None:
        status = "unobserved" if low is None and high is None else "partial"
    elif reconstructed == value:
        status = "match"
    else:
        status = "mismatch"
    return FetchSnapshot(
        row, address, value, collision, low, high, status, writer_summary, source_summary
    )


def summarize_row(versions: list[ByteVersion | None]) -> tuple[str, str, str]:
    if all(version is None for version in versions):
        return "unobserved", "none_observed", "none_observed"
    if any(version is None for version in versions):
        return "partial", "partial", "partial"
    known = [version for version in versions if version is not None]
    if all(version.write is None for version in known):
        return "match", "initial_powerup", "initial_powerup"
    writes = [version.write for version in known if version.write is not None]
    initiators = {write.values["initiator"] for write in writes}
    origins = {write.values["origin_status"] for write in writes}
    if initiators == {"cpu"}:
        writer = "cpu_exact" if origins == {"exact"} else "cpu_unattributed"
    elif len(initiators) == 1:
        writer = next(iter(initiators))
    else:
        writer = "mixed"
    sources = [version.source_read for version in known]
    known_sources = [source for source in sources if source is not None]
    source_initiators = {source.values["initiator"] for source in known_sources}
    if all(source is None for source in sources):
        source_summary = "cpu_write" if initiators == {"cpu"} else "none"
    elif all(source is not None and source.values["space"] in ROM_SPACES for source in sources):
        if source_initiators == {"cpu"}:
            source_summary = "cpu_rom_movsb"
        elif source_initiators == {"gdma"}:
            source_summary = "gdma_rom"
        else:
            source_summary = "mixed_or_partial_sources"
    elif any(source is not None for source in sources):
        source_summary = "mixed_or_partial_sources"
    else:
        source_summary = "none"
    return "match", writer, source_summary


def check_snapshot(snapshot: FetchSnapshot) -> None:
    if snapshot.collision:
        raise ValueError(f"line {snapshot.row.line}: raw display fetch collided with an IRAM write")
    if snapshot.scoreboard_status == "mismatch":
        raise ValueError(f"line {snapshot.row.line}: raw display value disagrees with IRAM scoreboard")


def validate_cell(row: TraceRow, group: FetchGroup) -> tuple[list[FetchSnapshot], list[ByteVersion | None]]:
    map_address = decimal(row, "map_address", 0xFFFF)
    map_value = decimal(row, "map_value", 0xFFFF)
    map_collision = decimal(row, "map_collision", 1)
    if (group.map_fetch.address, group.map_fetch.value, group.map_fetch.collision) != (
        map_address,
        map_value,
        map_collision,
    ):
        raise ValueError(f"line {row.line}: atomic map fields do not match the preceding raw map fetch")

    bank_enabled = decimal(row, "tile_bank_enabled", 1)
    expected_index = (map_value & 0x1FF) | (((map_value >> 13) & 1) << 9 if bank_enabled else 0)
    decoded = {
        "tile_index": expected_index,
        "palette": (map_value >> 9) & 0xF,
        "hflip": (map_value >> 14) & 1,
        "vflip": (map_value >> 15) & 1,
    }
    maxima = {"tile_index": 0x3FF, "palette": 0xF, "hflip": 1, "vflip": 1}
    for field, expected in decoded.items():
        if decimal(row, field, maxima[field]) != expected:
            raise ValueError(f"line {row.line}: {field} is inconsistent with map_value")

    expected_x = (map_address >> 1) & 0x1F
    expected_y = (map_address >> 6) & 0x1F
    if (
        decimal(row, "map_x", 0x1F),
        decimal(row, "map_y", 0x1F),
    ) != (expected_x, expected_y):
        raise ValueError(
            f"line {row.line}: map coordinates are inconsistent with map_address"
        )

    bpp = decimal(row, "bpp", 4)
    if bpp not in (2, 4):
        raise ValueError(f"line {row.line}: bpp must be 2 or 4")
    decimal(row, "packed", 1)
    tile_row = decimal(row, "tile_row", 7)
    row_address = decimal(row, "tile_row_address", 0xFFFF)
    row_bytes = decimal(row, "tile_row_bytes", 4)
    row_value = decimal(row, "tile_row_value", 0xFFFFFFFF)
    row_collision = decimal(row, "tile_row_collision", 1)
    if row_bytes != bpp:
        raise ValueError(f"line {row.line}: tile_row_bytes must equal bpp")
    expected_row_address = (
        (0x2000 if bpp == 2 else 0x4000)
        + expected_index * row_bytes * 8
        + tile_row * row_bytes
    )
    if row_address != expected_row_address:
        raise ValueError(
            f"line {row.line}: tile_row_address is inconsistent with decoded cell"
        )

    tile0, tile1 = group.tile_fetches
    if tile0.address & 3 or tile1.address != tile0.address + 2:
        raise ValueError(f"line {row.line}: raw tile words are not one aligned four-byte fetch group")
    if bpp == 2:
        selected = [fetch for fetch in group.tile_fetches if fetch.address == row_address]
        if len(selected) != 1:
            raise ValueError(f"line {row.line}: 2bpp row does not select exactly one raw tile word")
        contributing = selected
        expected_value = selected[0].value
        expected_collision = selected[0].collision
    else:
        if row_address != tile0.address:
            raise ValueError(f"line {row.line}: 4bpp row does not start at the first raw tile word")
        contributing = [tile0, tile1]
        expected_value = tile0.value | (tile1.value << 16)
        expected_collision = tile0.collision | tile1.collision
    if row_value != expected_value or row_collision != expected_collision:
        raise ValueError(f"line {row.line}: atomic tile-row fields do not match raw tile fetches")

    # The aligned neighbor word is fetched by the existing BG engine even in
    # 2bpp, but it cannot contribute pixels for this row. Its uncertainty must
    # not taint otherwise exact cell provenance.
    for snapshot in [group.map_fetch, *contributing]:
        check_snapshot(snapshot)
    if map_collision or row_collision:
        raise ValueError(f"line {row.line}: atomic background cell contains a read/write collision")
    versions = [version for fetch in contributing for version in (fetch.low, fetch.high)]
    return contributing, versions


def correlate(
    trace: Path,
    output: TextIO,
    require_complete_coverage: bool = False,
) -> dict[str, int]:
    coverage_status, iram = read_manifest(trace)
    if require_complete_coverage and coverage_status != "complete_from_reset":
        raise ValueError("trace manifest does not prove complete mem+vram+bg_cell history from reset")

    writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    counts = {
        "cells": 0,
        "screen1": 0,
        "screen2": 0,
        "bpp2": 0,
        "bpp4": 0,
        "raw_superseded": 0,
        "raw_unpromoted": 0,
        "raw_inflight": 0,
        "cpu_rom_movsb_cells": 0,
        "cpu_rom_movsb_bytes": 0,
        "cpu_rom_movsb_origins": 0,
    }
    building: dict[str, FetchGroup | None] = {"screen1": None, "screen2": None}
    completed: dict[str, deque[FetchGroup]] = {"screen1": deque(), "screen2": deque()}
    source_tracker = MemorySourceTracker()

    with trace.open(newline="", encoding="utf-8") as source:
        for cycle, rows_iter in itertools.groupby(iter_rows(source), key=lambda item: item.cycle):
            rows = list(rows_iter)

            # The DPRAM value and its writer snapshot both precede any write on
            # this edge. Process all raw reads before same-cycle memory events.
            for row in (item for item in rows if item.values["event"] == "vram"):
                role = row.values["role"]
                if role not in {"screen1_map", "screen1_tile", "screen2_map", "screen2_tile"}:
                    continue
                layer, kind = role.split("_", 1)
                snapshot = snapshot_fetch(row, iram)
                if kind == "map":
                    if building[layer] is not None:
                        raise ValueError(
                            f"line {row.line}: new {layer} map before prior raw group completed"
                        )
                    building[layer] = FetchGroup(layer, snapshot, [])
                else:
                    group = building[layer]
                    if group is None:
                        raise ValueError(f"line {row.line}: {layer} tile fetch has no preceding map")
                    group.tile_fetches.append(snapshot)
                    if len(group.tile_fetches) == 2:
                        completed[layer].append(group)
                        building[layer] = None
                    elif len(group.tile_fetches) > 2:
                        raise ValueError(f"line {row.line}: too many tile words in {layer} raw group")

            for row in (item for item in rows if item.values["event"] == "bg_cell"):
                layer = layer_name(row)
                if not completed[layer]:
                    raise ValueError(
                        f"line {row.line}: {layer} atomic cell has no completed raw fetch group"
                    )
                # gpu_bg continues fetching and replacing its completed buffer
                # while a layer is disabled, but emits no cell event until a
                # buffer is promoted after enable.  Older completed groups are
                # therefore superseded, not pending FIFO entries.  The newest
                # group is the one held by the RTL at this promotion edge.
                group = completed[layer].pop()
                counts["raw_superseded"] += len(completed[layer])
                completed[layer].clear()
                contributing, versions = validate_cell(row, group)
                row_status, row_writer, row_source = summarize_row(versions)
                map_fetch = group.map_fetch
                tile0, tile1 = group.tile_fetches
                record: dict[str, object] = {
                    "cell_index": counts["cells"],
                    "line": row.line,
                    "cycle": cycle,
                    "bg_layer": layer,
                    "coverage_status": coverage_status,
                    "map_raw_line": map_fetch.row.line,
                    "map_raw_cycle": map_fetch.row.cycle,
                    "map_raw_collision": map_fetch.collision,
                    "map_scoreboard_status": map_fetch.scoreboard_status,
                    "map_writer_summary": map_fetch.writer_summary,
                    "map_source_summary": map_fetch.source_summary,
                    "tile0_raw_line": tile0.row.line,
                    "tile0_raw_cycle": tile0.row.cycle,
                    "tile0_raw_address": tile0.address,
                    "tile0_raw_value": tile0.value,
                    "tile0_raw_collision": tile0.collision,
                    "tile1_raw_line": tile1.row.line,
                    "tile1_raw_cycle": tile1.row.cycle,
                    "tile1_raw_address": tile1.address,
                    "tile1_raw_value": tile1.value,
                    "tile1_raw_collision": tile1.collision,
                    "contributing_raw_lines": ";".join(str(fetch.row.line) for fetch in contributing),
                    "contributing_raw_cycles": ";".join(str(fetch.row.cycle) for fetch in contributing),
                    "row_scoreboard_status": row_status,
                    "row_writer_summary": row_writer,
                    "row_source_summary": row_source,
                }
                for field in BG_CELL_FIELDS:
                    if field != "bg_layer":
                        record[field] = row.values[field]
                record.update(byte_fields("map_lo", map_fetch.low, map_fetch.address))
                record.update(byte_fields("map_hi", map_fetch.high, map_fetch.address + 1))
                padded = [*versions, None, None, None, None][:4]
                for index, version in enumerate(padded):
                    record.update(
                        byte_fields(
                            f"row_b{index}",
                            version,
                            decimal(row, "tile_row_address", 0xFFFF) + index,
                        )
                    )
                writer.writerow(record)
                counts["cells"] += 1
                counts[layer] += 1
                counts[f"bpp{row.values['bpp']}"] += 1
                if row_source == "cpu_rom_movsb":
                    counts["cpu_rom_movsb_cells"] += 1

            for row in (item for item in rows if item.values["event"] == "mem"):
                values = row.values
                access = values["access"]
                source_read = source_tracker.observe(row)
                if access != "write" or values["space"] != "iram":
                    continue
                address = decimal(row, "address", 0xFFFF)
                byte_enable = decimal(row, "byte_enable", 3)
                value = decimal(row, "value", 0xFFFF)
                for lane in (0, 1):
                    if byte_enable & (1 << lane):
                        target = address + lane
                        if target > 0xFFFF:
                            raise ValueError(f"line {row.line}: IRAM write crosses 0xffff")
                        iram[target] = ByteVersion(
                            (value >> (8 * lane)) & 0xFF,
                            row,
                            source_read,
                            source_lane(source_read, lane),
                        )

    for layer in ("screen1", "screen2"):
        if building[layer] is not None:
            # Starting the next fetch means every older completed buffer was
            # already advanced while no enabled cell event was emitted.
            counts["raw_superseded"] += len(completed[layer])
            counts["raw_inflight"] += 1
        elif completed[layer]:
            # Only the newest FETCHDONE buffer is still awaiting promotion.
            counts["raw_superseded"] += len(completed[layer]) - 1
            counts["raw_unpromoted"] += 1
    counts["cpu_rom_movsb_bytes"] = source_tracker.cpu_rom_movsb_bytes
    counts["cpu_rom_movsb_origins"] = len(source_tracker.cpu_rom_movsb_origins)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete-coverage", action="store_true")
    args = parser.parse_args()
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as output:
            counts = correlate(args.trace, output, args.require_complete_coverage)
    except (OSError, ValueError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    print(f"PASS {args.trace} " + " ".join(f"{key}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    main()
