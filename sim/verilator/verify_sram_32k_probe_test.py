#!/usr/bin/env python3
"""Mutation-strong offline tests for the paired 32 KiB SRAM verifier."""

from __future__ import annotations

import csv
import json
import tempfile
from copy import deepcopy
from pathlib import Path

from generate_sram_32k_probe import generate
from verify_sram_32k_probe import (
    BIOS_FNV1A64,
    BIOS_SIZE,
    EXPECTED,
    EXPECTED_EVENTS,
    ROM_FNV1A64,
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
                "initiator": "cpu",
                "access": item.access,
                "byte_enable": item.byte_enable,
                "space": "cart_sram",
                "mapped_offset": item.mapped_offset,
                "instruction_id": item.instruction_id,
                "origin_pc": item.origin_pc,
                "origin_status": "exact",
            }
        )
        rows.append(row)
    return rows


def write_trace(
    trace: Path,
    rows: list[dict[str, object]],
    rom_type: int,
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
        "capture_cycles": 1000,
        "completed_frames": 1,
        "rom_size": len(rom),
        "rom_fnv1a64": ROM_FNV1A64[rom_type],
        "bios_size": BIOS_SIZE,
        "bios_fnv1a64": BIOS_FNV1A64,
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


def must_fail(
    bios: Path,
    type01_rom: Path,
    type01_trace: Path,
    type02_rom: Path,
    type02_trace: Path,
    expected: str,
) -> None:
    try:
        verify(bios, type01_rom, type01_trace, type02_rom, type02_trace)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid SRAM case passed: {expected}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-sram32k-test-") as directory:
        root = Path(directory)
        type01_rom, type02_rom, bios = generate(root)
        roms = {1: type01_rom.read_bytes(), 2: type02_rom.read_bytes()}
        traces = {1: root / "type01.csv", 2: root / "type02.csv"}
        for rom_type in (1, 2):
            write_trace(traces[rom_type], valid_rows(), rom_type, roms[rom_type])
        verify(bios, type01_rom, traces[1], type02_rom, traces[2])

        # Simulate the inherited 8 KiB type-01 mask: offset 0x2000 mirrors 0,
        # 0x7fff masks to 0x1fff, and subsequent reads observe overwritten data.
        old_mask = deepcopy(valid_rows())
        old_mask[1]["mapped_offset"] = 0
        old_mask[2]["mapped_offset"] = 0x1FFF
        old_mask[3]["value"] = 0x22
        old_mask[4]["value"] = 0x22
        old_mask[4]["mapped_offset"] = 0
        old_mask[5]["mapped_offset"] = 0x1FFF
        old_mask[6]["value"] = 0x22
        write_trace(traces[1], old_mask, 1, roms[1])
        must_fail(bios, type01_rom, traces[1], type02_rom, traces[2], "mapped_offset mismatch")

        mutations = (
            ("alias", 6, "mapped_offset", 0x8000, "mapped_offset mismatch"),
            ("value", 4, "value", 0x11, "value mismatch"),
            ("address", 2, "address", 0x15FFF, "address mismatch"),
            ("access", 3, "access", "write", "access mismatch"),
            ("lane", 0, "byte_enable", 3, "byte_enable mismatch"),
            ("origin", 0, "origin_status", "unattributed", "origin_status mismatch"),
        )
        for name, index, field, value, expected in mutations:
            rows = deepcopy(valid_rows())
            rows[index][field] = value
            write_trace(traces[1], rows, 1, roms[1])
            must_fail(bios, type01_rom, traces[1], type02_rom, traces[2], expected)

        write_trace(traces[1], valid_rows()[:-1], 1, roms[1])
        must_fail(bios, type01_rom, traces[1], type02_rom, traces[2], "event count")

        write_trace(traces[1], valid_rows(), 1, roms[1])
        changed_type02 = deepcopy(valid_rows())
        changed_type02[6]["cycle"] += 1
        write_trace(traces[2], changed_type02, 2, roms[2])
        must_fail(bios, type01_rom, traces[1], type02_rom, traces[2], "cycle mismatch")

        write_trace(traces[2], valid_rows(), 2, roms[2])
        for name, updates, expected in (
            ("rom-binding", {"rom_fnv1a64": "0" * 16}, "rom_fnv1a64 mismatch"),
            ("bios-binding", {"bios_fnv1a64": "0" * 16}, "bios_fnv1a64 mismatch"),
            ("filter", {"memory_filters_active": False}, "memory_filters_active mismatch"),
            ("completion", {"capture_completed": False}, "capture_completed mismatch"),
        ):
            write_trace(
                traces[1], valid_rows(), 1, roms[1], manifest_updates=updates
            )
            must_fail(bios, type01_rom, traces[1], type02_rom, traces[2], expected)

        corrupt = root / "corrupt-type01.ws"
        changed = bytearray(roms[1])
        changed[0] ^= 1
        corrupt.write_bytes(changed)
        write_trace(traces[1], valid_rows(), 1, roms[1])
        must_fail(bios, corrupt, traces[1], type02_rom, traces[2], "size/hash")

    print("PASS paired 32 KiB SRAM verifier mutation controls")


if __name__ == "__main__":
    main()
