#!/usr/bin/env python3
"""Focused positive and mutation tests for the 80186 quirk fixture gate."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from verify_80186_quirks import (
    BG_FIELDS,
    BLANK_FRAME_SHA256,
    CAPTURE_CYCLES,
    CPU_FIELDS,
    DEFAULT_MONO_BIOS_FNV1A64,
    EXPECTED_EVENTS,
    FONT_OFFSET,
    FRAME_SIZE,
    MIN_TERMINAL_TAIL,
    PASS_FRAME_SHA256,
    PASS_TILE,
    RESULT_X,
    ROM_NAME,
    TERMINAL_CS,
    TERMINAL_IP,
    TERMINAL_PC,
    expected_frame,
    fnv1a64,
    sha256,
    verify_frames,
    verify_pair,
    verify_rom,
    verify_sources,
    verify_trace,
)
from verify_trace import FIELDS_V5


def cpu_row(cycle: int, pc: int, cs: int, ip: int) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V5}
    row.update(
        {"cycle": cycle, "event": "cpu", "physical_pc": pc, "cs": cs, "ip": ip}
    )
    assert {field for field, value in row.items() if value != ""} == CPU_FIELDS
    return row


def valid_rows(rom: bytes) -> list[dict[str, object]]:
    rows = [cpu_row(1, 0xFFFF2, 0xFFFF, 2)]
    rows.extend(
        cpu_row(100 + index, TERMINAL_PC, TERMINAL_CS, TERMINAL_IP)
        for index in range(MIN_TERMINAL_TAIL)
    )
    font = rom[FONT_OFFSET : FONT_OFFSET + 128 * 8]
    cycle = 1000
    for result in range(3):
        for tile_row, value in enumerate(font[PASS_TILE * 8 : PASS_TILE * 8 + 8]):
            row: dict[str, object] = {field: "" for field in FIELDS_V5}
            row.update(
                {
                    "cycle": cycle,
                    "event": "bg_cell",
                    "bg_layer": 1,
                    "map_address": 0x1800 + result * 64 + RESULT_X * 2,
                    "map_value": PASS_TILE,
                    "map_x": RESULT_X,
                    "map_y": result,
                    "tile_bank_enabled": 0,
                    "tile_index": PASS_TILE,
                    "palette": 0,
                    "hflip": 0,
                    "vflip": 0,
                    "bpp": 2,
                    "packed": 0,
                    "tile_row": tile_row,
                    "tile_row_address": 0x2000 + PASS_TILE * 16 + tile_row * 2,
                    "tile_row_bytes": 2,
                    "tile_row_value": value,
                    "map_collision": 0,
                    "tile_row_collision": 0,
                }
            )
            assert {field for field, item in row.items() if item != ""} == BG_FIELDS
            rows.append(row)
            cycle += 1
    return rows


def write_trace(path: Path, rows: list[dict[str, object]], rom: bytes) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    trace_bytes = path.read_bytes()
    manifest = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_file": str(path),
        "trace_size_bytes": len(trace_bytes),
        "trace_fnv1a64": fnv1a64(trace_bytes),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": CAPTURE_CYCLES,
        "completed_frames": 2,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "bios_size": 4096,
        "bios_fnv1a64": DEFAULT_MONO_BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": True,
    }
    Path(f"{path}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def must_fail(call, expected: str) -> None:
    try:
        call()
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid 80186 fixture passed; expected {expected!r}")


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    checked_fixture = repository / "testroms/ws-test-suite/80186_quirks"
    verify_sources(checked_fixture)
    checked_rom = verify_rom(checked_fixture / ROM_NAME)
    expected = expected_frame(checked_rom)
    assert len(expected) == FRAME_SIZE
    assert sha256(expected) == PASS_FRAME_SHA256
    assert sha256(b"\xff" * FRAME_SIZE) == BLANK_FRAME_SHA256

    with tempfile.TemporaryDirectory(prefix="swansong-80186-quirks-test-") as directory:
        root = Path(directory)
        fixture = root / "fixture"
        shutil.copytree(checked_fixture, fixture)
        rom_path = fixture / ROM_NAME
        rom = verify_rom(rom_path)
        rows = valid_rows(rom)

        trace_a = root / "a.csv"
        trace_b = root / "b.csv"
        write_trace(trace_a, rows, rom)
        write_trace(trace_b, rows, rom)
        frame0_a = root / "a-frame0.rgb"
        frame1_a = root / "a-frame1.rgb"
        frame0_b = root / "b-frame0.rgb"
        frame1_b = root / "b-frame1.rgb"
        for path in (frame0_a, frame0_b):
            path.write_bytes(b"\xff" * FRAME_SIZE)
        for path in (frame1_a, frame1_b):
            path.write_bytes(expected)

        counts = verify_pair(
            fixture,
            trace_a,
            frame0_a,
            frame1_a,
            trace_b,
            frame0_b,
            frame1_b,
        )
        assert counts["pass_results"] == 3
        assert counts["pass_rows"] == 24

        bad_source = root / "bad-source"
        shutil.copytree(fixture, bad_source)
        with (bad_source / "tests.s").open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(lambda: verify_sources(bad_source), "tests.s SHA-256 mismatch")

        bad_footer = root / "bad-footer.ws"
        changed = bytearray(rom)
        changed[-4] ^= 1
        bad_footer.write_bytes(changed)
        must_fail(lambda: verify_rom(bad_footer), "footer identity mismatch")

        bad_checksum = root / "bad-checksum.ws"
        changed = bytearray(rom)
        changed[0] ^= 1
        bad_checksum.write_bytes(changed)
        must_fail(lambda: verify_rom(bad_checksum), "footer checksum mismatch")

        bad_identity = root / "bad-identity.ws"
        changed = bytearray(rom)
        # Preserve the additive footer checksum while changing the bound ROM.
        changed[0x1EE31] += 1
        changed[0x1EE32] -= 1
        bad_identity.write_bytes(changed)
        must_fail(lambda: verify_rom(bad_identity), "ROM SHA-256 mismatch")

        bad_terminal = root / "bad-terminal.csv"
        terminal_rows = deepcopy(rows)
        terminal_rows[MIN_TERMINAL_TAIL]["physical_pc"] = TERMINAL_PC + 1
        terminal_rows[MIN_TERMINAL_TAIL]["ip"] = TERMINAL_IP + 1
        write_trace(bad_terminal, terminal_rows, rom)
        must_fail(lambda: verify_trace(bad_terminal, rom), "terminal PC")

        bad_result = root / "bad-result.csv"
        result_rows = deepcopy(rows)
        first_bg = 1 + MIN_TERMINAL_TAIL
        result_rows[first_bg]["tile_index"] = 6
        result_rows[first_bg]["map_value"] = 6
        write_trace(bad_result, result_rows, rom)
        must_fail(lambda: verify_trace(bad_result, rom), "FAIL tile")

        bad_frame = root / "bad-frame.rgb"
        changed_frame = bytearray(expected)
        changed_frame[0] ^= 0xFF
        bad_frame.write_bytes(changed_frame)
        must_fail(lambda: verify_frames(frame0_a, bad_frame, rom), "three-PASS frame")

        stale_trace = root / "stale.csv"
        write_trace(stale_trace, rows, rom)
        with stale_trace.open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(lambda: verify_trace(stale_trace, rom), "trace manifest mismatch")

        different_trace = root / "different.csv"
        different_rows = deepcopy(rows)
        different_rows[0] = cpu_row(1, 0xFFFF3, 0xFFFF, 3)
        write_trace(different_trace, different_rows, rom)
        verify_trace(different_trace, rom)
        must_fail(
            lambda: verify_pair(
                fixture,
                trace_a,
                frame0_a,
                frame1_a,
                different_trace,
                frame0_b,
                frame1_b,
            ),
            "not byte-identical",
        )

    print("PASS pinned 80186 quirk verifier source/footer/terminal/results/frame/determinism mutations")


if __name__ == "__main__":
    main()
