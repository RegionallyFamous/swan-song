#!/usr/bin/env python3
"""Positive and adversarial tests for the pinned SoC interrupt fixture gate."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from verify_interrupts_fixture import (
    BG_FIELDS,
    BLANK_FRAME_SHA256,
    CAPTURE_CYCLES,
    CAPTURE_FRAMES,
    CPU_FIELDS,
    DEFAULT_MONO_BIOS_FNV1A64,
    EXPECTED_EVENTS,
    FAIL_TILE,
    FONT_OFFSET,
    FONT_SIZE,
    FRAME_SIZE,
    MIN_TERMINAL_TAIL,
    PASS_FRAME_SHA256,
    PASS_TILE,
    RESULT_POSITIONS,
    ROM_NAME,
    TERMINAL_CS,
    TERMINAL_IP,
    TERMINAL_PC,
    WIDTH,
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


def pass_row(
    rom: bytes, cycle: int, map_x: int, map_y: int, tile_row: int
) -> dict[str, object]:
    font = rom[FONT_OFFSET : FONT_OFFSET + FONT_SIZE]
    row: dict[str, object] = {field: "" for field in FIELDS_V5}
    row.update(
        {
            "cycle": cycle,
            "event": "bg_cell",
            "bg_layer": 1,
            "map_address": 0x1800 + map_y * 64 + map_x * 2,
            "map_value": PASS_TILE,
            "map_x": map_x,
            "map_y": map_y,
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
            "tile_row_value": font[PASS_TILE * 8 + tile_row],
            "map_collision": 0,
            "tile_row_collision": 0,
        }
    )
    assert {field for field, value in row.items() if value != ""} == BG_FIELDS
    return row


def valid_rows(rom: bytes) -> list[dict[str, object]]:
    rows = [cpu_row(1, 0xFFFF2, 0xFFFF, 2)]
    rows.extend(
        cpu_row(100 + index, TERMINAL_PC, TERMINAL_CS, TERMINAL_IP)
        for index in range(MIN_TERMINAL_TAIL)
    )
    cycle = 1000
    for map_x, map_y in RESULT_POSITIONS:
        for tile_row in range(8):
            rows.append(pass_row(rom, cycle, map_x, map_y, tile_row))
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
        "completed_frames": CAPTURE_FRAMES,
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
        raise AssertionError(f"invalid interrupt fixture passed; expected {expected!r}")


def frame_with_fail(rom: bytes) -> bytes:
    frame = bytearray(expected_frame(rom))
    font = rom[FONT_OFFSET : FONT_OFFSET + FONT_SIZE]
    tile_x, tile_y = RESULT_POSITIONS[0]
    for row in range(8):
        for column in range(8):
            pixel = ((tile_y * 8 + row) * WIDTH + tile_x * 8 + column) * 3
            frame[pixel : pixel + 3] = b"\xff\xff\xff"
            if font[FAIL_TILE * 8 + row] & (0x80 >> column):
                frame[pixel : pixel + 3] = b"\x00\x00\x00"
    return bytes(frame)


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    checked_fixture = repository / "testroms/ws-test-suite/interrupts"
    verify_sources(checked_fixture)
    checked_rom = verify_rom(checked_fixture / ROM_NAME)
    expected = expected_frame(checked_rom)
    assert len(expected) == FRAME_SIZE
    assert sha256(expected) == PASS_FRAME_SHA256
    assert sha256(b"\xff" * FRAME_SIZE) == BLANK_FRAME_SHA256

    with tempfile.TemporaryDirectory(prefix="swansong-interrupts-test-") as directory:
        root = Path(directory)
        fixture = root / "fixture"
        shutil.copytree(checked_fixture, fixture)
        rom = verify_rom(fixture / ROM_NAME)
        rows = valid_rows(rom)

        trace_a = root / "a.csv"
        trace_b = root / "b.csv"
        write_trace(trace_a, rows, rom)
        write_trace(trace_b, rows, rom)
        frame0_a = root / "a-frame0.rgb"
        final_a = root / "a-final.rgb"
        frame0_b = root / "b-frame0.rgb"
        final_b = root / "b-final.rgb"
        for path in (frame0_a, frame0_b):
            path.write_bytes(b"\xff" * FRAME_SIZE)
        for path in (final_a, final_b):
            path.write_bytes(expected)

        counts = verify_pair(
            fixture, trace_a, frame0_a, final_a, trace_b, frame0_b, final_b
        )
        assert counts["pass_results"] == 13
        assert counts["pass_rows"] == 104

        bad_source = root / "bad-source"
        shutil.copytree(fixture, bad_source)
        with (bad_source / "main.c").open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(lambda: verify_sources(bad_source), "main.c SHA-256 mismatch")

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
        # Preserve the additive checksum while changing the bound program.
        changed[0x1ED51] += 1
        changed[0x1ED52] -= 1
        bad_identity.write_bytes(changed)
        must_fail(lambda: verify_rom(bad_identity), "ROM SHA-256 mismatch")

        bad_terminal = root / "bad-terminal.csv"
        terminal_rows = deepcopy(rows)
        terminal_rows[MIN_TERMINAL_TAIL]["physical_pc"] = TERMINAL_PC + 1
        terminal_rows[MIN_TERMINAL_TAIL]["ip"] = TERMINAL_IP + 1
        write_trace(bad_terminal, terminal_rows, rom)
        must_fail(lambda: verify_trace(bad_terminal, rom), "left terminal loop")

        first_bg = 1 + MIN_TERMINAL_TAIL
        bad_result = root / "bad-result.csv"
        result_rows = deepcopy(rows)
        for row in result_rows[first_bg : first_bg + 8]:
            row["tile_index"] = FAIL_TILE
            row["map_value"] = FAIL_TILE
        write_trace(bad_result, result_rows, rom)
        must_fail(lambda: verify_trace(bad_result, rom), "FAIL tile")

        missing_row = root / "missing-row.csv"
        missing_rows = deepcopy(rows)
        del missing_rows[first_bg + 7]
        write_trace(missing_row, missing_rows, rom)
        must_fail(lambda: verify_trace(missing_row, rom), "only 7 PASS rows")

        reordered = root / "reordered.csv"
        reordered_rows = deepcopy(rows)
        left = reordered_rows[first_bg]
        right = reordered_rows[first_bg + 1]
        fields = (
            "tile_row",
            "tile_row_address",
            "tile_row_value",
        )
        for field in fields:
            left[field], right[field] = right[field], left[field]
        write_trace(reordered, reordered_rows, rom)
        must_fail(lambda: verify_trace(reordered, rom), "row sequence mismatch")

        wrong_map = root / "wrong-map.csv"
        wrong_map_rows = deepcopy(rows)
        wrong_map_rows[first_bg]["map_address"] = int(
            wrong_map_rows[first_bg]["map_address"]
        ) + 2
        write_trace(wrong_map, wrong_map_rows, rom)
        must_fail(lambda: verify_trace(wrong_map, rom), "map_address mismatch")

        collision = root / "collision.csv"
        collision_rows = deepcopy(rows)
        collision_rows[first_bg]["tile_row_collision"] = 1
        write_trace(collision, collision_rows, rom)
        must_fail(lambda: verify_trace(collision, rom), "tile_row_collision mismatch")

        early_only = root / "early-only.csv"
        early_pass_rows = deepcopy(rows[first_bg:])
        for index, row in enumerate(early_pass_rows):
            row["cycle"] = 10 + index
        early_rows = [cpu_row(1, 0xFFFF2, 0xFFFF, 2)]
        early_rows.extend(early_pass_rows)
        early_rows.extend(
            cpu_row(1000 + index, TERMINAL_PC, TERMINAL_CS, TERMINAL_IP)
            for index in range(MIN_TERMINAL_TAIL)
        )
        write_trace(early_only, early_rows, rom)
        must_fail(
            lambda: verify_trace(early_only, rom),
            "no complete post-terminal PASS raster",
        )

        bad_frame = root / "bad-frame.rgb"
        bad_frame.write_bytes(frame_with_fail(rom))
        must_fail(
            lambda: verify_frames(frame0_a, bad_frame, rom),
            "final thirteen-PASS frame",
        )

        stale_trace = root / "stale.csv"
        write_trace(stale_trace, rows, rom)
        with stale_trace.open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(lambda: verify_trace(stale_trace, rom), "trace manifest mismatch")

        bad_manifest = root / "bad-manifest.csv"
        write_trace(bad_manifest, rows, rom)
        manifest_path = Path(f"{bad_manifest}.manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["events"]["bg_cell"] = False
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        must_fail(lambda: verify_trace(bad_manifest, rom), "trace manifest mismatch")

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
                final_a,
                different_trace,
                frame0_b,
                final_b,
            ),
            "not byte-identical",
        )

    print(
        "PASS pinned interrupt verifier "
        "source/footer/terminal/13-results/rows/frame/manifest/determinism mutations"
    )


if __name__ == "__main__":
    main()
