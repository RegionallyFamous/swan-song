#!/usr/bin/env python3
"""Focused positive and mutation tests for the bootstrap REP MOVSB verifier."""

from __future__ import annotations

import csv
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Callable

from verify_cpu_rep_movsb import (
    BIOS_FNV1A64,
    BIOS_SIZE,
    COPIES,
    EXPECTED_EVENTS,
    fnv1a64,
    verify,
)
from verify_trace import FIELDS_V5


def blank_row(cycle: int, event: str) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V5}
    row.update({"cycle": cycle, "event": event})
    return row


def mem_row(
    cycle: int,
    access: str,
    address: int,
    value: int,
    byte_enable: int,
    space: str,
    mapped_offset: int,
    instruction_id: int | str,
    origin_pc: int | str,
    origin_status: str,
) -> dict[str, object]:
    row = blank_row(cycle, "mem")
    row.update(
        {
            "address": address,
            "value": value,
            "initiator": "cpu",
            "access": access,
            "byte_enable": byte_enable,
            "space": space,
            "mapped_offset": mapped_offset,
            "instruction_id": instruction_id,
            "origin_pc": origin_pc,
            "origin_status": origin_status,
        }
    )
    return row


def valid_rows(rom: bytes) -> list[dict[str, object]]:
    rows = [blank_row(1, "cpu"), blank_row(2, "vram"), blank_row(3, "bg_cell")]
    cycle = 10
    for instruction_id, copy in zip((62, 102), COPIES):
        origin_offset = copy.origin - 0xF0000
        rows.append(
            mem_row(
                cycle,
                "read",
                copy.origin,
                0xA4F3,
                0,
                "cart_rom_linear",
                origin_offset,
                "",
                "",
                "unattributed",
            )
        )
        cycle += 10
        for index in range(copy.length):
            source_offset = copy.source_offset + index
            source_address = copy.source_address + index
            source_byte = rom[source_offset]
            # The high half is deliberately not canonical operand evidence.
            raw_value = source_byte | (((source_byte ^ 0xA5) & 0xFF) << 8)
            rows.append(
                mem_row(
                    cycle,
                    "read",
                    source_address,
                    raw_value,
                    0,
                    "cart_rom_linear",
                    source_offset,
                    instruction_id,
                    copy.origin,
                    "exact",
                )
            )
            rows.append(
                mem_row(
                    cycle + 2,
                    "write",
                    copy.destination + index,
                    source_byte,
                    1,
                    "iram",
                    copy.destination + index,
                    instruction_id,
                    copy.origin,
                    "exact",
                )
            )
            cycle += 4
        cycle += 10
    return rows


