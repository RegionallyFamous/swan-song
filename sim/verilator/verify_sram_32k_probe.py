#!/usr/bin/env python3
"""Verify paired type-01/type-02 32 KiB SRAM traces and bound inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from generate_sram_32k_probe import ROM_SIZE
from verify_trace import FIELDS_V5


OPEN_IPL_SIZE = 4096
OPEN_IPL_FNV1A64 = "bcae6dfa69fd72ab"
ROM_SHA256 = {
    1: "396671b3b43a7acbde3ced5730d6490567f9acdcd3595bcd4aa81e2654c8c4f1",
    2: "028c4a2686f3d73bc18ad113e57489b444e9fde00344f9df41798f026a35b7e4",
}
ROM_FNV1A64 = {
    1: "85fdf2b579323630",
    2: "77ef25cdac89e32a",
}
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
    access: str
    byte_enable: int
    mapped_offset: int
    instruction_id: int
    origin_pc: int


EXPECTED = (
    Expected(2160, 0x10000, 0x11, "write", 1, 0x0000, 53, 0xF0006),
    Expected(2184, 0x12000, 0x22, "write", 1, 0x2000, 54, 0xF000B),
    Expected(2208, 0x17FFF, 0x33, "write", 1, 0x7FFF, 55, 0xF0010),
    Expected(2238, 0x10000, 0x11, "read", 0, 0x0000, 56, 0xF0015),
    Expected(2262, 0x12000, 0x22, "read", 0, 0x2000, 57, 0xF0018),
    Expected(2298, 0x17FFF, 0x33, "read", 0, 0x7FFF, 58, 0xF001B),
    Expected(2322, 0x18000, 0x11, "read", 0, 0x0000, 59, 0xF001E),
)


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def integer(value: str, field: str, line: int, maximum: int) -> int:
    try:
        result = int(value, 10)
    except ValueError as error:
        raise ValueError(f"line {line}: invalid {field}: {value!r}") from error
    if not 0 <= result <= maximum:
        raise ValueError(f"line {line}: {field} outside 0..{maximum}: {result}")
    return result


def verify_input(path: Path, size: int, digest: str, description: str) -> bytes:
    data = path.read_bytes()
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"unexpected {description} size/hash")
    return data


def verify_manifest(trace: Path, rom_type: int, rom: bytes) -> None:
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
        "rom_fnv1a64": ROM_FNV1A64[rom_type],
        "open_ipl_size": OPEN_IPL_SIZE,
        "open_ipl_fnv1a64": OPEN_IPL_FNV1A64,
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
                f"type {rom_type:02x} manifest {field} mismatch: "
                f"{manifest.get(field)!r} != {wanted!r}"
            )
    cycles = manifest.get("capture_cycles")
    if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles <= 0:
        raise ValueError(f"type {rom_type:02x} manifest capture_cycles is invalid")


def verify_trace(trace: Path, rom_type: int, rom: bytes) -> None:
    verify_manifest(trace, rom_type, rom)
    with trace.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(f"type {rom_type:02x} trace requires exact v5 header")
        rows = list(reader)

    if len(rows) != len(EXPECTED):
        raise ValueError(
            f"type {rom_type:02x} SRAM event count {len(rows)} != {len(EXPECTED)}"
        )

    populated = {
        "cycle", "event", "address", "value", "initiator", "access",
        "byte_enable", "space", "mapped_offset", "instruction_id",
        "origin_pc", "origin_status",
    }
    for index, (row, wanted) in enumerate(zip(rows, EXPECTED), start=1):
        line = index + 1
        unexpected = sorted(field for field in FIELDS_V5 if field not in populated and row[field])
        if unexpected:
            raise ValueError(f"line {line}: unexpected populated fields: {unexpected}")
        fixed = {
            "event": "mem",
            "initiator": "cpu",
            "space": "cart_sram",
            "origin_status": "exact",
        }
        for field, value in fixed.items():
            if row[field] != value:
                raise ValueError(f"line {line}: {field} mismatch")
        observed = {
            "cycle": integer(row["cycle"], "cycle", line, (1 << 64) - 1),
            "address": integer(row["address"], "address", line, 0xFFFFF),
            "value": integer(row["value"], "value", line, 0xFFFF),
            "access": row["access"],
            "byte_enable": integer(row["byte_enable"], "byte_enable", line, 3),
            "mapped_offset": integer(row["mapped_offset"], "mapped_offset", line, 0xFFFFFF),
            "instruction_id": integer(row["instruction_id"], "instruction_id", line, 0xFFFFFFFF),
            "origin_pc": integer(row["origin_pc"], "origin_pc", line, 0xFFFFF),
        }
        for field, value in observed.items():
            if value != getattr(wanted, field):
                raise ValueError(
                    f"type {rom_type:02x} event {index} {field} mismatch: "
                    f"{value!r} != {getattr(wanted, field)!r}"
                )


def verify(
    type01_rom_path: Path,
    type01_trace: Path,
    type02_rom_path: Path,
    type02_trace: Path,
) -> None:
    traces: list[bytes] = []
    for rom_type, rom_path, trace in (
        (1, type01_rom_path, type01_trace),
        (2, type02_rom_path, type02_trace),
    ):
        rom = verify_input(
            rom_path, ROM_SIZE, ROM_SHA256[rom_type], f"type {rom_type:02x} SRAM ROM"
        )
        if rom[-5] != rom_type:
            raise ValueError(f"type {rom_type:02x} ROM header mismatch")
        verify_trace(trace, rom_type, rom)
        traces.append(trace.read_bytes())
    if traces[0] != traces[1]:
        raise ValueError("type 01 and type 02 SRAM traces differ")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("type01_rom", type=Path)
    parser.add_argument("type01_trace", type=Path)
    parser.add_argument("type02_rom", type=Path)
    parser.add_argument("type02_trace", type=Path)
    args = parser.parse_args()
    try:
        verify(
            args.type01_rom,
            args.type01_trace,
            args.type02_rom,
            args.type02_trace,
        )
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"32 KiB SRAM probe: {error}") from error
    print(
        "PASS type01/type02 32KiB SRAM distinct=0000,2000,7fff "
        "alias=8000->0000 traces=identical inputs=bound"
    )


if __name__ == "__main__":
    main()
