#!/usr/bin/env python3
"""Verify deterministic controller replay through the integrated keypad RTL."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from generate_input_replay_probe import (
    INPUT_SCRIPT,
    MARKER_ORIGIN_PCS,
    ROM_SIZE,
    image,
)
from verify_trace import FIELDS_V5


EXPECTED_BANKS = (
    (0xC0, 0x49, MARKER_ORIGIN_PCS[0]),
    (0xC2, 0x4E, MARKER_ORIGIN_PCS[1]),
    (0xC3, 0x50, MARKER_ORIGIN_PCS[2]),
)
EXPECTED_ROWS = (
    (1247, 0xC0, 0x49, 30, MARKER_ORIGIN_PCS[0]),
    (1343, 0xC2, 0x4E, 32, MARKER_ORIGIN_PCS[1]),
    (5279, 0xC3, 0x50, 160, MARKER_ORIGIN_PCS[2]),
)
EXPECTED_NORMALIZED = b"1000 0002\n5000 0000\n"
FRAME_SIZE = 224 * 144 * 3
ROM_SHA256 = "7a9b26d93e6cf7a056dfc0ab60baed180e67974a62645d7b275081b8466c8f15"
SCRIPT_SHA256 = "a6bb22586076045d1e827d5d8221cd460c71a43d9c8ee8fc6f62c8d1bba95fd3"
TRACE_SHA256 = "c7d21e24e4a60a84b265f45d8876a5dfcd3c650d4c89b5132099fc70f8ec5ad8"
FRAME_SHA256 = "b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511"
CAPTURE_CYCLES = 442_241
BIOS_FNV1A64 = "2c83c0c1976b8168"

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


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def number(value: str, field: str, line: int, maximum: int) -> int:
    if not value or not value.isdecimal():
        raise ValueError(f"line {line}: {field} is not a decimal integer: {value!r}")
    result = int(value, 10)
    if result > maximum:
        raise ValueError(f"line {line}: {field} exceeds {maximum}: {result}")
    return result


def verify_rom(path: Path) -> bytes:
    data = path.read_bytes()
    expected = image()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != ROM_SIZE or data != expected or digest != ROM_SHA256:
        raise ValueError(
            f"ROM identity mismatch: size={len(data)}, "
            f"sha256={digest}"
        )
    return data


def verify_script_source(path: Path) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if data != INPUT_SCRIPT or digest != SCRIPT_SHA256:
        raise ValueError(
            "input script fixture mismatch: "
            f"size={len(data)}, fnv1a64={fnv1a64(data)}, sha256={digest}"
        )
    return data


def verify_trace(path: Path) -> tuple[tuple[int, int, int, int, int], ...]:
    observed: list[tuple[int, int, int, int, int]] = []
    previous_cycle = -1
    previous_instruction_id = 0
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(
                f"bank replay requires exact v5 trace header; got {reader.fieldnames!r}"
            )
        for line, row in enumerate(reader, start=2):
            if row["event"] != "bank":
                raise ValueError(f"line {line}: unexpected event {row['event']!r}")
            populated = [field for field in EMPTY_BANK_FIELDS if row[field]]
            if populated:
                raise ValueError(
                    f"line {line}: unexpected bank fields: {', '.join(populated)}"
                )
            cycle = number(row["cycle"], "cycle", line, (1 << 64) - 1)
            if cycle <= previous_cycle:
                raise ValueError(
                    f"line {line}: cycle {cycle} does not follow {previous_cycle}"
                )
            previous_cycle = cycle
            if row["origin_status"] != "exact":
                raise ValueError(
                    f"line {line}: bank origin is not exact: {row['origin_status']!r}"
                )
            instruction_id = number(
                row["instruction_id"], "instruction_id", line, 0xFFFFFFFF
            )
            if instruction_id <= previous_instruction_id:
                raise ValueError(
                    f"line {line}: instruction ID {instruction_id} does not follow "
                    f"{previous_instruction_id}"
                )
            previous_instruction_id = instruction_id
            observed.append(
                (
                    cycle,
                    number(row["address"], "address", line, 0xFF),
                    number(row["value"], "value", line, 0xFF),
                    instruction_id,
                    number(row["origin_pc"], "origin_pc", line, 0xFFFFF),
                )
            )

    identity = tuple((address, value, pc) for _, address, value, _, pc in observed)
    if identity != EXPECTED_BANKS:
        raise ValueError(f"unexpected input-replay bank marker: {identity!r}")
    if tuple(observed) != EXPECTED_ROWS:
        raise ValueError(f"unexpected exact input-replay bank rows: {observed!r}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != TRACE_SHA256:
        raise ValueError(f"input-replay trace SHA-256 mismatch: {digest}")
    return tuple(observed)


def verify_no_input_trace(path: Path) -> None:
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(
                f"no-input control requires exact v5 trace header; "
                f"got {reader.fieldnames!r}"
            )
        first = next(reader, None)
        if first is not None:
            raise ValueError(
                "input marker was reachable without a replay script: "
                f"{first!r}"
            )
    trace_bytes = path.read_bytes()
    manifest = read_manifest(path)
    if "input_script" in manifest:
        raise ValueError("no-input control unexpectedly has an input_script manifest")
    required = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_file": str(path),
        "trace_size_bytes": len(trace_bytes),
        "trace_fnv1a64": fnv1a64(trace_bytes),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": CAPTURE_CYCLES,
        "completed_frames": 1,
        "rom_size": ROM_SIZE,
        "rom_fnv1a64": fnv1a64(image()),
        "bios_size": 4096,
        "bios_fnv1a64": BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": {
            "cpu": False,
            "bank": True,
            "vram": False,
            "mem": False,
            "bg_cell": False,
        },
    }
    mismatches = [
        f"{field}={manifest.get(field)!r} (expected {expected!r})"
        for field, expected in required.items()
        if manifest.get(field) != expected
    ]
    if mismatches:
        raise ValueError("no-input manifest mismatch: " + "; ".join(mismatches))


def read_manifest(trace: Path) -> dict[str, Any]:
    path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"trace manifest {path} is not an object")
    return manifest


def verify_manifest(
    trace: Path,
    manifest: dict[str, Any],
    rom: bytes,
    script: bytes,
) -> dict[str, Any]:
    trace_bytes = trace.read_bytes()
    expected_fields = {
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
    if set(manifest) != expected_fields:
        raise ValueError(
            "trace manifest field set mismatch: "
            f"missing={sorted(expected_fields - set(manifest))}, "
            f"extra={sorted(set(manifest) - expected_fields)}"
        )

    fixed = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_size_bytes": len(trace_bytes),
        "trace_fnv1a64": fnv1a64(trace_bytes),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": CAPTURE_CYCLES,
        "completed_frames": 1,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "bios_size": 4096,
        "bios_fnv1a64": BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": {
            "cpu": False,
            "bank": True,
            "vram": False,
            "mem": False,
            "bg_cell": False,
        },
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
    }
    mismatches = [
        f"{field}={manifest.get(field)!r} (expected {expected!r})"
        for field, expected in fixed.items()
        if manifest.get(field) != expected
    ]
    if mismatches:
        raise ValueError("trace manifest mismatch: " + "; ".join(mismatches))
    if manifest.get("trace_file") != str(trace):
        raise ValueError(
            f"trace_file mismatch: {manifest.get('trace_file')!r} != {str(trace)!r}"
        )
    expected_input = {
        "schema": "swan-song-input-script-v1",
        "source_size_bytes": len(script),
        "source_fnv1a64": fnv1a64(script),
        "normalized_fnv1a64": fnv1a64(EXPECTED_NORMALIZED),
        "event_count": 2,
        "applied_events": 2,
        "completed": True,
        "final_state": "released",
    }
    if manifest.get("input_script") != expected_input:
        raise ValueError(
            "input script manifest mismatch: "
            f"{manifest.get('input_script')!r} != {expected_input!r}"
        )
    return {field: manifest[field] for field in fixed if field != "trace_file"}


def verify_frame(path: Path) -> bytes:
    frame = path.read_bytes()
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"invalid frame size {len(frame)} at {path}")
    digest = hashlib.sha256(frame).hexdigest()
    if digest != FRAME_SHA256:
        raise ValueError(f"input-replay frame SHA-256 mismatch: {digest}")
    return frame


def prove_raw_script_mutation_rejected(
    trace: Path,
    manifest: dict[str, Any],
    rom: bytes,
    script: bytes,
) -> None:
    # A comment preserves normalized semantics but changes the bound raw source.
    mutated = script + b"# semantically inert raw-source mutation\n"
    try:
        verify_manifest(trace, manifest, rom, mutated)
    except ValueError as error:
        if "input script manifest mismatch" not in str(error):
            raise ValueError(
                f"raw script mutation failed for the wrong reason: {error}"
            ) from error
    else:
        raise ValueError("manifest accepted a mutated raw input script")


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
    verify_no_input_trace(no_input_trace)
    rows_a = verify_trace(trace_a)
    rows_b = verify_trace(trace_b)
    if trace_a.read_bytes() != trace_b.read_bytes() or rows_a != rows_b:
        raise ValueError("replayed bank traces are not byte-identical")
    first_frame = verify_frame(frame_a)
    second_frame = verify_frame(frame_b)
    if first_frame != second_frame:
        raise ValueError("replayed output frames are not byte-identical")

    manifest_a = read_manifest(trace_a)
    manifest_b = read_manifest(trace_b)
    semantics_a = verify_manifest(trace_a, manifest_a, rom, script)
    semantics_b = verify_manifest(trace_b, manifest_b, rom, script)
    if semantics_a != semantics_b:
        raise ValueError("replay manifests differ beyond their trace paths")
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
        raise SystemExit(f"input-replay probe: {error}") from error
    print(
        "PASS input replay no-input isolation, raw+normalized identity, "
        "keypad marker, two-run trace/frame determinism, and mutation rejection"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
