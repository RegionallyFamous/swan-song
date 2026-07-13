#!/usr/bin/env python3
"""Verify the canonical bootstrap's exact CPU REP MOVSB ROM-to-IRAM copies."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from verify_trace import FIELDS_V5


ROM_SIZE = 64 * 1024
ROM_SHA256 = "a222ed50ae977bcd1ac9bbf66c35b57e589e49b7594a21d07a5eddf899335173"
BIOS_SIZE = 4096
BIOS_FNV1A64 = "2c83c0c1976b8168"
EXPECTED_EVENTS = {
    "cpu": True,
    "bank": False,
    "vram": True,
    "mem": True,
    "bg_cell": True,
}
ROM_SPACES = {"cart_rom0", "cart_rom1", "cart_rom_linear"}
MEM_SPACES = {
    "iram",
    "cart_sram",
    *ROM_SPACES,
    "boot_rom",
    "unmapped",
    "absent_sram",
}
MEM_FIELDS = {
    "cycle",
    "event",
    "address",
    "value",
    "initiator",
    "access",
    "byte_enable",
    "space",
    "mapped_offset",
    "instruction_id",
    "origin_pc",
    "origin_status",
}


@dataclass(frozen=True)
class Copy:
    origin: int
    source_address: int
    source_offset: int
    destination: int
    length: int


COPIES = (
    Copy(0xF00A4, 0xF0252, 0x0252, 0x2800, 0x800),
    Copy(0xF0100, 0xF0A52, 0x0A52, 0x2000, 0x800),
)


@dataclass(frozen=True)
class TraceRow:
    line: int
    cycle: int
    values: dict[str, str]


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def number(value: str, field: str, line: int, maximum: int) -> int:
    if not value:
        raise ValueError(f"line {line}: {field} is empty")
    try:
        result = int(value, 10)
    except ValueError as error:
        raise ValueError(
            f"line {line}: {field} is not a decimal integer: {value!r}"
        ) from error
    if not 0 <= result <= maximum:
        raise ValueError(f"line {line}: {field} outside 0..{maximum}: {result}")
    return result


def verify_manifest(trace: Path, rom: bytes) -> int:
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
    for field, wanted in expected.items():
        if manifest.get(field) != wanted:
            raise ValueError(
                f"trace manifest {field} mismatch: "
                f"{manifest.get(field)!r} != {wanted!r}"
            )
    # The producer records the --event-trace spelling verbatim, so this field
    # may be absolute or relative to the capture process's working directory.
    # Content hash and byte size are the portable binding authorities.
    trace_file = manifest.get("trace_file")
    if not isinstance(trace_file, str) or not trace_file:
        raise ValueError(f"trace manifest trace_file is invalid: {trace_file!r}")
    cycles = manifest.get("capture_cycles")
    if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles <= 0:
        raise ValueError(f"trace manifest capture_cycles is invalid: {cycles!r}")
    return cycles


def validate_mem(row: TraceRow) -> None:
    values = row.values
    unexpected = sorted(
        field for field in FIELDS_V5 if field not in MEM_FIELDS and values[field]
    )
    if unexpected:
        raise ValueError(
            f"line {row.line}: mem event has unexpected populated fields: {unexpected}"
        )
    initiator = values["initiator"]
    access = values["access"]
    space = values["space"]
    origin = values["origin_status"]
    if initiator not in {"cpu", "gdma", "sdma"}:
        raise ValueError(f"line {row.line}: invalid memory initiator {initiator!r}")
    if access not in {"read", "write"}:
        raise ValueError(f"line {row.line}: invalid memory access {access!r}")
    if space not in MEM_SPACES:
        raise ValueError(f"line {row.line}: invalid memory space {space!r}")
    number(values["address"], "address", row.line, 0xFFFFF)
    number(values["value"], "value", row.line, 0xFFFF)
    byte_enable = number(values["byte_enable"], "byte_enable", row.line, 3)
    if values["mapped_offset"]:
        number(values["mapped_offset"], "mapped_offset", row.line, 0xFFFFFF)
    elif space not in {"unmapped", "absent_sram"}:
        raise ValueError(f"line {row.line}: mapped memory event has no offset")

    if initiator == "cpu":
        if access == "read" and byte_enable != 0:
            raise ValueError(f"line {row.line}: CPU read byte_enable is not zero")
        if origin == "exact":
            instruction_id = number(
                values["instruction_id"], "instruction_id", row.line, 0xFFFFFFFF
            )
            if instruction_id == 0:
                raise ValueError(f"line {row.line}: exact CPU instruction_id is zero")
            number(values["origin_pc"], "origin_pc", row.line, 0xFFFFF)
        elif origin == "unattributed":
            if values["instruction_id"] or values["origin_pc"]:
                raise ValueError(
                    f"line {row.line}: unattributed CPU event has an instruction origin"
                )
        else:
            raise ValueError(f"line {row.line}: invalid CPU origin status {origin!r}")
    else:
        if origin != "not_applicable":
            raise ValueError(f"line {row.line}: DMA event has CPU origin status")
        if values["instruction_id"] or values["origin_pc"]:
            raise ValueError(f"line {row.line}: DMA event has an instruction origin")


def read_trace(path: Path) -> tuple[list[TraceRow], list[TraceRow]]:
    rows: list[TraceRow] = []
    mem_rows: list[TraceRow] = []
    seen_events: set[str] = set()
    previous_cycle = -1
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(
                "bootstrap REP MOVSB verification requires the exact v5 trace header"
            )
        for line, values in enumerate(reader, start=2):
            if None in values:
                raise ValueError(f"line {line}: trace row has surplus columns")
            cycle = number(values["cycle"], "cycle", line, (1 << 64) - 1)
            if cycle < previous_cycle:
                raise ValueError(
                    f"line {line}: cycle {cycle} follows later cycle {previous_cycle}"
                )
            previous_cycle = cycle
            event = values["event"]
            if event not in {"cpu", "vram", "mem", "bg_cell"}:
                raise ValueError(f"line {line}: unexpected event {event!r}")
            seen_events.add(event)
            row = TraceRow(line, cycle, values)
            rows.append(row)
            if event == "mem":
                validate_mem(row)
                mem_rows.append(row)
    required = {name for name, enabled in EXPECTED_EVENTS.items() if enabled}
    if seen_events != required:
        raise ValueError(
            f"trace event coverage mismatch: {sorted(seen_events)} != {sorted(required)}"
        )
    if not rows or not mem_rows:
        raise ValueError("bootstrap REP MOVSB trace has no memory events")
    return rows, mem_rows


def integer(row: TraceRow, field: str, maximum: int) -> int:
    return number(row.values[field], field, row.line, maximum)


def verify_prefetch(copy: Copy, rom: bytes, mem_rows: list[TraceRow]) -> TraceRow:
    origin_offset = copy.origin - 0xF0000
    if rom[origin_offset : origin_offset + 2] != b"\xF3\xA4":
        raise ValueError(f"ROM origin {copy.origin:#07x} is not REP MOVSB")
    candidates = [
        row
        for row in mem_rows
        if row.values["initiator"] == "cpu"
        and row.values["access"] == "read"
        and integer(row, "address", 0xFFFFF) == copy.origin
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"origin {copy.origin:#07x} prefetch count mismatch: {len(candidates)} != 1"
        )
    row = candidates[0]
    expected = {
        "value": 0xA4F3,
        "byte_enable": 0,
        "mapped_offset": origin_offset,
    }
    if row.values["space"] != "cart_rom_linear":
        raise ValueError(f"line {row.line}: REP MOVSB prefetch is not linear ROM")
    if row.values["origin_status"] != "unattributed":
        raise ValueError(f"line {row.line}: REP MOVSB prefetch is not unattributed")
    for field, wanted in expected.items():
        maximum = 3 if field == "byte_enable" else 0xFFFFFF
        if field == "value":
            maximum = 0xFFFF
        observed = integer(row, field, maximum)
        if observed != wanted:
            raise ValueError(
                f"line {row.line}: REP MOVSB prefetch {field} mismatch: "
                f"{observed} != {wanted}"
            )
    return row


def verify_copy(copy: Copy, rom: bytes, mem_rows: list[TraceRow]) -> tuple[int, int, int]:
    prefetch = verify_prefetch(copy, rom, mem_rows)
    origin_rows = [
        row
        for row in mem_rows
        if row.values["initiator"] == "cpu"
        and row.values["origin_status"] == "exact"
        and integer(row, "origin_pc", 0xFFFFF) == copy.origin
    ]
    instruction_ids = {integer(row, "instruction_id", 0xFFFFFFFF) for row in origin_rows}
    if len(instruction_ids) != 1:
        raise ValueError(
            f"origin {copy.origin:#07x} instruction-chain count mismatch: "
            f"{sorted(instruction_ids)}"
        )
    instruction_id = next(iter(instruction_ids))
    chain = [
        row
        for row in mem_rows
        if row.values["instruction_id"]
        and integer(row, "instruction_id", 0xFFFFFFFF) == instruction_id
    ]
    expected_count = copy.length * 2
    if len(chain) != expected_count:
        raise ValueError(
            f"origin {copy.origin:#07x} chain event count mismatch: "
            f"{len(chain)} != {expected_count}"
        )
    if prefetch.cycle >= chain[0].cycle:
        raise ValueError(f"origin {copy.origin:#07x} prefetch does not precede its chain")
    span = [row for row in mem_rows if chain[0].cycle <= row.cycle <= chain[-1].cycle]
    if span != chain:
        raise ValueError(f"origin {copy.origin:#07x} chain has interleaved memory traffic")

    for index in range(copy.length):
        read, write = chain[index * 2 : index * 2 + 2]
        source_address = copy.source_address + index
        source_offset = copy.source_offset + index
        destination = copy.destination + index
        source_byte = rom[source_offset]

        for row, access, space, address, offset, byte_enable in (
            (read, "read", "cart_rom_linear", source_address, source_offset, 0),
            (write, "write", "iram", destination, destination, 1),
        ):
            if row.values["initiator"] != "cpu":
                raise ValueError(f"line {row.line}: REP MOVSB initiator is not CPU")
            if row.values["access"] != access:
                raise ValueError(
                    f"line {row.line}: REP MOVSB alternation mismatch; expected {access}"
                )
            if row.values["space"] != space:
                raise ValueError(
                    f"line {row.line}: REP MOVSB {access} space mismatch: "
                    f"{row.values['space']!r} != {space!r}"
                )
            if row.values["origin_status"] != "exact":
                raise ValueError(f"line {row.line}: REP MOVSB event is not exact")
            if integer(row, "origin_pc", 0xFFFFF) != copy.origin:
                raise ValueError(f"line {row.line}: REP MOVSB origin changed within chain")
            expected_numbers = {
                "instruction_id": instruction_id,
                "address": address,
                "mapped_offset": offset,
                "byte_enable": byte_enable,
            }
            for field, wanted in expected_numbers.items():
                maximum = 0xFFFFFFFF if field == "instruction_id" else 0xFFFFFF
                if field == "address":
                    maximum = 0xFFFFF
                elif field == "byte_enable":
                    maximum = 3
                observed = integer(row, field, maximum)
                if observed != wanted:
                    raise ValueError(
                        f"line {row.line}: REP MOVSB {access} {field} mismatch: "
                        f"{observed} != {wanted}"
                    )

        read_byte = integer(read, "value", 0xFFFF) & 0xFF
        write_value = integer(write, "value", 0xFFFF)
        if read_byte != source_byte:
            raise ValueError(
                f"line {read.line}: REP MOVSB ROM byte mismatch at {source_offset:#x}: "
                f"{read_byte:#04x} != {source_byte:#04x}"
            )
        if write_value != source_byte:
            raise ValueError(
                f"line {write.line}: REP MOVSB write value mismatch at {destination:#x}: "
                f"{write_value:#04x} != {source_byte:#04x}"
            )
    return instruction_id, chain[0].cycle, chain[-1].cycle


def verify(rom_path: Path, trace: Path) -> tuple[int, ...]:
    rom = rom_path.read_bytes()
    digest = hashlib.sha256(rom).hexdigest()
    if len(rom) != ROM_SIZE or digest != ROM_SHA256:
        raise ValueError(f"bootstrap ROM size/hash mismatch: size={len(rom)} sha256={digest}")
    capture_cycles = verify_manifest(trace, rom)
    rows, mem_rows = read_trace(trace)
    if capture_cycles <= rows[-1].cycle:
        raise ValueError(
            f"trace manifest capture_cycles {capture_cycles} does not exceed final cycle "
            f"{rows[-1].cycle}"
        )

    results = [verify_copy(copy, rom, mem_rows) for copy in COPIES]
    instruction_ids = tuple(result[0] for result in results)
    if len(set(instruction_ids)) != len(COPIES) or list(instruction_ids) != sorted(
        instruction_ids
    ):
        raise ValueError(f"REP MOVSB instruction IDs are reused or out of order: {instruction_ids}")
    for previous, current in zip(results, results[1:]):
        if previous[2] >= current[1]:
            raise ValueError("REP MOVSB copy spans overlap or are out of order")

    candidate_ids: set[int] = set()
    grouped: dict[int, list[TraceRow]] = {}
    for row in mem_rows:
        if row.values["origin_status"] != "exact":
            continue
        instruction_id = integer(row, "instruction_id", 0xFFFFFFFF)
        grouped.setdefault(instruction_id, []).append(row)
    for instruction_id, group in grouped.items():
        has_rom_read = any(
            row.values["access"] == "read" and row.values["space"] in ROM_SPACES
            for row in group
        )
        has_iram_write = any(
            row.values["access"] == "write" and row.values["space"] == "iram"
            for row in group
        )
        if has_rom_read and has_iram_write:
            candidate_ids.add(instruction_id)
    if candidate_ids != set(instruction_ids):
        raise ValueError(
            "unexpected exact CPU ROM-to-IRAM instruction chains: "
            f"{sorted(candidate_ids)} != {sorted(instruction_ids)}"
        )
    return instruction_ids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    try:
        instruction_ids = verify(args.rom, args.trace)
    except (OSError, ValueError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    rendered = ",".join(str(value) for value in instruction_ids)
    print(
        f"PASS {args.trace} rep_movsb_copies={len(COPIES)} "
        f"bytes={sum(copy.length for copy in COPIES)} instruction_ids={rendered}"
    )


if __name__ == "__main__":
    main()
