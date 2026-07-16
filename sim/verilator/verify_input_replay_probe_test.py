#!/usr/bin/env python3
"""Focused source-level tests for the input-replay probe and verifier."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from pathlib import Path

from generate_input_replay_probe import (
    FOOTER_OFFSET,
    INPUT_SCRIPT,
    MARKER,
    MARKER_OFFSET,
    MARKER_ORIGIN_PCS,
    PROGRAM,
    PROGRAM_OFFSET,
    ROM_SIZE,
    generate,
    image,
)
from verify_input_replay_probe import (
    OPEN_IPL_FNV1A64,
    CAPTURE_CYCLES,
    EXPECTED_BANKS,
    EXPECTED_NORMALIZED,
    EXPECTED_ROWS,
    FRAME_SHA256,
    FRAME_SIZE,
    ROM_SHA256,
    SCRIPT_SHA256,
    TRACE_SHA256,
    fnv1a64,
    prove_raw_script_mutation_rejected,
    verify_manifest,
    verify_no_input_trace,
    verify_rom,
    verify_script_source,
    verify_trace,
    verify_frame,
)
from verify_trace import FIELDS_V5


def bank_row(
    cycle: int, address: int, value: int, instruction_id: int, origin_pc: int
) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V5}
    row.update(
        {
            "cycle": cycle,
            "event": "bank",
            "address": address,
            "value": value,
            "instruction_id": instruction_id,
            "origin_pc": origin_pc,
            "origin_status": "exact",
        }
    )
    return row


def write_trace(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        for cycle, address, value, instruction_id, pc in EXPECTED_ROWS:
            writer.writerow(bank_row(cycle, address, value, instruction_id, pc))


def manifest(trace: Path, rom: bytes, script: bytes) -> dict[str, object]:
    trace_bytes = trace.read_bytes()
    return {
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
        "open_ipl_size": 4096,
        "open_ipl_fnv1a64": OPEN_IPL_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "input_script": {
            "schema": "swan-song-input-script-v1",
            "source_size_bytes": len(script),
            "source_fnv1a64": fnv1a64(script),
            "normalized_fnv1a64": fnv1a64(EXPECTED_NORMALIZED),
            "event_count": 2,
            "applied_events": 2,
            "completed": True,
            "final_state": "released",
        },
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


def must_fail(call, expected: str) -> None:
    try:
        call()
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid fixture passed; expected {expected!r}")


def main() -> None:
    built = image()
    assert len(built) == ROM_SIZE
    assert built[PROGRAM_OFFSET : PROGRAM_OFFSET + len(PROGRAM)] == PROGRAM
    assert built[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] == MARKER
    assert built[FOOTER_OFFSET] == 0xEA
    assert built[FOOTER_OFFSET + 4] == 0xF0
    assert built[FOOTER_OFFSET + 10] == 0x00
    assert built[FOOTER_OFFSET + 12] == 0x04
    assert int.from_bytes(built[-2:], "little") == sum(built[:-2]) & 0xFFFF
    assert MARKER_ORIGIN_PCS == (0xF0011, 0xF0015, 0xF0023)
    assert hashlib.sha256(built).hexdigest() == ROM_SHA256
    assert hashlib.sha256(INPUT_SCRIPT).hexdigest() == SCRIPT_SHA256

    with tempfile.TemporaryDirectory(prefix="swansong-input-replay-test-") as directory:
        root = Path(directory)
        rom_path, script_path = generate(root / "generated")
        rom = verify_rom(rom_path)
        script = verify_script_source(script_path)

        trace = root / "events.csv"
        write_trace(trace)
        assert hashlib.sha256(trace.read_bytes()).hexdigest() == TRACE_SHA256
        rows = verify_trace(trace)
        assert len(rows) == 3
        valid_manifest = manifest(trace, rom, script)
        verify_manifest(trace, valid_manifest, rom, script)
        prove_raw_script_mutation_rejected(trace, valid_manifest, rom, script)

        no_input = root / "no-input.csv"
        with no_input.open("w", newline="", encoding="utf-8") as output:
            csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n").writeheader()
        no_input_manifest = manifest(no_input, rom, script)
        no_input_manifest.pop("input_script")
        no_input_manifest["trace_file"] = str(no_input)
        no_input_manifest["trace_size_bytes"] = no_input.stat().st_size
        no_input_manifest["trace_fnv1a64"] = fnv1a64(no_input.read_bytes())
        Path(f"{no_input}.manifest.json").write_text(
            json.dumps(no_input_manifest), encoding="utf-8"
        )
        verify_no_input_trace(no_input)
        with no_input.open("a", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
            writer.writerow(bank_row(*EXPECTED_ROWS[0]))
        must_fail(lambda: verify_no_input_trace(no_input), "reachable without")

        wrong_marker = root / "wrong-marker.csv"
        write_trace(wrong_marker)
        lines = wrong_marker.read_text(encoding="utf-8").splitlines()
        lines[2] = lines[2].replace(",78,", ",79,")
        wrong_marker.write_text("\n".join(lines) + "\n", encoding="utf-8")
        must_fail(lambda: verify_trace(wrong_marker), "unexpected input-replay bank marker")

        wrong_script = root / "mutated.input"
        wrong_script.write_bytes(INPUT_SCRIPT + b"# mutation\n")
        must_fail(lambda: verify_script_source(wrong_script), "fixture mismatch")
        must_fail(
            lambda: verify_manifest(trace, valid_manifest, rom, wrong_script.read_bytes()),
            "input script manifest mismatch",
        )

        wrong_rom = root / "wrong.ws"
        changed = bytearray(rom)
        changed[MARKER_OFFSET] ^= 1
        wrong_rom.write_bytes(changed)
        must_fail(lambda: verify_rom(wrong_rom), "ROM identity mismatch")

        frame = root / "frame.rgb"
        # A same-sized synthetic frame is still rejected by the calibrated
        # image identity; the end-to-end regression supplies the real frame.
        frame.write_bytes(b"\0" * FRAME_SIZE)
        assert hashlib.sha256(frame.read_bytes()).hexdigest() != FRAME_SHA256
        must_fail(lambda: verify_frame(frame), "frame SHA-256 mismatch")

        manifest_path = Path(f"{trace}.manifest.json")
        manifest_path.write_text(json.dumps(valid_manifest), encoding="utf-8")
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded["input_script"]["source_fnv1a64"] == fnv1a64(INPUT_SCRIPT)

    print("PASS generated input-replay probe/verifier contracts and mutations")


if __name__ == "__main__":
    main()
