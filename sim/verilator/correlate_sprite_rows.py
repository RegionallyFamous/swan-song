#!/usr/bin/env python3
"""Correlate v6 atomic sprite rows with raw VRAM reads and IRAM writers.

Sprite descriptors are loaded by an earlier two-word DMA and may be reused for
many scanlines.  Pixel rows are fetched as a two-read stream immediately before
an atomic ``sprite_row`` event.  In 2bpp the second tile read is synchronization
traffic only: it is audited, but it cannot contribute data, collision state, or
writer uncertainty to the promoted row.
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

from frame_manifest import accepts_complete_schema
from correlate_provenance import (
    ByteVersion,
    MemorySourceTracker,
    POWERUP_ZERO,
    ROM_SPACES,
    TraceRow,
    byte_fields,
    source_lane,
    trace_fnv1a64,
)
from verify_trace import FIELDS_V6, SPRITE_FIELDS


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
BYTE_PREFIXES = (
    "table_b0",
    "table_b1",
    "table_b2",
    "table_b3",
    "row_b0",
    "row_b1",
    "row_b2",
    "row_b3",
)
ATOMIC_TILE_FIELDS = (
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
    "tile_row_collision",
)
OUTPUT_FIELDS = [
    "sprite_row_index",
    "line",
    "cycle",
    *SPRITE_FIELDS,
    *ATOMIC_TILE_FIELDS,
    "coverage_status",
    "table_group_index",
    "table0_raw_line",
    "table0_raw_cycle",
    "table0_raw_address",
    "table0_raw_value",
    "table0_raw_collision",
    "table0_scoreboard_status",
    "table1_raw_line",
    "table1_raw_cycle",
    "table1_raw_address",
    "table1_raw_value",
    "table1_raw_collision",
    "table1_scoreboard_status",
    "table_scoreboard_status",
    "table_writer_summary",
    "table_source_summary",
    "tile_group_index",
    "tile0_raw_line",
    "tile0_raw_cycle",
    "tile0_raw_address",
    "tile0_raw_value",
    "tile0_raw_collision",
    "tile0_scoreboard_status",
    "tile1_raw_line",
    "tile1_raw_cycle",
    "tile1_raw_address",
    "tile1_raw_value",
    "tile1_raw_collision",
    "tile1_scoreboard_status",
    "tile1_contributes",
    "contributing_raw_lines",
    "contributing_raw_cycles",
    "row_scoreboard_status",
    "row_writer_summary",
    "row_source_summary",
    *[f"{prefix}_{suffix}" for prefix in BYTE_PREFIXES for suffix in BYTE_SUFFIXES],
]

COUNT_NAMES = {
    "sprite_rows",
    "bpp2",
    "bpp4",
    "packed",
    "planar",
    "raw_table_groups",
    "raw_table_unused",
    "raw_tile_groups",
    "raw_tile_unpromoted",
    "raw_table_inflight",
    "raw_tile_inflight",
    "descriptor_cpu_exact",
    "row_cpu_exact",
    "row_gdma",
    "row_source_gdma_rom",
    "descriptor_collision",
    "row_collision",
    "cpu_rom_movsb_rows",
    "cpu_rom_movsb_bytes",
    "cpu_rom_movsb_origins",
}


@dataclass(frozen=True)
class FetchSnapshot:
    row: TraceRow
    address: int
    value: int
    collision: int
    low: ByteVersion | None
    high: ByteVersion | None
    scoreboard_status: str


@dataclass
class FetchGroup:
    index: int
    first: FetchSnapshot
    second: FetchSnapshot
    references: int = 0

    @property
    def value(self) -> int:
        return self.first.value | (self.second.value << 16)

    @property
    def collision(self) -> int:
        return self.first.collision | self.second.collision


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
        accepts_complete_schema(manifest, path, trace)
        and manifest.get("trace_schema") == 6
        and binding_matches
        and manifest.get("capture_start") == "reset_release"
        and manifest.get("capture_completed") is True
        and positive(manifest.get("capture_cycles"))
        and positive(manifest.get("completed_frames"))
        and positive(manifest.get("rom_size"))
        and manifest.get("complete_memory_history") is True
        and manifest.get("complete_display_history") is True
        and manifest.get("complete_sprite_row_history") is True
        and manifest.get("memory_filters_active") is False
        and manifest.get("display_filters_active") is False
        and isinstance(events, dict)
        and events.get("mem") is True
        and events.get("vram") is True
        and events.get("sprite_row") is True
        and manifest.get("savestate_inputs_asserted") is False
        and manifest.get("iram_initial_state") == "zero"
    )
    if complete:
        return "complete_from_reset", [POWERUP_ZERO] * 0x10000
    return "observed_only", [None] * 0x10000


def iter_rows(source: TextIO) -> Iterable[TraceRow]:
    reader = csv.DictReader(source)
    if reader.fieldnames != FIELDS_V6:
        raise ValueError(
            "sprite-row correlation requires exact v6 header, "
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


def snapshot_fetch(row: TraceRow, iram: list[ByteVersion | None]) -> FetchSnapshot:
    address = decimal(row, "address", 0xFFFF)
    if address & 1 or address == 0xFFFF:
        raise ValueError(f"line {row.line}: invalid display word address")
    value = decimal(row, "fetch_value", 0xFFFF)
    collision = decimal(row, "fetch_collision", 1)
    low, high = iram[address], iram[address + 1]
    reconstructed = None if low is None or high is None else low.value | (high.value << 8)
    if collision:
        status = "unspecified_collision"
    elif reconstructed is None:
        status = "unobserved" if low is None and high is None else "partial"
    elif reconstructed == value:
        status = "match"
    else:
        status = "mismatch"
    return FetchSnapshot(row, address, value, collision, low, high, status)


def summarize_group(
    versions: list[ByteVersion | None],
) -> tuple[str, str, str]:
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
    elif all(
        source is not None and source.values["space"] in ROM_SPACES
        for source in sources
    ):
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


def check_contributing(snapshot: FetchSnapshot) -> None:
    if snapshot.collision:
        raise ValueError(
            f"line {snapshot.row.line}: contributing sprite fetch collided with an IRAM write"
        )
    if snapshot.scoreboard_status == "mismatch":
        raise ValueError(
            f"line {snapshot.row.line}: contributing sprite value disagrees with IRAM scoreboard"
        )


def validate_table_group(row: TraceRow, group: FetchGroup) -> list[ByteVersion | None]:
    address = decimal(row, "sprite_table_address", 0xFFFF)
    value = decimal(row, "sprite_table_value", 0xFFFFFFFF)
    collision = decimal(row, "sprite_table_collision", 1)
    if group.first.address & 3 or group.second.address != group.first.address + 2:
        raise ValueError(
            f"line {row.line}: cached sprite table group is not one aligned descriptor"
        )
    if group.second.row.cycle >= row.cycle:
        raise ValueError(
            f"line {row.line}: cached sprite descriptor must be fetched before "
            "the atomic handoff"
        )
    if (group.first.address, group.value, group.collision) != (address, value, collision):
        raise ValueError(
            f"line {row.line}: atomic sprite descriptor does not match its exact raw table generation"
        )
    check_contributing(group.first)
    check_contributing(group.second)
    if collision:
        raise ValueError(f"line {row.line}: atomic sprite descriptor contains a collision")
    return [group.first.low, group.first.high, group.second.low, group.second.high]


def validate_atomic_decode(
    row: TraceRow,
) -> tuple[int, int, int, int, int, int, int]:
    table_address = decimal(row, "sprite_table_address", 0xFFFF)
    if table_address & 3:
        raise ValueError(f"line {row.line}: sprite table address is not 4-byte aligned")
    table_value = decimal(row, "sprite_table_value", 0xFFFFFFFF)
    line_y = decimal(row, "sprite_line_y", 0xFF)
    line_slot = decimal(row, "sprite_line_slot", 31)
    table_generation = decimal(row, "sprite_table_generation", 0xFFFFFFFF)
    line_epoch = decimal(row, "sprite_line_epoch", 0xFFFFFFFF)
    tile_index = decimal(row, "tile_index", 0x1FF)
    palette = decimal(row, "palette", 15)
    hflip = decimal(row, "hflip", 1)
    vflip = decimal(row, "vflip", 1)
    bpp = decimal(row, "bpp", 4)
    if bpp not in (2, 4):
        raise ValueError(f"line {row.line}: bpp must be 2 or 4")
    decimal(row, "packed", 1)
    tile_row = decimal(row, "tile_row", 7)
    row_address = decimal(row, "tile_row_address", 0xFFFF)
    row_bytes = decimal(row, "tile_row_bytes", 4)
    row_value = decimal(row, "tile_row_value", 0xFFFFFFFF)
    decimal(row, "tile_row_collision", 1)

    expected_decode = (
        table_value & 0x1FF,
        8 | ((table_value >> 9) & 7),
        (table_value >> 14) & 1,
        (table_value >> 15) & 1,
    )
    if (tile_index, palette, hflip, vflip) != expected_decode:
        raise ValueError(
            f"line {row.line}: sprite tile/palette/flip fields do not match descriptor"
        )
    sprite_y = (table_value >> 16) & 0xFF
    delta = (line_y - sprite_y) & 0xFF
    if delta >= 8:
        raise ValueError(f"line {row.line}: sprite is not vertically active")
    expected_row = 7 - delta if vflip else delta
    if tile_row != expected_row:
        raise ValueError(f"line {row.line}: tile_row does not match descriptor/line")
    expected_bytes = 2 if bpp == 2 else 4
    if row_bytes != expected_bytes:
        raise ValueError(f"line {row.line}: tile_row_bytes does not match bpp")
    expected_address = (
        (0x2000 if bpp == 2 else 0x4000)
        + tile_index * expected_bytes * 8
        + tile_row * expected_bytes
    )
    if row_address != expected_address:
        raise ValueError(
            f"line {row.line}: tile_row_address does not match descriptor/line"
        )
    if row_value >= 1 << (8 * row_bytes):
        raise ValueError(f"line {row.line}: tile_row_value exceeds row width")
    return (
        bpp,
        row_address,
        row_value,
        line_y,
        line_slot,
        table_generation,
        line_epoch,
    )


def validate_slot_sequence(
    row: TraceRow,
    line_y: int,
    line_slot: int,
    line_epoch: int,
    active_epoch: int | None,
    active_line_y: int | None,
    expected_slot: int,
) -> tuple[int, int, int]:
    if active_epoch is None or line_epoch > active_epoch:
        if line_slot != 0:
            raise ValueError(
                f"line {row.line}: sprite line epoch {line_epoch} must start at slot 0, "
                f"got {line_slot}"
            )
        return line_epoch, line_y, 1
    if line_epoch < active_epoch:
        raise ValueError(
            f"line {row.line}: sprite line epoch moved backwards from "
            f"{active_epoch} to {line_epoch}"
        )
    if line_y != active_line_y:
        raise ValueError(
            f"line {row.line}: sprite line epoch {line_epoch} changed target line "
            f"from {active_line_y} to {line_y}"
        )
    if line_slot != expected_slot:
        raise ValueError(
            f"line {row.line}: sprite line epoch {line_epoch} expected contiguous "
            f"slot {expected_slot}, got {line_slot}"
        )
    return line_epoch, line_y, expected_slot + 1


def validate_tile_group(
    row: TraceRow, group: FetchGroup, bpp: int, row_address: int, row_value: int
) -> tuple[list[FetchSnapshot], list[ByteVersion | None]]:
    first, second = group.first, group.second
    if row.cycle != second.row.cycle + 1:
        raise ValueError(
            f"line {row.line}: atomic sprite row must follow the second raw tile "
            "read by exactly one cycle"
        )
    if first.address != row_address:
        raise ValueError(
            f"line {row.line}: atomic sprite row does not match the next raw tile group"
        )
    expected_second = first.address + 2 if bpp == 4 else first.address | 2
    if second.address != expected_second:
        raise ValueError(
            f"line {row.line}: raw sprite tile second-read address does not match {bpp}bpp timing"
        )

    if bpp == 2:
        contributing = [first]
        expected_value = first.value
        expected_collision = first.collision
    else:
        if first.address & 3:
            raise ValueError(f"line {row.line}: 4bpp sprite row is not four-byte aligned")
        contributing = [first, second]
        expected_value = first.value | (second.value << 16)
        expected_collision = first.collision | second.collision
    row_collision = decimal(row, "tile_row_collision", 1)
    if (row_value, row_collision) != (expected_value, expected_collision):
        raise ValueError(
            f"line {row.line}: atomic sprite row does not match contributing raw tile reads"
        )
    for snapshot in contributing:
        check_contributing(snapshot)
    if row_collision:
        raise ValueError(f"line {row.line}: atomic sprite row contains a collision")
    versions = [version for fetch in contributing for version in (fetch.low, fetch.high)]
    return contributing, versions


def raw_fields(prefix: str, fetch: FetchSnapshot) -> dict[str, object]:
    return {
        f"{prefix}_raw_line": fetch.row.line,
        f"{prefix}_raw_cycle": fetch.row.cycle,
        f"{prefix}_raw_address": fetch.address,
        f"{prefix}_raw_value": fetch.value,
        f"{prefix}_raw_collision": fetch.collision,
        f"{prefix}_scoreboard_status": fetch.scoreboard_status,
    }


def correlate(
    trace: Path,
    output: TextIO,
    require_complete_coverage: bool = False,
) -> dict[str, int]:
    coverage_status, iram = read_manifest(trace)
    if require_complete_coverage and coverage_status != "complete_from_reset":
        raise ValueError(
            "trace manifest does not prove complete mem+vram+sprite_row history from reset"
        )

    writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    counts = {name: 0 for name in COUNT_NAMES}
    source_tracker = MemorySourceTracker()
    table_first: FetchSnapshot | None = None
    tile_first: FetchSnapshot | None = None
    table_groups: list[FetchGroup] = []
    tile_groups: deque[FetchGroup] = deque()
    active_epoch: int | None = None
    active_line_y: int | None = None
    expected_slot = 0

    with trace.open(newline="", encoding="utf-8") as source:
        for cycle, rows_iter in itertools.groupby(iter_rows(source), key=lambda item: item.cycle):
            rows = list(rows_iter)

            # The DPRAM sample and its writer version precede same-edge writes.
            # Process all raw reads before atomic handoffs and memory events.
            for row in (item for item in rows if item.values["event"] == "vram"):
                role = row.values["role"]
                if role not in {"sprite_table", "sprite_tile"}:
                    continue
                snapshot = snapshot_fetch(row, iram)
                if role == "sprite_table":
                    if table_first is None:
                        if snapshot.address & 3:
                            raise ValueError(
                                f"line {row.line}: sprite table group starts at an unaligned address"
                            )
                        table_first = snapshot
                    else:
                        if snapshot.address != table_first.address + 2:
                            raise ValueError(
                                f"line {row.line}: sprite table words are not a contiguous descriptor"
                            )
                        group = FetchGroup(counts["raw_table_groups"], table_first, snapshot)
                        table_groups.append(group)
                        counts["raw_table_groups"] += 1
                        table_first = None
                else:
                    if tile_first is None:
                        tile_first = snapshot
                    else:
                        group = FetchGroup(counts["raw_tile_groups"], tile_first, snapshot)
                        tile_groups.append(group)
                        counts["raw_tile_groups"] += 1
                        tile_first = None

            for row in (item for item in rows if item.values["event"] == "sprite_row"):
                (
                    bpp,
                    row_address,
                    row_value,
                    line_y,
                    line_slot,
                    table_generation,
                    line_epoch,
                ) = validate_atomic_decode(row)
                active_epoch, active_line_y, expected_slot = validate_slot_sequence(
                    row,
                    line_y,
                    line_slot,
                    line_epoch,
                    active_epoch,
                    active_line_y,
                    expected_slot,
                )
                if table_generation >= len(table_groups):
                    raise ValueError(
                        f"line {row.line}: atomic sprite row references unavailable raw table "
                        f"generation {table_generation}"
                    )
                table_group = table_groups[table_generation]
                if table_group.index != table_generation:
                    raise AssertionError("raw table generation index drift")
                if not tile_groups:
                    raise ValueError(
                        f"line {row.line}: atomic sprite row has no completed raw tile group"
                    )
                tile_group = tile_groups.popleft()
                table_versions = validate_table_group(row, table_group)
                contributing, row_versions = validate_tile_group(
                    row, tile_group, bpp, row_address, row_value
                )
                table_group.references += 1
                table_status, table_writer, table_source = summarize_group(table_versions)
                row_status, row_writer, row_source = summarize_group(row_versions)

                record: dict[str, object] = {
                    "sprite_row_index": counts["sprite_rows"],
                    "line": row.line,
                    "cycle": cycle,
                    "coverage_status": coverage_status,
                    "table_group_index": table_group.index,
                    "table_scoreboard_status": table_status,
                    "table_writer_summary": table_writer,
                    "table_source_summary": table_source,
                    "tile_group_index": tile_group.index,
                    "tile1_contributes": 1 if bpp == 4 else 0,
                    "contributing_raw_lines": ";".join(
                        str(fetch.row.line) for fetch in contributing
                    ),
                    "contributing_raw_cycles": ";".join(
                        str(fetch.row.cycle) for fetch in contributing
                    ),
                    "row_scoreboard_status": row_status,
                    "row_writer_summary": row_writer,
                    "row_source_summary": row_source,
                }
                for field in (*SPRITE_FIELDS, *ATOMIC_TILE_FIELDS):
                    record[field] = row.values[field]
                record.update(raw_fields("table0", table_group.first))
                record.update(raw_fields("table1", table_group.second))
                record.update(raw_fields("tile0", tile_group.first))
                record.update(raw_fields("tile1", tile_group.second))
                for index, version in enumerate(table_versions):
                    record.update(
                        byte_fields(
                            f"table_b{index}", version, table_group.first.address + index
                        )
                    )
                padded_rows = [*row_versions, None, None, None, None][:4]
                for index, version in enumerate(padded_rows):
                    record.update(byte_fields(f"row_b{index}", version, row_address + index))
                writer.writerow(record)

                counts["sprite_rows"] += 1
                counts[f"bpp{bpp}"] += 1
                counts["packed" if decimal(row, "packed", 1) else "planar"] += 1
                counts["descriptor_collision"] += decimal(
                    row, "sprite_table_collision", 1
                )
                counts["row_collision"] += decimal(row, "tile_row_collision", 1)
                if table_writer == "cpu_exact":
                    counts["descriptor_cpu_exact"] += 1
                if row_writer == "cpu_exact":
                    counts["row_cpu_exact"] += 1
                elif row_writer == "gdma":
                    counts["row_gdma"] += 1
                if row_source == "gdma_rom":
                    counts["row_source_gdma_rom"] += 1
                if row_source == "cpu_rom_movsb":
                    counts["cpu_rom_movsb_rows"] += 1

            for row in (item for item in rows if item.values["event"] == "mem"):
                values = row.values
                source_read = source_tracker.observe(row)
                if values["access"] != "write" or values["space"] != "iram":
                    continue
                address = decimal(row, "address", 0xFFFF)
                byte_enable = decimal(row, "byte_enable", 3)
                value = decimal(row, "value", 0xFFFF)
                for lane in (0, 1):
                    if not (byte_enable & (1 << lane)):
                        continue
                    target = address + lane
                    if target > 0xFFFF:
                        raise ValueError(f"line {row.line}: IRAM write crosses 0xffff")
                    iram[target] = ByteVersion(
                        (value >> (8 * lane)) & 0xFF,
                        row,
                        source_read,
                        source_lane(source_read, lane),
                    )

    counts["raw_table_unused"] = sum(group.references == 0 for group in table_groups)
    counts["raw_tile_unpromoted"] = len(tile_groups)
    counts["raw_table_inflight"] = 1 if table_first is not None else 0
    counts["raw_tile_inflight"] = 1 if tile_first is not None else 0
    counts["cpu_rom_movsb_bytes"] = source_tracker.cpu_rom_movsb_bytes
    counts["cpu_rom_movsb_origins"] = len(source_tracker.cpu_rom_movsb_origins)
    return counts


def expected_count(value: str) -> tuple[str, int]:
    try:
        name, count_text = value.split("=", 1)
        count = int(count_text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected count must be NAME=COUNT") from error
    if name not in COUNT_NAMES or count < 0:
        raise argparse.ArgumentTypeError(f"invalid expected count: {value}")
    return name, count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete-coverage", action="store_true")
    parser.add_argument(
        "--expect-count",
        type=expected_count,
        action="append",
        default=[],
        metavar="NAME=COUNT",
    )
    args = parser.parse_args()
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as output:
            counts = correlate(args.trace, output, args.require_complete_coverage)
        for name, expected in args.expect_count:
            if counts[name] != expected:
                raise ValueError(f"expected {name}={expected}, got {counts[name]}")
    except (OSError, ValueError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    print(f"PASS {args.trace} " + " ".join(f"{key}={counts[key]}" for key in sorted(counts)))


if __name__ == "__main__":
    main()
