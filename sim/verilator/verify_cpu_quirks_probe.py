#!/usr/bin/env python3
"""Verify the generated V30MZ quirk probe from exact ROM and trace evidence."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from generate_cpu_quirks_probe import (
    PROGRAM_OFFSET,
    PROGRAM_PC,
    ROM_SIZE,
    expected_results,
    image,
    program,
)
from verify_trace import FIELDS_V5


OPEN_IPL_SIZE = 4096
OPEN_IPL_FNV1A64 = "bcae6dfa69fd72ab"
EXPECTED_EVENTS = {
    "cpu": True,
    "bank": False,
    "vram": False,
    "mem": True,
    "bg_cell": False,
}
MEM_SPACES = {
    "iram",
    "cart_sram",
    "cart_rom0",
    "cart_rom1",
    "cart_rom_linear",
    "boot_rom",
    "unmapped",
    "absent_sram",
    "cart_flash",
}
CPU_FIELDS = {"cycle", "event", "physical_pc", "cs", "ip"}
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
class Row:
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


def verify_rom(path: Path) -> bytes:
    observed = path.read_bytes()
    expected = image()
    if len(observed) != ROM_SIZE or observed != expected:
        raise ValueError("probe ROM does not match the exact generated image")
    built = program()
    if observed[PROGRAM_OFFSET : PROGRAM_OFFSET + len(built.data)] != built.data:
        raise ValueError("probe ROM program bytes do not match generator metadata")
    return observed


def verify_manifest(trace: Path, rom: bytes) -> int:
    manifest_path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {manifest_path}: {error}") from error

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
    expected_keys = {*expected, "trace_file", "capture_cycles"}
    if set(manifest) != expected_keys:
        raise ValueError(
            "trace manifest field set mismatch: "
            f"{sorted(manifest)} != {sorted(expected_keys)}"
        )
    for field, wanted in expected.items():
        if manifest.get(field) != wanted:
            raise ValueError(
                f"trace manifest {field} mismatch: "
                f"{manifest.get(field)!r} != {wanted!r}"
            )
    trace_file = manifest.get("trace_file")
    if not isinstance(trace_file, str) or not trace_file:
        raise ValueError("trace manifest trace_file is invalid")
    if Path(trace_file).resolve() != trace.resolve():
        raise ValueError(
            f"trace manifest trace_file mismatch: {trace_file!r} != {str(trace)!r}"
        )
    cycles = manifest.get("capture_cycles")
    if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles <= 0:
        raise ValueError(f"trace manifest capture_cycles is invalid: {cycles!r}")
    return cycles


def _empty_except(row: Row, allowed: set[str]) -> None:
    unexpected = [
        field for field in FIELDS_V5 if field not in allowed and row.values[field]
    ]
    if unexpected:
        raise ValueError(
            f"line {row.line}: {row.values['event']} has unexpected fields: "
            f"{', '.join(unexpected)}"
        )


def validate_cpu(row: Row) -> None:
    _empty_except(row, CPU_FIELDS)
    pc = number(row.values["physical_pc"], "physical_pc", row.line, 0xFFFFF)
    cs = number(row.values["cs"], "cs", row.line, 0xFFFF)
    ip = number(row.values["ip"], "ip", row.line, 0xFFFF)
    if ((cs << 4) + ip) & 0xFFFFF != pc:
        raise ValueError(f"line {row.line}: CPU CS:IP does not equal physical_pc")


def validate_mem(row: Row) -> None:
    _empty_except(row, MEM_FIELDS)
    values = row.values
    if values["initiator"] != "cpu":
        raise ValueError(f"line {row.line}: non-CPU memory initiator")
    if values["access"] not in {"read", "write"}:
        raise ValueError(f"line {row.line}: invalid memory access")
    if values["space"] not in MEM_SPACES:
        raise ValueError(f"line {row.line}: invalid memory space")
    number(values["address"], "address", row.line, 0xFFFFF)
    number(values["value"], "value", row.line, 0xFFFF)
    byte_enable = number(values["byte_enable"], "byte_enable", row.line, 3)
    if values["access"] == "read" and byte_enable != 0:
        raise ValueError(f"line {row.line}: CPU read has a write byte lane")
    if values["access"] == "write" and byte_enable == 0:
        raise ValueError(f"line {row.line}: CPU write has no byte lane")
    if values["mapped_offset"]:
        number(values["mapped_offset"], "mapped_offset", row.line, 0xFFFFFF)
    elif values["space"] not in {"unmapped", "absent_sram"}:
        raise ValueError(f"line {row.line}: mapped memory event has no offset")

    status = values["origin_status"]
    if status == "exact":
        instruction_id = number(
            values["instruction_id"], "instruction_id", row.line, 0xFFFFFFFF
        )
        if instruction_id == 0:
            raise ValueError(f"line {row.line}: exact instruction_id is zero")
        number(values["origin_pc"], "origin_pc", row.line, 0xFFFFF)
    elif status == "unattributed":
        if values["instruction_id"] or values["origin_pc"]:
            raise ValueError(
                f"line {row.line}: unattributed memory event has instruction origin"
            )
    else:
        raise ValueError(f"line {row.line}: invalid CPU origin status {status!r}")


def read_trace(path: Path) -> tuple[list[Row], list[Row]]:
    cpu_rows: list[Row] = []
    mem_rows: list[Row] = []
    instruction_origins: dict[int, int] = {}
    previous_cycle = -1
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError("CPU quirk probe requires the exact v5 trace header")
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
            row = Row(line, cycle, values)
            if event == "cpu":
                validate_cpu(row)
                cpu_rows.append(row)
            elif event == "mem":
                validate_mem(row)
                if values["origin_status"] == "exact":
                    instruction_id = number(
                        values["instruction_id"], "instruction_id", line, 0xFFFFFFFF
                    )
                    origin = number(values["origin_pc"], "origin_pc", line, 0xFFFFF)
                    previous_origin = instruction_origins.setdefault(
                        instruction_id, origin
                    )
                    if previous_origin != origin:
                        raise ValueError(
                            f"line {line}: instruction_id {instruction_id} maps to "
                            f"both {previous_origin:#07x} and {origin:#07x}"
                        )
                mem_rows.append(row)
            else:
                raise ValueError(f"line {line}: unexpected event {event!r}")
            seen.add(event)
    if seen != {"cpu", "mem"} or not cpu_rows or not mem_rows:
        raise ValueError("trace does not contain complete CPU and memory evidence")
    return cpu_rows, mem_rows


def integer(row: Row, field: str, maximum: int) -> int:
    return number(row.values[field], field, row.line, maximum)


def verify_results(mem_rows: list[Row]) -> None:
    built = program()
    contracts = expected_results(built)
    addresses = {contract[0] for contract in contracts.values()}
    result_writes = [
        row
        for row in mem_rows
        if row.values["access"] == "write"
        and integer(row, "address", 0xFFFFF) in addresses
    ]
    if len(result_writes) != len(contracts):
        raise ValueError(
            f"result write count mismatch: {len(result_writes)} != {len(contracts)}"
        )

    previous_cycle = -1
    observed_values: dict[str, int] = {}
    for name, (address, expected, mask) in contracts.items():
        candidates = [
            row for row in result_writes if integer(row, "address", 0xFFFFF) == address
        ]
        if len(candidates) != 1:
            raise ValueError(f"{name} write count mismatch: {len(candidates)} != 1")
        row = candidates[0]
        if row.cycle <= previous_cycle:
            raise ValueError(f"{name} result write is out of program order")
        previous_cycle = row.cycle
        if row.values["space"] != "iram" or integer(row, "mapped_offset", 0xFFFFFF) != address:
            raise ValueError(f"line {row.line}: {name} is not an exact IRAM write")
        if integer(row, "byte_enable", 3) != 3:
            raise ValueError(f"line {row.line}: {name} is not a word write")
        value = integer(row, "value", 0xFFFF)
        observed_values[name] = value
        if value & mask != expected & mask:
            raise ValueError(
                f"line {row.line}: {name} value mismatch: "
                f"{value & mask:#06x} != {expected & mask:#06x} (mask {mask:#06x})"
            )
        if row.values["origin_status"] != "exact":
            raise ValueError(f"line {row.line}: {name} has no exact instruction origin")
        origin = integer(row, "origin_pc", 0xFFFFF)
        if origin != built.result_origins[name]:
            raise ValueError(
                f"line {row.line}: {name} origin mismatch: "
                f"{origin:#07x} != {built.result_origins[name]:#07x}"
            )

    for path in ("cf0", "cf1"):
        before = observed_values[f"salc_{path}_flags_before"]
        after = observed_values[f"salc_{path}_flags"]
        if before != after:
            raise ValueError(
                f"SALC {path} changed PUSHF: {before:#06x} != {after:#06x}"
            )

    extra_window_writes = [
        row
        for row in mem_rows
        if row.values["access"] == "write"
        and 0x0200 <= integer(row, "address", 0xFFFFF) <= 0x022F
        and integer(row, "address", 0xFFFFF) not in addresses
    ]
    if extra_window_writes:
        raise ValueError("probe has an unexpected write in the result window")


def _cpu_completion(cpu_rows: list[Row], pc: int) -> Row:
    matches = [row for row in cpu_rows if integer(row, "physical_pc", 0xFFFFF) == pc]
    if len(matches) != 1:
        raise ValueError(f"CPU completion PC {pc:#07x} count mismatch: {len(matches)} != 1")
    return matches[0]


def verify_salc(cpu_rows: list[Row], mem_rows: list[Row], rom: bytes) -> tuple[int, int]:
    built = program()
    timings: list[int] = []
    for origin in built.salc_origins:
        # MOV AX,imm immediately precedes each SALC.  Its completion PC is the
        # SALC origin; the following completion is the one-byte SALC's end.
        # The observer's end-to-end system-cycle delta includes variable
        # prefetch-buffer credits (dbuf), so it cannot certify an isolated
        # V30MZ clock count.  Require adjacency and report, but do not relabel,
        # the measured deltas.
        before = _cpu_completion(cpu_rows, origin)
        after = _cpu_completion(cpu_rows, origin + 1)
        elapsed = after.cycle - before.cycle
        before_index = cpu_rows.index(before)
        if elapsed <= 0 or before_index + 1 >= len(cpu_rows) or cpu_rows[before_index + 1] != after:
            raise ValueError(f"SALC at {origin:#07x} has no adjacent completion")
        timings.append(elapsed)

        data_accesses = [
            row
            for row in mem_rows
            if row.values["origin_status"] == "exact"
            and integer(row, "origin_pc", 0xFFFFF) == origin
        ]
        if data_accesses:
            raise ValueError(
                f"SALC at {origin:#07x} emitted attributed data-memory traffic"
            )

        # Complete memory history does contain normal instruction-prefetch
        # reads while SALC's delay retires.  Bind every such interval row to
        # the exact generated ROM bytes; reject an unattributed XLAT-like IRAM
        # access as well as ordinary exactly attributed data traffic.
        interval_rows = [
            row for row in mem_rows if before.cycle < row.cycle <= after.cycle
        ]
        for row in interval_rows:
            if (
                row.values["origin_status"] != "unattributed"
                or row.values["access"] != "read"
                or row.values["space"] != "cart_rom_linear"
            ):
                raise ValueError(
                    f"line {row.line}: SALC interval contains non-prefetch memory traffic"
                )
            address = integer(row, "address", 0xFFFFF)
            offset = integer(row, "mapped_offset", 0xFFFFFF)
            if not PROGRAM_PC <= address < PROGRAM_PC + len(built.data):
                raise ValueError(
                    f"line {row.line}: SALC interval prefetch is outside probe code"
                )
            if offset + 1 >= len(rom):
                raise ValueError(
                    f"line {row.line}: SALC interval prefetch offset is outside ROM"
                )
            expected_offset = PROGRAM_OFFSET + (address - PROGRAM_PC)
            if address & 1 or offset != expected_offset:
                raise ValueError(
                    f"line {row.line}: SALC interval prefetch mapping mismatch: "
                    f"address={address:#07x} offset={offset:#07x} "
                    f"expected={expected_offset:#07x}"
                )
            expected_word = rom[offset] | (rom[offset + 1] << 8)
            if integer(row, "value", 0xFFFF) != expected_word:
                raise ValueError(
                    f"line {row.line}: SALC interval prefetch value mismatches ROM"
                )
    return timings[0], timings[1]


def verify_terminal(cpu_rows: list[Row], capture_cycles: int) -> None:
    built = program()
    # HLT does not emit cpu_done in the current observer.  The last completion
    # is therefore the instruction immediately before the completion-marker
    # store; that store is separately required as exact memory evidence.
    expected_pc = PROGRAM_PC + built.labels["halt"]
    last = cpu_rows[-1]
    pc = integer(last, "physical_pc", 0xFFFFF)
    if pc != expected_pc:
        raise ValueError(f"terminal CPU PC mismatch: {pc:#07x} != {expected_pc:#07x}")
    if last.cycle >= capture_cycles:
        raise ValueError("terminal CPU event is outside the certified capture")


def verify(rom_path: Path, trace_path: Path) -> tuple[int, int]:
    rom = verify_rom(rom_path)
    capture_cycles = verify_manifest(trace_path, rom)
    cpu_rows, mem_rows = read_trace(trace_path)
    if max(cpu_rows[-1].cycle, mem_rows[-1].cycle) >= capture_cycles:
        raise ValueError("trace event lies outside the certified capture_cycles")
    verify_results(mem_rows)
    timings = verify_salc(cpu_rows, mem_rows, rom)
    verify_terminal(cpu_rows, capture_cycles)
    return timings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    try:
        timings = verify(args.rom, args.trace)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"CPU quirk probe: {error}") from error
    print(
        "PASS generated CPU quirk probe "
        f"records={len(expected_results(program()))} "
        f"salc_completion_deltas={timings[0]},{timings[1]} "
        "no_salc_data_access=2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
