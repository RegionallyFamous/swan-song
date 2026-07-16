#!/usr/bin/env python3
"""Verify the generated REP MOVSB ROM and its exact v5 trace semantics."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from generate_rep_movsb_probe import (
    COMPLETION_ADDRESS,
    COMPLETION_VALUE,
    FOOTER_OFFSET,
    MARKER_OFFSET,
    MARKER_SIZE,
    PROGRAM_OFFSET,
    PROGRAM_PC,
    ROM_SIZE,
    TRANSFERS,
    footer,
    image,
    marker_records,
    parse_marker,
    payload,
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
ROM_SPACES = {"cart_rom0", "cart_rom1", "cart_rom_linear"}
MEM_SPACES = {
    "iram",
    "cart_sram",
    *ROM_SPACES,
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


@dataclass(frozen=True)
class CopyEvidence:
    instruction_id: int
    prefetch_cycle: int
    first_cycle: int
    last_cycle: int
    write_lines: frozenset[int]


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


def integer(row: Row, field: str, maximum: int) -> int:
    return number(row.values[field], field, row.line, maximum)


def verify_rom(path: Path) -> bytes:
    """Bind every generated region plus all otherwise-erased ROM bytes."""

    observed = path.read_bytes()
    if len(observed) != ROM_SIZE:
        raise ValueError(f"probe ROM size mismatch: {len(observed)} != {ROM_SIZE}")
    expected_checksum = sum(observed[:-2]) & 0xFFFF
    stored_checksum = int.from_bytes(observed[-2:], "little")
    if stored_checksum != expected_checksum:
        raise ValueError(
            "probe ROM footer checksum mismatch: "
            f"{stored_checksum:#06x} != {expected_checksum:#06x}"
        )

    expected = image()
    if observed[FOOTER_OFFSET:-2] != footer()[:-2]:
        raise ValueError("probe ROM 16-byte footer mismatch")

    encoded_marker = observed[MARKER_OFFSET : MARKER_OFFSET + MARKER_SIZE]
    records = parse_marker(encoded_marker)
    if records != marker_records():
        raise ValueError("probe ROM machine marker transfer records mismatch")

    built = program()
    if observed[PROGRAM_OFFSET : PROGRAM_OFFSET + len(built.data)] != built.data:
        raise ValueError("probe ROM program bytes mismatch")
    for index, transfer in enumerate(TRANSFERS):
        source = observed[
            transfer.source_offset : transfer.source_offset + transfer.length
        ]
        if source != payload(index):
            raise ValueError(f"probe ROM {transfer.name} payload mismatch")
    if observed != expected:
        raise ValueError("probe ROM does not match the exact generated image")
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
    capture_cycles = manifest.get("capture_cycles")
    if (
        not isinstance(capture_cycles, int)
        or isinstance(capture_cycles, bool)
        or capture_cycles <= 0
    ):
        raise ValueError(
            f"trace manifest capture_cycles is invalid: {capture_cycles!r}"
        )
    return capture_cycles


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
        raise ValueError(f"line {row.line}: REP MOVSB trace has a non-CPU initiator")
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
            raise ValueError("REP MOVSB probe requires the exact v5 trace header")
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


def verify_prefetch(origin: int, rom: bytes, mem_rows: list[Row]) -> Row:
    program_offset = PROGRAM_OFFSET + (origin - PROGRAM_PC)
    if rom[program_offset : program_offset + 2] != b"\xF3\xA4":
        raise ValueError(f"generated origin {origin:#07x} is not REP MOVSB")
    candidates = [
        row
        for row in mem_rows
        if row.values["origin_status"] == "unattributed"
        and row.values["access"] == "read"
        and integer(row, "address", 0xFFFFF) == origin
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"REP MOVSB origin {origin:#07x} prefetch count mismatch: "
            f"{len(candidates)} != 1"
        )
    row = candidates[0]
    if row.values["space"] != "cart_rom_linear":
        raise ValueError(f"line {row.line}: REP MOVSB prefetch is not linear ROM")
    expected = {
        "value": 0xA4F3,
        "byte_enable": 0,
        "mapped_offset": program_offset,
    }
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


def verify_copy(index: int, rom: bytes, mem_rows: list[Row]) -> CopyEvidence:
    transfer = TRANSFERS[index]
    origin = program().rep_origins[index]
    prefetch = verify_prefetch(origin, rom, mem_rows)
    origin_rows = [
        row
        for row in mem_rows
        if row.values["origin_status"] == "exact"
        and integer(row, "origin_pc", 0xFFFFF) == origin
    ]
    instruction_ids = {
        integer(row, "instruction_id", 0xFFFFFFFF) for row in origin_rows
    }
    if len(instruction_ids) != 1:
        raise ValueError(
            f"{transfer.name} instruction-chain count mismatch: "
            f"{sorted(instruction_ids)}"
        )
    instruction_id = next(iter(instruction_ids))
    chain = [
        row
        for row in mem_rows
        if row.values["origin_status"] == "exact"
        and integer(row, "instruction_id", 0xFFFFFFFF) == instruction_id
    ]
    expected_count = transfer.length * 2
    if len(chain) != expected_count:
        raise ValueError(
            f"{transfer.name} chain event count mismatch: "
            f"{len(chain)} != {expected_count}"
        )
    if prefetch.cycle >= chain[0].cycle:
        raise ValueError(f"{transfer.name} prefetch does not precede its copy chain")

    positions_by_line = {row.line: position for position, row in enumerate(mem_rows)}
    positions = [positions_by_line[row.line] for row in chain]
    if positions != list(range(positions[0], positions[0] + len(chain))):
        raise ValueError(f"{transfer.name} chain has interleaved memory traffic")
    if any(first.cycle >= second.cycle for first, second in zip(chain, chain[1:])):
        raise ValueError(f"{transfer.name} chain cycles are not strictly increasing")

    source_data = payload(index)
    write_lines: set[int] = set()
    for offset in range(transfer.length):
        read, write = chain[offset * 2 : offset * 2 + 2]
        expected_rows = (
            (
                read,
                "read",
                "cart_rom_linear",
                transfer.source_address + offset,
                transfer.source_offset + offset,
                0,
            ),
            (
                write,
                "write",
                "iram",
                transfer.destination + offset,
                transfer.destination + offset,
                1,
            ),
        )
        for row, access, space, address, mapped_offset, byte_enable in expected_rows:
            if row.values["access"] != access:
                raise ValueError(
                    f"line {row.line}: {transfer.name} alternation mismatch; "
                    f"expected {access}"
                )
            if row.values["space"] != space:
                raise ValueError(
                    f"line {row.line}: {transfer.name} {access} space mismatch: "
                    f"{row.values['space']!r} != {space!r}"
                )
            if row.values["origin_status"] != "exact":
                raise ValueError(f"line {row.line}: copy event is not exactly attributed")
            if integer(row, "origin_pc", 0xFFFFF) != origin:
                raise ValueError(f"line {row.line}: copy origin changed within chain")
            expected_numbers = {
                "instruction_id": instruction_id,
                "address": address,
                "mapped_offset": mapped_offset,
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
                        f"line {row.line}: {transfer.name} {access} {field} "
                        f"mismatch: {observed} != {wanted}"
                    )

        source_byte = source_data[offset]
        if integer(read, "value", 0xFFFF) & 0xFF != source_byte:
            raise ValueError(
                f"line {read.line}: {transfer.name} ROM byte mismatch at "
                f"{transfer.source_offset + offset:#x}"
            )
        if integer(write, "value", 0xFFFF) != source_byte:
            raise ValueError(
                f"line {write.line}: {transfer.name} IRAM write value mismatch at "
                f"{transfer.destination + offset:#x}"
            )
        write_lines.add(write.line)

    return CopyEvidence(
        instruction_id=instruction_id,
        prefetch_cycle=prefetch.cycle,
        first_cycle=chain[0].cycle,
        last_cycle=chain[-1].cycle,
        write_lines=frozenset(write_lines),
    )


def verify_destination_windows(mem_rows: list[Row], copies: list[CopyEvidence]) -> None:
    expected_lines = set().union(*(copy.write_lines for copy in copies))
    for row in mem_rows:
        if row.values["access"] != "write":
            continue
        address = integer(row, "address", 0xFFFFF)
        byte_enable = integer(row, "byte_enable", 3)
        affected_addresses = {
            address + lane
            for lane in range(2)
            if byte_enable & (1 << lane)
        }
        overlaps_destination = any(
            transfer.destination <= affected < transfer.destination + transfer.length
            for transfer in TRANSFERS
            for affected in affected_addresses
        )
        if overlaps_destination and row.line not in expected_lines:
            raise ValueError(
                f"line {row.line}: copied IRAM destination has an unexpected write"
            )


def verify_no_extra_copies(mem_rows: list[Row], copies: list[CopyEvidence]) -> None:
    grouped: dict[int, list[Row]] = {}
    for row in mem_rows:
        if row.values["origin_status"] != "exact":
            continue
        instruction_id = integer(row, "instruction_id", 0xFFFFFFFF)
        grouped.setdefault(instruction_id, []).append(row)
    candidates = {
        instruction_id
        for instruction_id, rows in grouped.items()
        if any(
            row.values["access"] == "read" and row.values["space"] in ROM_SPACES
            for row in rows
        )
        and any(
            row.values["access"] == "write" and row.values["space"] == "iram"
            for row in rows
        )
    }
    expected = {copy.instruction_id for copy in copies}
    if candidates != expected:
        raise ValueError(
            "unexpected exact CPU ROM-to-IRAM instruction chains: "
            f"{sorted(candidates)} != {sorted(expected)}"
        )


def verify_completion(
    cpu_rows: list[Row],
    mem_rows: list[Row],
    copies: list[CopyEvidence],
    capture_cycles: int,
) -> None:
    built = program()
    candidates = [
        row
        for row in mem_rows
        if row.values["access"] == "write"
        and integer(row, "address", 0xFFFFF) == COMPLETION_ADDRESS
    ]
    if len(candidates) != 1:
        raise ValueError(f"completion write count mismatch: {len(candidates)} != 1")
    row = candidates[0]
    expected = {
        "value": COMPLETION_VALUE,
        "byte_enable": 3,
        "mapped_offset": COMPLETION_ADDRESS,
        "origin_pc": built.completion_origin,
    }
    if row.values["space"] != "iram" or row.values["origin_status"] != "exact":
        raise ValueError(f"line {row.line}: completion is not an exact IRAM write")
    for field, wanted in expected.items():
        maximum = 3 if field == "byte_enable" else 0xFFFFFF
        if field == "value":
            maximum = 0xFFFF
        elif field == "origin_pc":
            maximum = 0xFFFFF
        observed = integer(row, field, maximum)
        if observed != wanted:
            raise ValueError(
                f"line {row.line}: completion {field} mismatch: "
                f"{observed} != {wanted}"
            )
    completion_id = integer(row, "instruction_id", 0xFFFFFFFF)
    if completion_id in {copy.instruction_id for copy in copies}:
        raise ValueError("completion reuses a REP MOVSB instruction_id")
    if row.cycle <= copies[-1].last_cycle:
        raise ValueError("completion write does not follow both REP MOVSB copies")

    last_cpu = cpu_rows[-1]
    terminal_pc = integer(last_cpu, "physical_pc", 0xFFFFF)
    if terminal_pc != built.halt_pc:
        raise ValueError(
            f"terminal CPU PC mismatch: {terminal_pc:#07x} != {built.halt_pc:#07x}"
        )
    # cpu_done is observed before the separately registered memory trace row
    # for this store, so do not impose an artificial ordering between those
    # two observer channels.  Both must independently follow the copy chain.
    if last_cpu.cycle <= copies[-1].last_cycle:
        raise ValueError("terminal CPU completion does not follow both copies")
    if last_cpu.cycle >= capture_cycles:
        raise ValueError("terminal CPU event is outside the certified capture")


def verify(rom_path: Path, trace_path: Path) -> tuple[int, int]:
    rom = verify_rom(rom_path)
    capture_cycles = verify_manifest(trace_path, rom)
    cpu_rows, mem_rows = read_trace(trace_path)
    if max(cpu_rows[-1].cycle, mem_rows[-1].cycle) >= capture_cycles:
        raise ValueError("trace event lies outside the certified capture_cycles")

    copies = [verify_copy(index, rom, mem_rows) for index in range(len(TRANSFERS))]
    instruction_ids = tuple(copy.instruction_id for copy in copies)
    if len(set(instruction_ids)) != len(TRANSFERS) or list(
        instruction_ids
    ) != sorted(instruction_ids):
        raise ValueError(
            "REP MOVSB instruction IDs are reused or out of order: "
            f"{instruction_ids}"
        )
    for previous, current in zip(copies, copies[1:]):
        if previous.last_cycle >= current.prefetch_cycle:
            raise ValueError("REP MOVSB transfer spans overlap or are out of order")

    verify_destination_windows(mem_rows, copies)
    verify_no_extra_copies(mem_rows, copies)
    verify_completion(cpu_rows, mem_rows, copies, capture_cycles)
    return instruction_ids[0], instruction_ids[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    try:
        instruction_ids = verify(args.rom, args.trace)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"REP MOVSB probe: {error}") from error
    print(
        "PASS generated REP MOVSB probe "
        f"copies={len(TRANSFERS)} bytes={sum(item.length for item in TRANSFERS)} "
        f"instruction_ids={instruction_ids[0]},{instruction_ids[1]} "
        "destinations_intact=2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
