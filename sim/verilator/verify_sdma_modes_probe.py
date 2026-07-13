#!/usr/bin/env python3
"""Strictly verify the generated Sound-DMA modes probe and two-run evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generate_sdma_modes_probe import (
    DATA_OFFSET,
    EXPECTED_MARKERS as GENERATED_MARKERS,
    FAIL_MARKER,
    FOOTER_OFFSET,
    INPUT_SCRIPT,
    MARKER,
    MARKER_OFFSET,
    PROGRAM_OFFSET,
    PROGRAM_PC,
    ROM_SIZE,
    SAMPLE_DATA,
    image,
    program,
)
from verify_input_script_manifest import ScriptIdentity, parse_script
from verify_trace import FIELDS_V5


@dataclass(frozen=True)
class ExpectedRow:
    scenario: str
    cycle: int
    event: str
    address: int
    value: int
    mapped_offset: int | None = None
    instruction_id: int | None = None
    origin_pc: int | None = None


# Two byte-identical translated-RTL captures.  The verifier also independently
# checks these rows against the generator's origins and canonical ROM bytes.
EXPECTED_ROWS = (
    ExpectedRow("pre-enable-readback", 2255, "bank", 0xC0, ord("P"), instruction_id=40, origin_pc=983130),
    ExpectedRow("one-shot-byte-0", 3906, "mem", 0xF1000, 20017, mapped_offset=0x11000),
    ExpectedRow("one-shot-byte-1", 5454, "mem", 0xF1001, 78, mapped_offset=0x11001),
    ExpectedRow("one-shot-byte-2", 7050, "mem", 0xF1002, 34923, mapped_offset=0x11002),
    ExpectedRow("one-shot-terminal", 8483, "bank", 0xC0, ord("O"), instruction_id=158, origin_pc=983207),
    ExpectedRow("zero-length-restart-rejected", 31427, "bank", 0xC0, ord("N"), instruction_id=443, origin_pc=983292),
    ExpectedRow("pause-first-byte", 33618, "mem", 0xF1010, 7681, mapped_offset=0x11010),
    ExpectedRow("pause-frozen-counters", 57419, "bank", 0xC0, ord("S"), instruction_id=787, origin_pc=983447),
    ExpectedRow("resume-next-byte", 58686, "mem", 0xF1011, 30, mapped_offset=0x11011),
    ExpectedRow("resume-final-byte", 60222, "mem", 0xF1012, 22587, mapped_offset=0x11012),
    ExpectedRow("resume-terminal", 61439, "bank", 0xC0, ord("R"), instruction_id=860, origin_pc=983515),
    ExpectedRow("active-edit-original-byte", 63630, "mem", 0xF1020, 61137, mapped_offset=0x11020),
    ExpectedRow("active-edit-readback", 65027, "bank", 0xC0, ord("E"), instruction_id=928, origin_pc=983615),
    ExpectedRow("active-edit-new-byte-0", 65178, "mem", 0xF1030, 48801, mapped_offset=0x11030),
    ExpectedRow("active-edit-new-byte-1", 66714, "mem", 0xF1031, 190, mapped_offset=0x11031),
    ExpectedRow("active-edit-terminal", 67943, "bank", 0xC0, ord("A"), instruction_id=981, origin_pc=983679),
    ExpectedRow("repeat-original-byte", 70122, "mem", 0xF1040, 36465, mapped_offset=0x11040),
    ExpectedRow("repeat-shadow-byte-0", 71658, "mem", 0xF1050, 24129, mapped_offset=0x11050),
    ExpectedRow("repeat-shadow-byte-1", 73242, "mem", 0xF1051, 94, mapped_offset=0x11051),
    ExpectedRow("repeat-shadow-reload", 74771, "bank", 0xC0, ord("T"), instruction_id=1108, origin_pc=983804),
    ExpectedRow("decrement-byte-3", 76650, "mem", 0xF1063, 104, mapped_offset=0x11063),
    ExpectedRow("decrement-byte-2", 78162, "mem", 0xF1062, 26699, mapped_offset=0x11062),
    ExpectedRow("decrement-byte-1", 79698, "mem", 0xF1061, 46, mapped_offset=0x11061),
    ExpectedRow("decrement-byte-0", 81282, "mem", 0xF1060, 11793, mapped_offset=0x11060),
    ExpectedRow("decrement-terminal", 82715, "bank", 0xC0, ord("D"), instruction_id=1259, origin_pc=983905),
    ExpectedRow("hold-frozen-byte-1", 84954, "mem", 0xF1070, 65249, mapped_offset=0x11070),
    ExpectedRow("hold-live-zero-byte", 86502, "mem", 0xF1070, 65249, mapped_offset=0x11070),
    ExpectedRow("hold-reenabled-byte", 89466, "mem", 0xF1070, 65249, mapped_offset=0x11070),
    ExpectedRow("hold-zero-and-frozen", 90851, "bank", 0xC0, ord("H"), instruction_id=1412, origin_pc=984172),
    ExpectedRow("unhold-next-byte", 91062, "mem", 0xF1070, 65249, mapped_offset=0x11070),
    ExpectedRow("unhold-final-byte", 92538, "mem", 0xF1071, 254, mapped_offset=0x11071),
    ExpectedRow("unhold-terminal", 93923, "bank", 0xC0, ord("U"), instruction_id=1470, origin_pc=984249),
    ExpectedRow("terminal-success", 94019, "bank", 0xC0, ord("Z"), instruction_id=1472, origin_pc=984253),
)

EXPECTED_MARKERS = b"PONSREATDHUZ"
EXPECTED_MEM_ADDRESSES = (
    0xF1000,
    0xF1001,
    0xF1002,
    0xF1010,
    0xF1011,
    0xF1012,
    0xF1020,
    0xF1030,
    0xF1031,
    0xF1040,
    0xF1050,
    0xF1051,
    0xF1063,
    0xF1062,
    0xF1061,
    0xF1060,
    0xF1070,
    0xF1070,
    0xF1070,
    0xF1070,
    0xF1071,
)

ROM_SHA256 = "5a1a79455c4df0eca7ef57b69d8798f44af32db867e28edcb6ea9ff123fb78ad"
SCRIPT_SHA256 = "80deca26f30ce57dec5c71718938cd1342dc9c9b60133c62a52a062f1c54b505"
TRACE_SHA256 = "cb4b1f7f9c197da9cd5a9a8db2f7b7e06af70c882c34682d3e797bd716f68e15"
CAPTURE_CYCLES = 442_241
BIOS_FNV1A64 = "bde71f09ac34c168"
EXPECTED_SCRIPT_IDENTITY = ScriptIdentity(
    source_size_bytes=67,
    source_fnv1a64="149ec2aa599440d0",
    normalized_fnv1a64="1f9fac35d4bab3a9",
    event_count=2,
    final_cycle=1,
)

POPULATED_BANK_FIELDS = {
    "cycle",
    "event",
    "address",
    "value",
    "instruction_id",
    "origin_pc",
    "origin_status",
}
POPULATED_MEM_FIELDS = {
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
MANIFEST_FIELDS = {
    "schema",
    "trace_schema",
    "trace_file",
    "trace_size_bytes",
    "trace_fnv1a64",
    "capture_start",
    "capture_completed",
    "capture_cycles",
    "completed_frames",
    "rom_size",
    "rom_fnv1a64",
    "bios_size",
    "bios_fnv1a64",
    "iram_initial_state",
    "savestate_inputs_asserted",
    "input_script",
    "events",
    "memory_filters_active",
    "display_filters_active",
    "complete_memory_history",
    "complete_display_history",
    "complete_bg_cell_history",
}
INPUT_FIELDS = {
    "schema",
    "source_size_bytes",
    "source_fnv1a64",
    "normalized_fnv1a64",
    "event_count",
    "applied_events",
    "completed",
    "final_state",
}


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def _exact_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _exact_equal(actual[key], value) for key, value in expected.items()
        )
    return actual == expected


def _number(value: Any, field: str, line: int, maximum: int) -> int:
    if not isinstance(value, str) or not value or any(c < "0" or c > "9" for c in value):
        raise ValueError(
            f"line {line}: {field} is not an ASCII decimal integer: {value!r}"
        )
    result = int(value, 10)
    if result > maximum:
        raise ValueError(f"line {line}: {field} exceeds {maximum}: {result}")
    return result


def _generator_contract(rom: bytes) -> None:
    compiled = program()
    if GENERATED_MARKERS != EXPECTED_MARKERS:
        raise ValueError(f"generator marker order changed: {GENERATED_MARKERS!r}")
    bank_rows = tuple(row for row in EXPECTED_ROWS if row.event == "bank")
    success_rows = tuple(row for row in bank_rows if row.value != FAIL_MARKER)
    if bytes(row.value for row in success_rows) != EXPECTED_MARKERS:
        raise ValueError("canonical trace success marker order changed")
    origins = tuple(compiled.marker_origins[value] for value in EXPECTED_MARKERS)
    if origins != tuple(row.origin_pc for row in success_rows):
        raise ValueError(f"generator marker origins changed: {origins!r}")
    if any(row.value == FAIL_MARKER for row in bank_rows):
        raise ValueError("canonical trace contains the failure marker")

    mem_rows = tuple(row for row in EXPECTED_ROWS if row.event == "mem")
    if tuple(row.address for row in mem_rows) != EXPECTED_MEM_ADDRESSES:
        raise ValueError("canonical SDMA address sequence changed")
    for row in mem_rows:
        if row.mapped_offset is None:
            raise ValueError(f"{row.scenario}: missing canonical mapped offset")
        if row.mapped_offset != row.address - 0xE0000:
            raise ValueError(
                f"{row.scenario}: mapped offset is not the linear ROM mapping"
            )
        expected_value = rom[row.mapped_offset]
        if row.address & 1 == 0:
            expected_value |= rom[row.mapped_offset + 1] << 8
        if row.value != expected_value:
            raise ValueError(
                f"{row.scenario}: SDMA value is not bound to canonical ROM bytes"
            )

    success_pc = PROGRAM_PC + compiled.labels["success"]
    success_offset = PROGRAM_OFFSET + compiled.labels["success"]
    if success_rows[-1].origin_pc is None or success_rows[-1].origin_pc + 2 != success_pc:
        raise ValueError("terminal Z marker does not fall through to success")
    if rom[success_offset : success_offset + 2] != b"\xeb\xfe":
        raise ValueError("terminal success loop is not JMP $")
    failed_offset = PROGRAM_OFFSET + compiled.labels["failed"]
    if compiled.marker_origins[FAIL_MARKER] + 2 != PROGRAM_PC + compiled.labels["failed"]:
        raise ValueError("failure marker does not fall through to failed loop")
    if rom[failed_offset : failed_offset + 2] != b"\xeb\xfe":
        raise ValueError("terminal failure loop is not JMP $")
    if rom[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] != MARKER:
        raise ValueError("ROM probe identity marker mismatch")
    if rom[DATA_OFFSET : DATA_OFFSET + len(SAMPLE_DATA)] != SAMPLE_DATA:
        raise ValueError("ROM sample data mismatch")


def verify_rom(path: Path) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != ROM_SIZE or data != image() or digest != ROM_SHA256:
        raise ValueError(f"ROM identity mismatch: size={len(data)}, sha256={digest}")
    if data[FOOTER_OFFSET] != 0xEA:
        raise ValueError("ROM footer jump identity mismatch")
    if int.from_bytes(data[-2:], "little") != sum(data[:-2]) & 0xFFFF:
        raise ValueError("ROM footer checksum mismatch")
    _generator_contract(data)
    return data


def verify_script_source(path: Path) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if data != INPUT_SCRIPT or digest != SCRIPT_SHA256:
        raise ValueError(
            f"input script identity mismatch: size={len(data)}, sha256={digest}"
        )
    identity = parse_script(data, str(path))
    if identity != EXPECTED_SCRIPT_IDENTITY:
        raise ValueError(f"input script normalized identity changed: {identity!r}")
    return data


def _parse_trace(path: Path) -> tuple[ExpectedRow, ...]:
    observed: list[ExpectedRow] = []
    previous_cycle = -1
    previous_instruction_id = 0
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(f"exact v5 trace header required; got {reader.fieldnames!r}")
        for index, row in enumerate(reader):
            line = index + 2
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"line {line}: malformed CSV row")
            event = row["event"]
            allowed = (
                POPULATED_BANK_FIELDS if event == "bank" else POPULATED_MEM_FIELDS
                if event == "mem"
                else set()
            )
            if not allowed:
                raise ValueError(f"line {line}: unexpected event {event!r}")
            populated = {field for field, value in row.items() if value}
            if populated != allowed:
                raise ValueError(
                    f"line {line}: {event} populated-field mismatch: "
                    f"missing={sorted(allowed - populated)}, "
                    f"extra={sorted(populated - allowed)}"
                )
            cycle = _number(row["cycle"], "cycle", line, (1 << 64) - 1)
            if cycle <= previous_cycle:
                raise ValueError(
                    f"line {line}: cycle {cycle} does not follow {previous_cycle}"
                )
            previous_cycle = cycle
            address = _number(row["address"], "address", line, 0xFFFFF)
            value = _number(row["value"], "value", line, 0xFFFF)
            scenario = EXPECTED_ROWS[index].scenario if index < len(EXPECTED_ROWS) else "extra"
            if event == "bank":
                if row["origin_status"] != "exact":
                    raise ValueError(f"line {line}: bank origin is not exact")
                instruction_id = _number(
                    row["instruction_id"], "instruction_id", line, 0xFFFFFFFF
                )
                if instruction_id <= previous_instruction_id:
                    raise ValueError(
                        f"line {line}: instruction ID {instruction_id} does not follow "
                        f"{previous_instruction_id}"
                    )
                previous_instruction_id = instruction_id
                observed.append(
                    ExpectedRow(
                        scenario,
                        cycle,
                        event,
                        address,
                        value,
                        instruction_id=instruction_id,
                        origin_pc=_number(row["origin_pc"], "origin_pc", line, 0xFFFFF),
                    )
                )
            else:
                if row["initiator"] != "sdma":
                    raise ValueError(f"line {line}: mem initiator is not sdma")
                if row["access"] != "read":
                    raise ValueError(f"line {line}: SDMA access is not read")
                if _number(row["byte_enable"], "byte_enable", line, 3) != 3:
                    raise ValueError(f"line {line}: SDMA byte_enable is not raw RTL value 3")
                if row["space"] != "cart_rom_linear":
                    raise ValueError(f"line {line}: SDMA space is not cart_rom_linear")
                if row["origin_status"] != "not_applicable":
                    raise ValueError(f"line {line}: SDMA origin is not not_applicable")
                observed.append(
                    ExpectedRow(
                        scenario,
                        cycle,
                        event,
                        address,
                        value,
                        mapped_offset=_number(
                            row["mapped_offset"], "mapped_offset", line, 0xFFFFFF
                        ),
                    )
                )
    return tuple(observed)


def verify_trace(path: Path, rom: bytes | None = None) -> tuple[ExpectedRow, ...]:
    bound_rom = image() if rom is None else rom
    observed = _parse_trace(path)
    if len(observed) != len(EXPECTED_ROWS):
        raise ValueError(
            f"complete filtered trace row count mismatch: {len(observed)} != {len(EXPECTED_ROWS)}"
        )
    for index, (actual, wanted) in enumerate(zip(observed, EXPECTED_ROWS, strict=True)):
        if actual != wanted:
            fields = (
                "cycle",
                "event",
                "address",
                "value",
                "mapped_offset",
                "instruction_id",
                "origin_pc",
            )
            for field in fields:
                if getattr(actual, field) != getattr(wanted, field):
                    raise ValueError(
                        f"row {index + 1} {wanted.scenario} {field} mismatch: "
                        f"{getattr(actual, field)!r} != {getattr(wanted, field)!r}"
                    )
            raise ValueError(f"row {index + 1} {wanted.scenario} mismatch")
    _generator_contract(bound_rom)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != TRACE_SHA256:
        raise ValueError(f"trace SHA-256 mismatch: {digest}")
    return observed


def read_manifest(trace: Path) -> dict[str, Any]:
    path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"trace manifest {path} is not an object")
    return manifest


def _expected_input(script: bytes) -> dict[str, Any]:
    identity = parse_script(script)
    return {
        "schema": "swan-song-input-script-v1",
        "source_size_bytes": identity.source_size_bytes,
        "source_fnv1a64": identity.source_fnv1a64,
        "normalized_fnv1a64": identity.normalized_fnv1a64,
        "event_count": identity.event_count,
        "applied_events": identity.event_count,
        "completed": True,
        "final_state": "released",
    }


def verify_manifest(
    trace: Path, manifest: dict[str, Any], rom: bytes, script: bytes
) -> dict[str, Any]:
    if set(manifest) != MANIFEST_FIELDS:
        raise ValueError(
            "trace manifest field set mismatch: "
            f"missing={sorted(MANIFEST_FIELDS - set(manifest))}, "
            f"extra={sorted(set(manifest) - MANIFEST_FIELDS)}"
        )
    binding = manifest.get("input_script")
    if not isinstance(binding, dict) or set(binding) != INPUT_FIELDS:
        raise ValueError("input_script manifest field set mismatch")
    trace_bytes = trace.read_bytes()
    expected = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_file": str(trace),
        "trace_size_bytes": len(trace_bytes),
        "trace_fnv1a64": fnv1a64(trace_bytes),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": CAPTURE_CYCLES,
        "completed_frames": 1,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "bios_size": 8192,
        "bios_fnv1a64": BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "input_script": _expected_input(script),
        "events": {
            "cpu": False,
            "bank": True,
            "vram": False,
            "mem": True,
            "bg_cell": False,
        },
        "memory_filters_active": True,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
    }
    for field, wanted in expected.items():
        if not _exact_equal(manifest.get(field), wanted):
            raise ValueError(
                f"trace manifest {field} mismatch: {manifest.get(field)!r} != {wanted!r}"
            )
    return {field: manifest[field] for field in expected if field != "trace_file"}


def prove_raw_script_mutation_rejected(
    trace: Path, manifest: dict[str, Any], rom: bytes, script: bytes
) -> None:
    mutated = script + b"# semantically inert raw-source mutation\n"
    if parse_script(mutated).normalized_fnv1a64 != parse_script(script).normalized_fnv1a64:
        raise ValueError("internal raw-source mutation changed normalized semantics")
    try:
        verify_manifest(trace, manifest, rom, mutated)
    except ValueError as error:
        if "input_script" not in str(error):
            raise ValueError(f"raw input mutation failed for the wrong reason: {error}") from error
    else:
        raise ValueError("manifest accepted a raw input source mutation")


def verify_pair(rom_path: Path, script_path: Path, trace_a: Path, trace_b: Path) -> None:
    rom = verify_rom(rom_path)
    script = verify_script_source(script_path)
    rows_a = verify_trace(trace_a, rom)
    rows_b = verify_trace(trace_b, rom)
    if trace_a.read_bytes() != trace_b.read_bytes() or rows_a != rows_b:
        raise ValueError("two-run filtered traces are not byte-identical")
    manifest_a = read_manifest(trace_a)
    manifest_b = read_manifest(trace_b)
    identity_a = verify_manifest(trace_a, manifest_a, rom, script)
    identity_b = verify_manifest(trace_b, manifest_b, rom, script)
    if identity_a != identity_b:
        raise ValueError("two-run manifests differ beyond their trace paths")
    prove_raw_script_mutation_rejected(trace_a, manifest_a, rom, script)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--trace-a", required=True, type=Path)
    parser.add_argument("--trace-b", required=True, type=Path)
    args = parser.parse_args()
    try:
        verify_pair(args.rom, args.script, args.trace_a, args.trace_b)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"SDMA modes probe: {error}") from error
    print(
        "PASS SDMA modes immediate/live/shadow/pause/repeat/decrement/hold "
        "semantics, complete filtered trace, and two-run determinism"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
