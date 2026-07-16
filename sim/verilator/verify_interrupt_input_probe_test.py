#!/usr/bin/env python3
"""Adversarial source-level tests for the interrupt/input probe verifier."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
from pathlib import Path

from generate_interrupt_input_probe import (
    EXPECTED_MARKERS as GENERATED_MARKERS,
    FOOTER_OFFSET,
    INPUT_SCRIPT,
    MARKER,
    MARKER_OFFSET,
    PROGRAM_OFFSET,
    ROM_SIZE,
    generate,
    image,
    program,
)
from verify_input_script_manifest import parse_script
from verify_interrupt_input_probe import (
    OPEN_IPL_FNV1A64,
    CAPTURE_CYCLES,
    EXPECTED_MARKERS,
    EXPECTED_NO_INPUT_ROWS,
    EXPECTED_ROWS,
    FRAME_SHA256,
    FRAME_SIZE,
    NO_INPUT_TRACE_SHA256,
    ROM_SHA256,
    SCRIPT_SHA256,
    TRACE_SHA256,
    fnv1a64,
    prove_raw_script_mutation_rejected,
    verify_frame,
    verify_manifest,
    verify_no_input_trace,
    verify_pair,
    verify_rom,
    verify_script_source,
    verify_trace,
)
from verify_trace import FIELDS_V5


Row = tuple[int, int, int, int, int]


def bank_row(row: Row) -> dict[str, object]:
    cycle, address, value, instruction_id, origin_pc = row
    result: dict[str, object] = {field: "" for field in FIELDS_V5}
    result.update(
        cycle=cycle,
        event="bank",
        address=address,
        value=value,
        instruction_id=instruction_id,
        origin_pc=origin_pc,
        origin_status="exact",
    )
    return result


def write_trace(path: Path, rows: tuple[Row, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(bank_row(row))


def make_manifest(trace: Path, rom: bytes, script: bytes | None) -> dict[str, object]:
    trace_bytes = trace.read_bytes()
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
        "events": {"cpu": False, "bank": True, "vram": False, "mem": False, "bg_cell": False},
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
    }
    if script is not None:
        identity = parse_script(script)
        result["input_script"] = {
            "schema": "swan-song-input-script-v1",
            "source_size_bytes": identity.source_size_bytes,
            "source_fnv1a64": identity.source_fnv1a64,
            "normalized_fnv1a64": identity.normalized_fnv1a64,
            "event_count": identity.event_count,
            "applied_events": identity.event_count,
            "completed": True,
            "final_state": "released",
        }
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
        raise AssertionError(f"invalid fixture passed; expected {expected!r}")


def changed(value: object) -> object:
    if type(value) is bool:
        return not value
    if type(value) is int:
        return value + 1
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, dict):
        result = copy.deepcopy(value)
        first = next(iter(result))
        result[first] = changed(result[first])
        return result
    raise AssertionError(f"no mutation for {value!r}")


def main() -> None:
    built = image()
    compiled = program()
    assert len(built) == ROM_SIZE
    assert GENERATED_MARKERS == EXPECTED_MARKERS
    assert bytes(row[2] for row in EXPECTED_ROWS) == EXPECTED_MARKERS
    assert tuple(compiled.marker_origins[value] for value in EXPECTED_MARKERS) == tuple(
        row[4] for row in EXPECTED_ROWS
    )
    success = PROGRAM_OFFSET + compiled.labels["success"]
    assert built[success : success + 2] == b"\xeb\xfe"
    assert EXPECTED_ROWS[-1][4] + 2 == 0xF0000 + compiled.labels["success"]
    assert built[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] == MARKER
    assert built[FOOTER_OFFSET] == 0xEA
    assert int.from_bytes(built[-2:], "little") == sum(built[:-2]) & 0xFFFF
    assert hashlib.sha256(built).hexdigest() == ROM_SHA256
    assert hashlib.sha256(INPUT_SCRIPT).hexdigest() == SCRIPT_SHA256

    with tempfile.TemporaryDirectory(prefix="swansong-interrupt-input-test-") as directory:
        root = Path(directory)
        rom_path, script_path = generate(root / "fixture")
        rom = verify_rom(rom_path)
        script = verify_script_source(script_path)

        traces = [root / "run-a.csv", root / "run-b.csv"]
        frames = [root / "frame-a.rgb", root / "frame-b.rgb"]
        for trace in traces:
            write_trace(trace, EXPECTED_ROWS)
            assert hashlib.sha256(trace.read_bytes()).hexdigest() == TRACE_SHA256
            write_manifest(trace, make_manifest(trace, rom, script))
            verify_trace(trace)
            verify_manifest(trace, make_manifest(trace, rom, script), rom, script)
        for frame in frames:
            frame.write_bytes(b"\xff" * FRAME_SIZE)
            assert hashlib.sha256(frame.read_bytes()).hexdigest() == FRAME_SHA256
            verify_frame(frame)

        no_input = root / "no-input.csv"
        write_trace(no_input, EXPECTED_NO_INPUT_ROWS)
        assert hashlib.sha256(no_input.read_bytes()).hexdigest() == NO_INPUT_TRACE_SHA256
        write_manifest(no_input, make_manifest(no_input, rom, None))
        verify_no_input_trace(no_input, rom)

        verify_pair(
            rom_path,
            script_path,
            no_input,
            traces[0],
            frames[0],
            traces[1],
            frames[1],
        )
        valid_manifest = make_manifest(traces[0], rom, script)
        prove_raw_script_mutation_rejected(traces[0], valid_manifest, rom, script)

        # Every scenario rejects a forged marker, a reordered marker, a shifted
        # cycle, a wrong exact origin, and a wrong retired-instruction ID.
        mutant = root / "mutant.csv"
        for index in range(len(EXPECTED_ROWS)):
            rows = list(EXPECTED_ROWS)
            row = list(rows[index])
            row[2] ^= 0x20
            rows[index] = tuple(row)
            write_trace(mutant, tuple(rows))
            must_fail(lambda: verify_trace(mutant), "marker order")

            rows = list(EXPECTED_ROWS)
            other = index + 1 if index + 1 < len(rows) else index - 1
            row = list(rows[index])
            row[2] = rows[other][2]
            rows[index] = tuple(row)
            write_trace(mutant, tuple(rows))
            must_fail(lambda: verify_trace(mutant), "marker order")

            for offset, error in ((0, "cycle mismatch"), (4, "origin mismatch"), (3, "instruction ID mismatch")):
                rows = list(EXPECTED_ROWS)
                row = list(rows[index])
                row[offset] += 1
                rows[index] = tuple(row)
                write_trace(mutant, tuple(rows))
                must_fail(lambda: verify_trace(mutant), error)

        # The no-input control is allowed only its pre-wait B marker and can
        # neither grow toward nor contain the complete success sequence.
        write_trace(mutant, EXPECTED_ROWS)
        write_manifest(mutant, make_manifest(mutant, rom, None))
        must_fail(lambda: verify_no_input_trace(mutant, rom), "success marker sequence")

        # Every manifest value, field set, and every raw/normalized input
        # binding field is independently covered by an adversarial mutation.
        for field in tuple(valid_manifest):
            bad = copy.deepcopy(valid_manifest)
            bad[field] = changed(bad[field])
            must_fail(
                lambda bad=bad: verify_manifest(traces[0], bad, rom, script),
                "manifest",
            )
        missing = copy.deepcopy(valid_manifest)
        missing.pop("trace_schema")
        must_fail(lambda: verify_manifest(traces[0], missing, rom, script), "field set")
        extra = copy.deepcopy(valid_manifest)
        extra["unexpected"] = False
        must_fail(lambda: verify_manifest(traces[0], extra, rom, script), "field set")
        for field in tuple(valid_manifest["input_script"]):
            bad = copy.deepcopy(valid_manifest)
            binding = bad["input_script"]
            assert isinstance(binding, dict)
            binding[field] = changed(binding[field])
            must_fail(
                lambda bad=bad: verify_manifest(traces[0], bad, rom, script),
                "input_script",
            )

        raw_mutation = script + b"# raw-only mutation\n"
        assert parse_script(raw_mutation).normalized_fnv1a64 == parse_script(script).normalized_fnv1a64
        bad_script = root / "raw-mutated.input"
        bad_script.write_bytes(raw_mutation)
        must_fail(lambda: verify_script_source(bad_script), "fixture mismatch")
        must_fail(
            lambda: verify_manifest(traces[0], valid_manifest, rom, raw_mutation),
            "input_script",
        )
        semantic_mutation = script.replace(b"3000 x2", b"3000 x3", 1)
        assert parse_script(semantic_mutation).normalized_fnv1a64 != parse_script(script).normalized_fnv1a64
        bad_script.write_bytes(semantic_mutation)
        must_fail(lambda: verify_script_source(bad_script), "fixture mismatch")
        must_fail(
            lambda: verify_manifest(traces[0], valid_manifest, rom, semantic_mutation),
            "input_script",
        )

        wrong_rom = root / "wrong.wsc"
        changed_rom = bytearray(rom)
        changed_rom[MARKER_OFFSET] ^= 1
        wrong_rom.write_bytes(changed_rom)
        must_fail(lambda: verify_rom(wrong_rom), "ROM identity mismatch")

        bad_frame = root / "bad.rgb"
        bad_frame.write_bytes(b"\xff" * (FRAME_SIZE - 1))
        must_fail(lambda: verify_frame(bad_frame), "size")
        pixels = bytearray(b"\xff" * FRAME_SIZE)
        pixels[FRAME_SIZE // 2] = 0
        bad_frame.write_bytes(pixels)
        must_fail(lambda: verify_frame(bad_frame), "not the exact blank")

    print("PASS strict interrupt/input generated-probe contracts and adversarial mutations")


if __name__ == "__main__":
    main()
