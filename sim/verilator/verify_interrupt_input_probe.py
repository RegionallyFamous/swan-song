#!/usr/bin/env python3
"""Strictly verify the generated interrupt/input integration probe."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from generate_interrupt_input_probe import (
    EXPECTED_MARKERS as GENERATED_MARKERS,
    INPUT_SCRIPT,
    MARKER,
    MARKER_OFFSET,
    PROGRAM_OFFSET,
    PROGRAM_PC,
    ROM_SIZE,
    image,
    program,
)
from verify_input_script_manifest import ScriptIdentity, parse_script
from verify_trace import FIELDS_V5


# cycle, address, value, retired instruction ID, exact OUT origin PC
EXPECTED_ROWS = (
    (899, 0xC0, ord("B"), 17, 983070),
    (3311, 0xC0, ord("D"), 66, 983113),
    (11399, 0xC0, ord("V"), 214, 983166),
    (12071, 0xC0, ord("I"), 222, 983329),
    (24683, 0xC0, ord("H"), 457, 983213),
    (28379, 0xC0, ord("R"), 525, 983229),
    (28895, 0xC0, ord("P"), 535, 983255),
    (29411, 0xC0, ord("A"), 545, 983281),
    (37235, 0xC0, ord("C"), 687, 983301),
    (42155, 0xC0, ord("Z"), 776, 983311),
)
EXPECTED_NO_INPUT_ROWS = (EXPECTED_ROWS[0],)
EXPECTED_MARKERS = b"BDVIHRPACZ"
SCENARIOS = (
    "base-mask",
    "disabled-edge",
    "vector-status",
    "IRQ-dispatch",
    "held-key-clear",
    "repeat-edge",
    "masked-pending",
    "acknowledge",
    "combined-rows",
    "terminal-success",
)

ROM_SHA256 = "0cee15c78f49b1ae32b32eff90c3efdd29a904c6637d4c800885fe948c97acb2"
SCRIPT_SHA256 = "0e35059c6aea64aea1c056de0947336d1e603812a9aae9ebd67b8ef830a316ec"
TRACE_SHA256 = "fdaabc37f4733dbc7caba902693259f21919f61351da9e595644d74f5224096c"
NO_INPUT_TRACE_SHA256 = "2c8fcfebf915ed26d401392a5c27323723ca940808cf08d0752f872190ff31e1"
FRAME_SHA256 = "b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511"
FRAME_SIZE = 224 * 144 * 3
CAPTURE_CYCLES = 442_241
BIOS_FNV1A64 = "bde71f09ac34c168"

EXPECTED_SCRIPT_IDENTITY = ScriptIdentity(
    source_size_bytes=142,
    source_fnv1a64="ff4f6ff6222b5c4b",
    normalized_fnv1a64="fc2e3fa64b0cd028",
    event_count=8,
    final_cycle=42_000,
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
EMPTY_BANK_FIELDS = tuple(
    field for field in FIELDS_V5 if field not in POPULATED_BANK_FIELDS
)
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
        raise ValueError(f"line {line}: {field} is not an ASCII decimal integer: {value!r}")
    result = int(value, 10)
    if result > maximum:
        raise ValueError(f"line {line}: {field} exceeds {maximum}: {result}")
    return result


def _generator_contract(rom: bytes) -> None:
    compiled = program()
    if GENERATED_MARKERS != EXPECTED_MARKERS:
        raise ValueError(f"generator marker order changed: {GENERATED_MARKERS!r}")
    origins = tuple(compiled.marker_origins[value] for value in EXPECTED_MARKERS)
    expected_origins = tuple(row[4] for row in EXPECTED_ROWS)
    if origins != expected_origins:
        raise ValueError(f"generator marker origins changed: {origins!r}")
    success_pc = PROGRAM_PC + compiled.labels["success"]
    success_offset = PROGRAM_OFFSET + compiled.labels["success"]
    if EXPECTED_ROWS[-1][2] != ord("Z") or EXPECTED_ROWS[-1][4] + 2 != success_pc:
        raise ValueError("terminal Z marker does not fall through to success")
    if rom[success_offset : success_offset + 2] != b"\xeb\xfe":
        raise ValueError("terminal success loop is not JMP $ at the Z fallthrough")
    if rom[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] != MARKER:
        raise ValueError("ROM probe identity marker mismatch")


def verify_rom(path: Path) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != ROM_SIZE or data != image() or digest != ROM_SHA256:
        raise ValueError(f"ROM identity mismatch: size={len(data)}, sha256={digest}")
    _generator_contract(data)
    return data


def verify_script_source(path: Path) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if data != INPUT_SCRIPT or digest != SCRIPT_SHA256:
        raise ValueError(
            "input script fixture mismatch: "
            f"size={len(data)}, fnv1a64={fnv1a64(data)}, sha256={digest}"
        )
    identity = parse_script(data, str(path))
    if identity != EXPECTED_SCRIPT_IDENTITY:
        raise ValueError(f"input script normalized identity changed: {identity!r}")
    return data


def _read_bank_rows(path: Path) -> tuple[tuple[int, int, int, int, int], ...]:
    observed: list[tuple[int, int, int, int, int]] = []
    previous_cycle = -1
    previous_instruction_id = 0
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(f"exact v5 bank trace header required; got {reader.fieldnames!r}")
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"line {line}: malformed CSV row")
            if row["event"] != "bank":
                raise ValueError(f"line {line}: unexpected event {row['event']!r}")
            populated = [field for field in EMPTY_BANK_FIELDS if row[field]]
            if populated:
                raise ValueError(f"line {line}: unexpected bank fields: {', '.join(populated)}")
            if row["origin_status"] != "exact":
                raise ValueError(f"line {line}: bank origin is not exact: {row['origin_status']!r}")
            cycle = _number(row["cycle"], "cycle", line, (1 << 64) - 1)
            instruction_id = _number(row["instruction_id"], "instruction_id", line, 0xFFFFFFFF)
            if cycle <= previous_cycle:
                raise ValueError(f"line {line}: cycle {cycle} does not follow {previous_cycle}")
            if instruction_id <= previous_instruction_id:
                raise ValueError(
                    f"line {line}: instruction ID {instruction_id} does not follow {previous_instruction_id}"
                )
            previous_cycle = cycle
            previous_instruction_id = instruction_id
            observed.append(
                (
                    cycle,
                    _number(row["address"], "address", line, 0xFF),
                    _number(row["value"], "value", line, 0xFF),
                    instruction_id,
                    _number(row["origin_pc"], "origin_pc", line, 0xFFFFF),
                )
            )
    return tuple(observed)


def _require_rows(
    observed: tuple[tuple[int, int, int, int, int], ...],
    expected: tuple[tuple[int, int, int, int, int], ...],
    description: str,
) -> None:
    if len(observed) != len(expected):
        raise ValueError(f"{description} row count mismatch: {len(observed)} != {len(expected)}")
    if bytes(row[2] for row in observed) != bytes(row[2] for row in expected):
        raise ValueError(f"{description} scenario marker order mismatch")
    fields = ("cycle", "address", "marker", "instruction ID", "origin")
    for index, (actual, wanted) in enumerate(zip(observed, expected, strict=True)):
        for offset, field in enumerate(fields):
            if actual[offset] != wanted[offset]:
                scenario = SCENARIOS[index] if len(expected) == len(SCENARIOS) else "base-mask"
                raise ValueError(
                    f"{description} {scenario} {field} mismatch: "
                    f"{actual[offset]} != {wanted[offset]}"
                )


def verify_trace(path: Path) -> tuple[tuple[int, int, int, int, int], ...]:
    observed = _read_bank_rows(path)
    _require_rows(observed, EXPECTED_ROWS, "interrupt/input")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != TRACE_SHA256:
        raise ValueError(f"interrupt/input trace SHA-256 mismatch: {digest}")
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
    trace: Path, manifest: dict[str, Any], rom: bytes, script: bytes | None
) -> dict[str, Any]:
    trace_bytes = trace.read_bytes()
    expected_fields = MANIFEST_FIELDS if script is not None else MANIFEST_FIELDS - {"input_script"}
    if set(manifest) != expected_fields:
        raise ValueError(
            "trace manifest field set mismatch: "
            f"missing={sorted(expected_fields - set(manifest))}, "
            f"extra={sorted(set(manifest) - expected_fields)}"
        )
    expected: dict[str, Any] = {
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
        "events": {"cpu": False, "bank": True, "vram": False, "mem": False, "bg_cell": False},
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
    }
    if script is not None:
        expected["input_script"] = _expected_input(script)
        binding = manifest.get("input_script")
        if not isinstance(binding, dict) or set(binding) != INPUT_FIELDS:
            raise ValueError("input_script manifest field set mismatch")
    for field, wanted in expected.items():
        if not _exact_equal(manifest.get(field), wanted):
            raise ValueError(
                f"trace manifest {field} mismatch: {manifest.get(field)!r} != {wanted!r}"
            )
    return {field: manifest[field] for field in expected if field != "trace_file"}


def verify_no_input_trace(path: Path, rom: bytes | None = None) -> None:
    observed = _read_bank_rows(path)
    if EXPECTED_MARKERS in bytes(row[2] for row in observed):
        raise ValueError("no-input control reached the success marker sequence")
    _require_rows(observed, EXPECTED_NO_INPUT_ROWS, "no-input control")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != NO_INPUT_TRACE_SHA256:
        raise ValueError(f"no-input trace SHA-256 mismatch: {digest}")
    verify_manifest(path, read_manifest(path), image() if rom is None else rom, None)


def verify_frame(path: Path) -> bytes:
    frame = path.read_bytes()
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"invalid blank frame size {len(frame)} at {path}")
    if frame != b"\xff" * FRAME_SIZE:
        raise ValueError(f"frame is not the exact blank white frame: {path}")
    digest = hashlib.sha256(frame).hexdigest()
    if digest != FRAME_SHA256:
        raise ValueError(f"blank frame SHA-256 mismatch: {digest}")
    return frame


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


def verify_pair(
    rom_path: Path,
    script_path: Path,
    no_input_trace: Path,
    trace_a: Path,
    frame_a: Path,
    trace_b: Path,
    frame_b: Path,
) -> None:
    rom = verify_rom(rom_path)
    script = verify_script_source(script_path)
    verify_no_input_trace(no_input_trace, rom)
    rows_a = verify_trace(trace_a)
    rows_b = verify_trace(trace_b)
    if trace_a.read_bytes() != trace_b.read_bytes() or rows_a != rows_b:
        raise ValueError("two-run bank traces are not byte-identical")
    first_frame = verify_frame(frame_a)
    second_frame = verify_frame(frame_b)
    if first_frame != second_frame:
        raise ValueError("two-run blank frames are not byte-identical")
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
    parser.add_argument("--no-input-trace", required=True, type=Path)
    parser.add_argument("--trace-a", required=True, type=Path)
    parser.add_argument("--frame-a", required=True, type=Path)
    parser.add_argument("--trace-b", required=True, type=Path)
    parser.add_argument("--frame-b", required=True, type=Path)
    args = parser.parse_args()
    try:
        verify_pair(
            args.rom,
            args.script,
            args.no_input_trace,
            args.trace_a,
            args.frame_a,
            args.trace_b,
            args.frame_b,
        )
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"interrupt/input probe: {error}") from error
    print(
        "PASS interrupt/input probe exact scenarios, terminal loop, no-input isolation, "
        "raw+normalized identity, blank frame, and two-run determinism"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
