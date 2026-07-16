#!/usr/bin/env python3
"""Positive and adversarial tests for the strict SDMA modes probe verifier."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
from pathlib import Path

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
    generate,
    image,
    program,
)
from verify_input_script_manifest import parse_script
from verify_sdma_modes_probe import (
    OPEN_IPL_FNV1A64,
    CAPTURE_CYCLES,
    EXPECTED_MARKERS,
    EXPECTED_MEM_ADDRESSES,
    EXPECTED_ROWS,
    INPUT_FIELDS,
    MANIFEST_FIELDS,
    ROM_SHA256,
    SCRIPT_SHA256,
    TRACE_SHA256,
    ExpectedRow,
    fnv1a64,
    prove_raw_script_mutation_rejected,
    verify_manifest,
    verify_pair,
    verify_rom,
    verify_script_source,
    verify_trace,
)
from verify_trace import FIELDS_V5


def csv_row(row: ExpectedRow) -> dict[str, object]:
    result: dict[str, object] = {field: "" for field in FIELDS_V5}
    result.update(cycle=row.cycle, event=row.event, address=row.address, value=row.value)
    if row.event == "bank":
        result.update(
            instruction_id=row.instruction_id,
            origin_pc=row.origin_pc,
            origin_status="exact",
        )
    else:
        result.update(
            initiator="sdma",
            access="read",
            byte_enable=3,
            space="cart_rom_linear",
            mapped_offset=row.mapped_offset,
            origin_status="not_applicable",
        )
    return result


def write_trace(
    path: Path,
    rows: tuple[ExpectedRow, ...] = EXPECTED_ROWS,
    *,
    line_ending: str = "\n",
) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator=line_ending)
        writer.writeheader()
        for row in rows:
            writer.writerow(csv_row(row))


def write_raw_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_manifest(trace: Path, rom: bytes, script: bytes) -> dict[str, object]:
    trace_bytes = trace.read_bytes()
    identity = parse_script(script)
    result: dict[str, object] = {
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
        "open_ipl_size": 8192,
        "open_ipl_fnv1a64": OPEN_IPL_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "input_script": {
            "schema": "swan-song-input-script-v1",
            "source_size_bytes": identity.source_size_bytes,
            "source_fnv1a64": identity.source_fnv1a64,
            "normalized_fnv1a64": identity.normalized_fnv1a64,
            "event_count": identity.event_count,
            "applied_events": identity.event_count,
            "completed": True,
            "final_state": "released",
        },
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
    assert set(result) == MANIFEST_FIELDS
    assert set(result["input_script"]) == INPUT_FIELDS  # type: ignore[arg-type]
    return result


def write_manifest(trace: Path, manifest: dict[str, object]) -> None:
    Path(f"{trace}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def must_fail(call, expected: str) -> None:
    try:
        call()
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid SDMA modes evidence passed; expected {expected!r}")


def changed(value: object) -> object:
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, dict):
        result = copy.deepcopy(value)
        key = next(iter(result))
        result[key] = changed(result[key])
        return result
    raise AssertionError(f"no mutation for {value!r}")


def main() -> None:
    built = image()
    compiled = program()
    assert compiled.data.startswith(bytes((0xFA, 0xB0, 0x80, 0xE6, 0x60)))
    assert len(built) == ROM_SIZE
    assert hashlib.sha256(built).hexdigest() == ROM_SHA256
    assert hashlib.sha256(INPUT_SCRIPT).hexdigest() == SCRIPT_SHA256
    assert GENERATED_MARKERS == EXPECTED_MARKERS
    assert bytes(row.value for row in EXPECTED_ROWS if row.event == "bank") == EXPECTED_MARKERS
    assert tuple(row.address for row in EXPECTED_ROWS if row.event == "mem") == EXPECTED_MEM_ADDRESSES
    assert tuple(compiled.marker_origins[value] for value in EXPECTED_MARKERS) == tuple(
        row.origin_pc for row in EXPECTED_ROWS if row.event == "bank"
    )
    assert all(row.value != FAIL_MARKER for row in EXPECTED_ROWS)
    success = PROGRAM_OFFSET + compiled.labels["success"]
    failed = PROGRAM_OFFSET + compiled.labels["failed"]
    assert built[success : success + 2] == b"\xeb\xfe"
    assert built[failed : failed + 2] == b"\xeb\xfe"
    assert built[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] == MARKER
    assert built[FOOTER_OFFSET] == 0xEA
    assert int.from_bytes(built[-2:], "little") == sum(built[:-2]) & 0xFFFF

    with tempfile.TemporaryDirectory(prefix="swansong-sdma-modes-test-") as directory:
        root = Path(directory)
        rom_path, script_path = generate(root / "fixture")
        rom = verify_rom(rom_path)
        script = verify_script_source(script_path)

        trace_a = root / "a.csv"
        trace_b = root / "b.csv"
        for trace in (trace_a, trace_b):
            write_trace(trace)
            assert hashlib.sha256(trace.read_bytes()).hexdigest() == TRACE_SHA256
            write_manifest(trace, make_manifest(trace, rom, script))
            verify_trace(trace, rom)
            verify_manifest(trace, make_manifest(trace, rom, script), rom, script)
        verify_pair(rom_path, script_path, trace_a, trace_b)
        prove_raw_script_mutation_rejected(
            trace_a, make_manifest(trace_a, rom, script), rom, script
        )

        mutant = root / "mutant.csv"
        valid_raw = [csv_row(row) for row in EXPECTED_ROWS]

        # Every row is bound to its exact cycle/address/value and populated
        # field set.  Event-specific provenance is mutated below as well.
        for index, expected in enumerate(EXPECTED_ROWS):
            for field, needle in (
                ("cycle", "cycle"),
                ("address", "address"),
                ("value", "value"),
            ):
                rows = copy.deepcopy(valid_raw)
                rows[index][field] = int(rows[index][field]) + 1
                write_raw_rows(mutant, rows)
                must_fail(lambda: verify_trace(mutant, rom), needle)

            rows = copy.deepcopy(valid_raw)
            rows[index]["role"] = "forged"
            write_raw_rows(mutant, rows)
            must_fail(lambda: verify_trace(mutant, rom), "populated-field mismatch")

            rows = copy.deepcopy(valid_raw)
            rows[index]["event"] = "mem" if expected.event == "bank" else "bank"
            write_raw_rows(mutant, rows)
            must_fail(lambda: verify_trace(mutant, rom), "populated-field mismatch")

            if expected.event == "bank":
                for field, replacement, needle in (
                    ("instruction_id", int(valid_raw[index]["instruction_id"]) + 1, "instruction"),
                    ("origin_pc", int(valid_raw[index]["origin_pc"]) + 1, "origin"),
                    ("origin_status", "unattributed", "origin"),
                ):
                    rows = copy.deepcopy(valid_raw)
                    rows[index][field] = replacement
                    write_raw_rows(mutant, rows)
                    must_fail(lambda: verify_trace(mutant, rom), needle)
            else:
                for field, replacement, needle in (
                    ("mapped_offset", int(valid_raw[index]["mapped_offset"]) + 1, "mapped_offset"),
                    ("initiator", "gdma", "initiator"),
                    ("access", "write", "access"),
                    ("byte_enable", 1, "byte_enable"),
                    ("space", "iram", "space"),
                    ("origin_status", "exact", "origin"),
                ):
                    rows = copy.deepcopy(valid_raw)
                    rows[index][field] = replacement
                    write_raw_rows(mutant, rows)
                    must_fail(lambda: verify_trace(mutant, rom), needle)

        write_trace(mutant, EXPECTED_ROWS[:-1])
        must_fail(lambda: verify_trace(mutant, rom), "row count")
        write_trace(mutant, EXPECTED_ROWS + (EXPECTED_ROWS[-1],))
        must_fail(lambda: verify_trace(mutant, rom), "cycle")
        reordered = list(EXPECTED_ROWS)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        write_trace(mutant, tuple(reordered))
        must_fail(lambda: verify_trace(mutant, rom), "cycle")

        # Same parsed rows with a noncanonical byte representation are rejected
        # by the trace identity rather than passing on semantic equivalence.
        write_trace(mutant, line_ending="\r\n")
        must_fail(lambda: verify_trace(mutant, rom), "SHA-256")

        # ROM and source identities reject both direct and checksum-preserving
        # changes, including semantically inert raw script text.
        bad_rom = root / "bad.wsc"
        changed_rom = bytearray(rom)
        changed_rom[DATA_OFFSET] += 1
        changed_rom[DATA_OFFSET + 1] -= 1
        bad_rom.write_bytes(changed_rom)
        must_fail(lambda: verify_rom(bad_rom), "ROM identity")
        bad_script = root / "bad.input"
        bad_script.write_bytes(script + b"# inert\n")
        must_fail(lambda: verify_script_source(bad_script), "input script identity")

        # Every manifest field and every input-binding subfield is exact and
        # type-sensitive; missing/extra fields are rejected too.
        valid_manifest = make_manifest(trace_a, rom, script)
        for field in MANIFEST_FIELDS:
            manifest = copy.deepcopy(valid_manifest)
            manifest[field] = changed(manifest[field])
            must_fail(
                lambda manifest=manifest: verify_manifest(
                    trace_a, manifest, rom, script
                ),
                field,
            )
        for field in INPUT_FIELDS:
            manifest = copy.deepcopy(valid_manifest)
            binding = manifest["input_script"]
            assert isinstance(binding, dict)
            binding[field] = changed(binding[field])
            must_fail(
                lambda manifest=manifest: verify_manifest(
                    trace_a, manifest, rom, script
                ),
                "input_script",
            )
        events = valid_manifest["events"]
        assert isinstance(events, dict)
        for field in events:
            manifest = copy.deepcopy(valid_manifest)
            nested = manifest["events"]
            assert isinstance(nested, dict)
            nested[field] = changed(nested[field])
            must_fail(
                lambda manifest=manifest: verify_manifest(
                    trace_a, manifest, rom, script
                ),
                "events",
            )
        for field in ("trace_fnv1a64", "capture_cycles", "rom_size"):
            manifest = copy.deepcopy(valid_manifest)
            manifest[field] = True
            must_fail(
                lambda manifest=manifest: verify_manifest(
                    trace_a, manifest, rom, script
                ),
                field,
            )
        manifest = copy.deepcopy(valid_manifest)
        manifest["extra"] = 1
        must_fail(
            lambda: verify_manifest(trace_a, manifest, rom, script), "field set"
        )
        manifest = copy.deepcopy(valid_manifest)
        del manifest["events"]
        must_fail(
            lambda: verify_manifest(trace_a, manifest, rom, script), "field set"
        )

    print(
        "PASS SDMA modes verifier ROM/script/origin/events/manifest/determinism mutations"
    )


if __name__ == "__main__":
    main()