def write_case(
    trace: Path,
    rows: list[dict[str, object]],
    rom: bytes,
    *,
    manifest_updates: dict[str, object] | None = None,
) -> None:
    with trace.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest: dict[str, object] = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_file": str(trace.resolve()),
        "trace_size_bytes": trace.stat().st_size,
        "trace_fnv1a64": fnv1a64(trace.read_bytes()),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": int(rows[-1]["cycle"]) + 1,
        "completed_frames": 6,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "bios_size": BIOS_SIZE,
        "bios_fnv1a64": BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": True,
        "complete_bg_cell_history": True,
    }
    if manifest_updates:
        manifest.update(manifest_updates)
    Path(f"{trace}.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def must_fail(rom: Path, trace: Path, expected: str) -> None:
    try:
        verify(rom, trace)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid REP MOVSB case passed: {trace.name}")


def find_row(rows: list[dict[str, object]], **wanted: object) -> int:
    matches = [
        index
        for index, row in enumerate(rows)
        if all(row[field] == value for field, value in wanted.items())
    ]
    if len(matches) != 1:
        raise AssertionError(f"row selection is not unique: {wanted!r} -> {matches!r}")
    return matches[0]


def mutation_case(
    root: Path,
    rom_path: Path,
    rom: bytes,
    rows: list[dict[str, object]],
    name: str,
    mutate: Callable[[list[dict[str, object]]], None],
    expected: str,
) -> None:
    changed = deepcopy(rows)
    mutate(changed)
    trace = root / f"{name}.csv"
    write_case(trace, changed, rom)
    must_fail(rom_path, trace, expected)


def main() -> None:
    root_path = Path(__file__).resolve().parents[2]
    rom_path = root_path / "testroms/spritepriority/spritepriority.ws"
    rom = rom_path.read_bytes()
    rows = valid_rows(rom)

    with tempfile.TemporaryDirectory(prefix="swansong-rep-movsb-test-") as directory:
        root = Path(directory)
        valid = root / "valid.csv"
        write_case(valid, rows, rom)
        if verify(rom_path, valid) != (62, 102):
            raise AssertionError("valid REP MOVSB IDs changed")

        first_prefetch = find_row(rows, event="mem", address=COPIES[0].origin)
        first_read = find_row(rows, event="mem", address=COPIES[0].source_address)
        first_write = find_row(rows, event="mem", address=COPIES[0].destination)

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "opcode",
            lambda changed: changed[first_prefetch].update(value=0xA5F3),
            "prefetch value mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "alternation",
            lambda changed: changed[first_read].update(access="write"),
            "alternation mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "source-address",
            lambda changed: changed[first_read].update(
                address=int(changed[first_read]["address"]) + 1
            ),
            "read address mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "source-offset",
            lambda changed: changed[first_read].update(mapped_offset=0x253),
            "read mapped_offset mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "source-value",
            lambda changed: changed[first_read].update(
                value=int(changed[first_read]["value"]) ^ 1
            ),
            "ROM byte mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "destination",
            lambda changed: changed[first_write].update(
                address=int(changed[first_write]["address"]) + 1,
                mapped_offset=int(changed[first_write]["mapped_offset"]) + 1,
            ),
            "write address mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "write-value",
            lambda changed: changed[first_write].update(
                value=int(changed[first_write]["value"]) ^ 1
            ),
            "write value mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "write-lane",
            lambda changed: changed[first_write].update(byte_enable=3),
            "write byte_enable mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "split-id",
            lambda changed: changed[first_write].update(instruction_id=63),
            "instruction-chain count mismatch",
        )

        interleaved = deepcopy(rows)
        read_cycle = int(interleaved[first_read]["cycle"])
        interleaved.insert(
            first_write,
            mem_row(
                read_cycle + 1,
                "read",
                0xFFFF0,
                0,
                0,
                "cart_rom_linear",
                0xFFF0,
                "",
                "",
                "unattributed",
            ),
        )
        trace = root / "interleaved.csv"
        write_case(trace, interleaved, rom)
        must_fail(rom_path, trace, "interleaved memory traffic")

        trace = root / "manifest.csv"
        write_case(
            trace,
            rows,
            rom,
            manifest_updates={"complete_memory_history": False},
        )
        must_fail(rom_path, trace, "complete_memory_history mismatch")

        for name, updates, expected in (
            (
                "trace-file",
                {"trace_file": ""},
                "trace_file is invalid",
            ),
            (
                "memory-filter",
                {"memory_filters_active": True},
                "memory_filters_active mismatch",
            ),
            (
                "savestate",
                {"savestate_inputs_asserted": True},
                "savestate_inputs_asserted mismatch",
            ),
            (
                "event-set",
                {"events": {**EXPECTED_EVENTS, "mem": False}},
                "events mismatch",
            ),
        ):
            trace = root / f"{name}.csv"
            write_case(trace, rows, rom, manifest_updates=updates)
            must_fail(rom_path, trace, expected)

        extra = deepcopy(rows)
        final_cycle = int(extra[-1]["cycle"])
        extra.extend(
            (
                mem_row(
                    final_cycle + 1,
                    "read",
                    0xF3000,
                    0,
                    0,
                    "cart_rom_linear",
                    0x3000,
                    200,
                    0xF2000,
                    "exact",
                ),
                mem_row(
                    final_cycle + 2,
                    "write",
                    0x3000,
                    0,
                    1,
                    "iram",
                    0x3000,
                    200,
                    0xF2000,
                    "exact",
                ),
            )
        )
        trace = root / "extra-chain.csv"
        write_case(trace, extra, rom)
        must_fail(rom_path, trace, "unexpected exact CPU ROM-to-IRAM")

        trace = root / "trace-binding.csv"
        write_case(trace, rows, rom)
        with trace.open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(rom_path, trace, "trace_size_bytes mismatch")

        corrupt_rom = root / "corrupt.ws"
        changed_rom = bytearray(rom)
        changed_rom[COPIES[0].source_offset] ^= 1
        corrupt_rom.write_bytes(changed_rom)
        must_fail(corrupt_rom, valid, "ROM size/hash mismatch")

    print("PASS bootstrap REP MOVSB verifier")


if __name__ == "__main__":
    main()
