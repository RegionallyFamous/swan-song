#!/usr/bin/env python3
"""Focused positive and negative tests for the generated SDMA verifier."""

from __future__ import annotations

import csv
import json
import tempfile
from copy import deepcopy
from pathlib import Path

from generate_sdma_probe import PROGRAM, generate
from verify_sdma_probe import (
    DEFAULT_COLOR_BIOS_FNV1A64,
    DEFAULT_COLOR_BIOS_SIZE,
    EXPECTED,
    EXPECTED_EVENTS,
    fnv1a64,
    verify,
)
from verify_trace import FIELDS_V5


def valid_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in EXPECTED:
        row: dict[str, object] = {field: "" for field in FIELDS_V5}
        row.update(
            {
                "cycle": item.cycle,
                "event": "mem",
                "address": item.address,
                "value": item.value,
                "initiator": "sdma",
                "access": "read",
                "byte_enable": 3,
                "space": "cart_rom_linear",
                "mapped_offset": item.mapped_offset,
                "origin_status": "not_applicable",
            }
        )
        rows.append(row)
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
    manifest = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_file": str(trace),
        "trace_size_bytes": trace.stat().st_size,
        "trace_fnv1a64": fnv1a64(trace.read_bytes()),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": 10000,
        "completed_frames": 1,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "bios_size": DEFAULT_COLOR_BIOS_SIZE,
        "bios_fnv1a64": DEFAULT_COLOR_BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": True,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
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
        raise AssertionError(f"invalid SDMA case passed: {trace.name}")


def mutated_case(
    root: Path,
    rom_path: Path,
    rom: bytes,
    name: str,
    field: str,
    value: object,
    expected: str,
) -> None:
    rows = deepcopy(valid_rows())
    rows[1][field] = value
    trace = root / f"{name}.csv"
    write_case(trace, rows, rom)
    must_fail(rom_path, trace, expected)


def main() -> None:
    assert PROGRAM.startswith(bytes((0xFA, 0xB0, 0x80, 0xE6, 0x60)))
    with tempfile.TemporaryDirectory(prefix="swansong-sdma-test-") as directory:
        root = Path(directory)
        rom_path = generate(root)
        rom = rom_path.read_bytes()

        valid = root / "valid.csv"
        write_case(valid, valid_rows(), rom)
        verify(rom_path, valid)

        mutated_case(root, rom_path, rom, "initiator", "initiator", "gdma", "initiator")
        mutated_case(root, rom_path, rom, "address", "address", 0xF0104, "address")
        mutated_case(root, rom_path, rom, "value", "value", 0x1234, "value")
        mutated_case(root, rom_path, rom, "cycle", "cycle", EXPECTED[1].cycle + 1, "cycle")
        mutated_case(
            root, rom_path, rom, "offset", "mapped_offset", 0x10104, "mapped_offset"
        )
        mutated_case(root, rom_path, rom, "access", "access", "write", "not read")
        mutated_case(root, rom_path, rom, "space", "space", "iram", "space")
        mutated_case(root, rom_path, rom, "origin", "instruction_id", 1, "CPU origin")
        mutated_case(root, rom_path, rom, "lane", "byte_enable", 1, "byte_enable")

        trace = root / "count.csv"
        write_case(trace, valid_rows()[:-1], rom)
        must_fail(rom_path, trace, "event count")

        rows = valid_rows()
        rows[1], rows[2] = rows[2], rows[1]
        trace = root / "order.csv"
        write_case(trace, rows, rom)
        must_fail(rom_path, trace, "cycle order")

        trace = root / "manifest.csv"
        write_case(trace, valid_rows(), rom)
        with trace.open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(rom_path, trace, "trace_size_bytes mismatch")

        for name, updates, expected in (
            ("rom-binding", {"rom_fnv1a64": "0" * 16}, "rom_fnv1a64 mismatch"),
            ("bios-binding", {"bios_fnv1a64": "0" * 16}, "bios_fnv1a64 mismatch"),
            (
                "filter-authority",
                {"memory_filters_active": False},
                "memory_filters_active mismatch",
            ),
            (
                "completeness-authority",
                {"complete_memory_history": True},
                "complete_memory_history mismatch",
            ),
        ):
            trace = root / f"{name}.csv"
            write_case(trace, valid_rows(), rom, manifest_updates=updates)
            must_fail(rom_path, trace, expected)

        corrupt_rom = root / "corrupt.wsc"
        changed = bytearray(rom)
        changed[0x10100] ^= 1
        corrupt_rom.write_bytes(changed)
        must_fail(corrupt_rom, valid, "ROM size/hash mismatch")

    print("PASS generated SDMA verifier")


if __name__ == "__main__":
    main()
