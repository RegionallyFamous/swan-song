#!/usr/bin/env python3
"""Focused positive and negative tests for the mapper-memory verifier."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from generate_mapper_memory_probe import image
from verify_mapper_memory_probe import (
    BANK_EVENTS,
    BOOT_EVENTS,
    COMMON_PROBE_EVENTS,
    EXPECTED_COUNTS,
    EXPECTED_EVENTS,
    OPEN_IPL_FNV1A64,
    OPEN_IPL_SIZE,
    MemEvent,
    BankEvent,
    fnv1a64,
    footer_events,
    sram_events,
    verify,
)
from verify_trace import FIELDS_V5


def row(**values: object) -> dict[str, object]:
    result: dict[str, object] = {field: "" for field in FIELDS_V5}
    result.update(values)
    return result


def mem_row(item: MemEvent) -> dict[str, object]:
    return row(
        cycle=item.cycle,
        event="mem",
        address=item.address,
        value=item.value,
        initiator="cpu",
        access=item.access,
        byte_enable=item.byte_enable,
        space=item.space,
        mapped_offset="" if item.mapped_offset is None else item.mapped_offset,
        instruction_id="" if item.instruction_id is None else item.instruction_id,
        origin_pc="" if item.origin_pc is None else item.origin_pc,
        origin_status=item.origin_status,
    )


def bank_row(item: BankEvent) -> dict[str, object]:
    return row(
        cycle=item.cycle,
        event="bank",
        address=item.address,
        value=item.value,
        instruction_id=item.instruction_id,
        origin_pc=item.origin_pc,
        origin_status="exact",
    )


def trace_rows(rom: Path, present: bool) -> list[dict[str, object]]:
    items: list[dict[str, object]] = [mem_row(item) for item in BOOT_EVENTS]
    items.extend(mem_row(item) for item in footer_events(rom))
    items.extend(bank_row(item) for item in BANK_EVENTS)
    items.extend(mem_row(item) for item in sram_events(present))
    items.extend(mem_row(item) for item in COMMON_PROBE_EVENTS)
    items.extend(
        mem_row(
            MemEvent(
                1100 + index,
                "read",
                index * 2,
                0,
                0,
                "iram",
                index * 2,
                None,
                None,
                "unattributed",
            )
        )
        for index in range(24)
    )

    existing_linear = sum(
        item["event"] == "mem" and item["space"] == "cart_rom_linear"
        for item in items
    )
    for index in range(36917 - existing_linear):
        address = 0x80000 + ((index * 2) & 0xFFFE)
        items.append(
            mem_row(
                MemEvent(
                    2000 + index,
                    "read",
                    address,
                    0,
                    0,
                    "cart_rom_linear",
                    0x180000 + (address & 0xFFFF),
                    None,
                    None,
                    "unattributed",
                )
            )
        )
    items.sort(key=lambda item: int(item["cycle"]))
    assert sum(item["event"] == "mem" for item in items) == EXPECTED_COUNTS["mem"]
    assert sum(item["event"] == "bank" for item in items) == EXPECTED_COUNTS["bank"]
    return items


def write_trace(path: Path, rows: list[dict[str, object]], rom: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_file": str(path),
        "trace_size_bytes": path.stat().st_size,
        "trace_fnv1a64": fnv1a64(path),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": max(int(item["cycle"]) for item in rows) + 1,
        "completed_frames": 1,
        "rom_size": rom.stat().st_size,
        "rom_fnv1a64": fnv1a64(rom),
        "open_ipl_size": OPEN_IPL_SIZE,
        "open_ipl_fnv1a64": OPEN_IPL_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
    }
    Path(f"{path}.manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def must_fail(function, expected: str) -> None:
    try:
        function()
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError("invalid mapper fixture passed")


def find(rows: list[dict[str, object]], *, event: str = "mem", origin_pc: int) -> int:
    return next(
        index
        for index, item in enumerate(rows)
        if item["event"] == event and item["origin_pc"] == origin_pc
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-mapper-verifier-") as directory:
        root = Path(directory)
        present_rom = root / "present.ws"
        absent_rom = root / "absent.ws"
        present_trace = root / "present.csv"
        absent_trace = root / "absent.csv"
        present_rom.write_bytes(image(3))
        absent_rom.write_bytes(image(0))
        present_rows = trace_rows(present_rom, True)
        absent_rows = trace_rows(absent_rom, False)

        def restore() -> None:
            write_trace(present_trace, present_rows, present_rom)
            write_trace(absent_trace, absent_rows, absent_rom)

        def check() -> None:
            verify(present_rom, present_trace, absent_rom, absent_trace)

        restore()
        check()

        wrong_offset = [*present_rows]
        index = find(wrong_offset, origin_pc=0xF0049)
        wrong_offset[index] = dict(wrong_offset[index], mapped_offset=0x151236)
        write_trace(present_trace, wrong_offset, present_rom)
        must_fail(check, "exact-origin memory sequence")

        restore()
        wrong_value = [*present_rows]
        index = find(wrong_value, origin_pc=0xF001C)
        wrong_value[index] = dict(wrong_value[index], value=0)
        write_trace(present_trace, wrong_value, present_rom)
        must_fail(check, "exact-origin memory sequence")

        restore()
        wrong_write_be = [*present_rows]
        index = find(wrong_write_be, origin_pc=0xF001F)
        wrong_write_be[index] = dict(wrong_write_be[index], byte_enable=3)
        write_trace(present_trace, wrong_write_be, present_rom)
        must_fail(check, "exact-origin memory sequence")

        restore()
        wrong_read_be = [*present_rows]
        index = find(wrong_read_be, origin_pc=0xF0041)
        wrong_read_be[index] = dict(wrong_read_be[index], byte_enable=1)
        write_trace(present_trace, wrong_read_be, present_rom)
        must_fail(check, "CPU read byte_enable convention")

        restore()
        wrong_bank = [*present_rows]
        index = find(wrong_bank, event="bank", origin_pc=0xF000B)
        wrong_bank[index] = dict(wrong_bank[index], instruction_id=17)
        write_trace(present_trace, wrong_bank, present_rom)
        must_fail(check, "bank sequence")

        restore()
        absent_offset = [*absent_rows]
        index = find(absent_offset, origin_pc=0xF0019)
        absent_offset[index] = dict(absent_offset[index], mapped_offset=0x11234)
        write_trace(absent_trace, absent_offset, absent_rom)
        must_fail(check, "absent_sram has a mapped offset")

        restore()
        manifest_path = Path(f"{present_trace}.manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["memory_filters_active"] = True
        manifest["complete_memory_history"] = False
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        must_fail(check, "complete bound authority")

        restore()
        with present_trace.open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(check, "complete bound authority")

        restore()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["open_ipl_fnv1a64"] = "0" * 16
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        must_fail(check, "complete bound authority")

    print("PASS mapper-memory verifier positive/negative cases")


if __name__ == "__main__":
    main()
