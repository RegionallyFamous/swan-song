#!/usr/bin/env python3
"""Verify the exact generated Sound-DMA trace and its bound inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from generate_sdma_probe import MARKER, MARKER_OFFSET, ROM_SIZE
from verify_trace import FIELDS_V5


ROM_SHA256 = "a223ce2d5a962d834adac62ecea06dcca03d026ac871f6de802237f03164d3f9"
DEFAULT_COLOR_BIOS_SIZE = 8192
DEFAULT_COLOR_BIOS_FNV1A64 = "ef7d73ef979bfc94"
EXPECTED_EVENTS = {
    "cpu": False,
    "bank": False,
    "vram": False,
    "mem": True,
    "bg_cell": False,
}


@dataclass(frozen=True)
class Expected:
    cycle: int
    address: int
    value: int
    mapped_offset: int


# Current integrated RTL issues one 16-bit bus read with byte_enable=3 for each
# byte SDMA step. Odd addresses are returned in the low byte by memorymux.
EXPECTED = (
    Expected(2790, 0xF0100, 0xB2A1, 0x10100),
    Expected(4326, 0xF0101, 0x00B2, 0x10101),
    Expected(5862, 0xF0102, 0xD4C3, 0x10102),
    Expected(7398, 0xF0103, 0x00D4, 0x10103),
)


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def integer(value: str, field: str, line: int, maximum: int) -> int:
    if not value:
        raise ValueError(f"line {line}: {field} is empty")
    try:
        result = int(value, 10)
    except ValueError as error:
        raise ValueError(f"line {line}: invalid {field}: {value!r}") from error
    if not 0 <= result <= maximum:
        raise ValueError(f"line {line}: {field} outside 0..{maximum}: {result}")
    return result


def verify_manifest(trace: Path, rom: bytes) -> None:
    path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {path}: {error}") from error

    expected = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_size_bytes": trace.stat().st_size,
        "trace_fnv1a64": fnv1a64(trace.read_bytes()),
        "capture_start": "reset_release",
        "capture_completed": True,
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
    for field, wanted in expected.items():
        if manifest.get(field) != wanted:
            raise ValueError(
                f"trace manifest {field} mismatch: "
                f"{manifest.get(field)!r} != {wanted!r}"
            )
    cycles = manifest.get("capture_cycles")
    if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles <= 0:
        raise ValueError(f"trace manifest capture_cycles is invalid: {cycles!r}")


def verify(rom_path: Path, trace: Path) -> None:
    rom = rom_path.read_bytes()
    if len(rom) != ROM_SIZE or hashlib.sha256(rom).hexdigest() != ROM_SHA256:
        raise ValueError("SDMA probe ROM size/hash mismatch")
    if rom[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] != MARKER:
        raise ValueError("SDMA probe ROM marker mismatch")
    verify_manifest(trace, rom)

    rows: list[tuple[int, dict[str, str]]] = []
    with trace.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(f"SDMA probe requires exact v5 header: {reader.fieldnames!r}")
        previous_cycle = -1
        for line, row in enumerate(reader, start=2):
            cycle = integer(row["cycle"], "cycle", line, (1 << 64) - 1)
            if cycle <= previous_cycle:
                raise ValueError(
                    f"line {line}: SDMA cycle order is not strictly increasing"
                )
            previous_cycle = cycle
            rows.append((line, row))

    if len(rows) != len(EXPECTED):
        raise ValueError(
            f"unexpected SDMA event count: {len(rows)} != {len(EXPECTED)}"
        )

    empty_fields = set(FIELDS_V5) - {
        "cycle",
        "event",
        "address",
        "value",
        "initiator",
        "access",
        "byte_enable",
        "space",
        "mapped_offset",
        "origin_status",
    }
    for index, ((line, row), wanted) in enumerate(zip(rows, EXPECTED), start=1):
        unexpected = sorted(field for field in empty_fields if row[field])
        if unexpected:
            if "instruction_id" in unexpected or "origin_pc" in unexpected:
                raise ValueError(f"line {line}: SDMA event has a CPU origin")
            raise ValueError(f"line {line}: unexpected populated fields: {unexpected}")
        if row["event"] != "mem":
            raise ValueError(f"line {line}: SDMA event is not mem")
        if row["initiator"] != "sdma":
            raise ValueError(f"line {line}: invalid SDMA initiator {row['initiator']!r}")
        if row["access"] != "read":
            raise ValueError(f"line {line}: SDMA access is not read")
        if integer(row["byte_enable"], "byte_enable", line, 3) != 3:
            raise ValueError(f"line {line}: SDMA byte_enable does not match RTL value 3")
        if row["space"] != "cart_rom_linear":
            raise ValueError(f"line {line}: invalid SDMA space {row['space']!r}")
        if row["origin_status"] != "not_applicable":
            raise ValueError(f"line {line}: invalid SDMA origin status")

        observed = {
            "cycle": integer(row["cycle"], "cycle", line, (1 << 64) - 1),
            "address": integer(row["address"], "address", line, 0xFFFFF),
            "value": integer(row["value"], "value", line, 0xFFFF),
            "mapped_offset": integer(
                row["mapped_offset"], "mapped_offset", line, 0xFFFFFF
            ),
        }
        for field in ("cycle", "address", "value", "mapped_offset"):
            if observed[field] != getattr(wanted, field):
                raise ValueError(
                    f"SDMA event {index} {field} mismatch: "
                    f"{observed[field]} != {getattr(wanted, field)}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    try:
        verify(args.rom, args.trace)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"SDMA probe: {error}") from error
    print(
        f"PASS {args.trace} exact four-byte SDMA linear-ROM provenance "
        "byte_enable=3"
    )


if __name__ == "__main__":
    main()
