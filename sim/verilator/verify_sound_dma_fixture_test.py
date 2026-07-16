#!/usr/bin/env python3
"""Positive and adversarial tests for the pinned Sound-DMA fixture gate."""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from verify_sound_dma_fixture import (
    BG_FIELDS,
    CAPTURE_CYCLES,
    CAPTURE_FRAMES,
    CPU_FIELDS,
    DEFAULT_COLOR_OPEN_IPL_FNV1A64,
    EXPECTED_EVENTS,
    EXPECTED_SDMA_ROWS,
    FONT_OFFSET,
    FONT_SIZE,
    FRAME_SIZE,
    MEM_FIELDS,
    MIN_TERMINAL_TAIL,
    PASS_FRAME_SHA256,
    PASS_TILE,
    RESULT_POSITIONS,
    ROM_NAME,
    TERMINAL_CS,
    TERMINAL_IP,
    TERMINAL_PC,
    expected_frame,
    fnv1a64,
    sha256,
    verify_frame,
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


def mem_row(cycle: int, index: int) -> dict[str, object]:
    expected = EXPECTED_SDMA_ROWS[index]
    row: dict[str, object] = {field: "" for field in FIELDS_V5}
    row.update(
        {
            "cycle": cycle,
            "event": "mem",
            "address": expected.address,
            "value": expected.value,
            "initiator": "sdma",
            "access": "read",
            "byte_enable": 3,
            "space": expected.space,
            "mapped_offset": expected.mapped_offset,
            "origin_status": "not_applicable",
        }
    )
    assert {field for field, value in row.items() if value != ""} == MEM_FIELDS
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
            "tile_bank_enabled": 1,
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
    rows.extend(mem_row(1000 + index, index) for index in range(346))
    cycle = 2000
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
        "open_ipl_size": 8192,
        "open_ipl_fnv1a64": DEFAULT_COLOR_OPEN_IPL_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": True,
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
        raise AssertionError(f"invalid Sound-DMA fixture passed; expected {expected!r}")


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    checked_fixture = repository / "testroms/ws-test-suite/sound_dma"
    verify_sources(checked_fixture)
    checked_rom = verify_rom(checked_fixture / ROM_NAME)
    frame = expected_frame(checked_rom)
    assert len(frame) == FRAME_SIZE
    assert sha256(frame) == PASS_FRAME_SHA256
    assert len(EXPECTED_SDMA_ROWS) == 346
    segment_zero = [
        row for row in EXPECTED_SDMA_ROWS if row.phase.startswith("source_")
    ]
    assert len(segment_zero) == 43
    assert all(row.space == "iram" and 0x59 <= row.address <= 0x68 for row in segment_zero)
    assert not any(row.space == "cart_sram" for row in EXPECTED_SDMA_ROWS)

    with tempfile.TemporaryDirectory(prefix="swansong-sound-dma-test-") as directory:
        root = Path(directory)
        fixture = root / "fixture"
        shutil.copytree(checked_fixture, fixture)
        rom = verify_rom(fixture / ROM_NAME)
        rows = valid_rows(rom)
        first_mem = 1 + MIN_TERMINAL_TAIL
        first_bg = first_mem + len(EXPECTED_SDMA_ROWS)

        trace_a = root / "a.csv"
        trace_b = root / "b.csv"
        write_trace(trace_a, rows, rom)
        write_trace(trace_b, rows, rom)
        final_a = root / "a-final.rgb"
        final_b = root / "b-final.rgb"
        final_a.write_bytes(frame)
        final_b.write_bytes(frame)
        counts = verify_pair(fixture, trace_a, final_a, trace_b, final_b)
        assert counts["sdma_rows"] == 346
        assert counts["source_labeled_sram_iram_rows"] == 43
        assert counts["actual_sram_rows"] == 0
        assert counts["pass_results"] == 22
        assert counts["pass_rows"] == 176

        bad_source = root / "bad-source"
        shutil.copytree(fixture, bad_source)
        with (bad_source / "main.c").open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(lambda: verify_sources(bad_source), "main.c SHA-256 mismatch")

        bad_footer = root / "bad-footer.wsc"
        changed = bytearray(rom)
        changed[-4] ^= 1
        bad_footer.write_bytes(changed)
        must_fail(lambda: verify_rom(bad_footer), "footer identity mismatch")

        bad_checksum = root / "bad-checksum.wsc"
        changed = bytearray(rom)
        changed[0x1E896] += 1
        bad_checksum.write_bytes(changed)
        must_fail(lambda: verify_rom(bad_checksum), "footer checksum mismatch")

        bad_identity = root / "bad-identity.wsc"
        changed = bytearray(rom)
        changed[0x1E896] += 1
        changed[0x1E898] -= 1
        bad_identity.write_bytes(changed)
        must_fail(lambda: verify_rom(bad_identity), "ROM SHA-256 mismatch")

        mutations = (
            (0, "address", int(rows[first_mem]["address"]) + 1, "address mismatch"),
            (0, "value", int(rows[first_mem]["value"]) ^ 1, "value mismatch"),
            (67, "space", "cart_sram", "space mismatch"),
            (
                67,
                "mapped_offset",
                int(rows[first_mem + 67]["mapped_offset"]) + 1,
                "mapped_offset mismatch",
            ),
            (0, "initiator", "cpu", "initiator mismatch"),
            (0, "access", "write", "access mismatch"),
            (0, "byte_enable", 1, "byte_enable mismatch"),
            (0, "origin_status", "exact", "origin_status mismatch"),
        )
        for number, (index, field, value, message) in enumerate(mutations):
            changed_rows = deepcopy(rows)
            changed_rows[first_mem + index][field] = value
            path = root / f"bad-sdma-{number}.csv"
            write_trace(path, changed_rows, rom)
            must_fail(lambda path=path: verify_trace(path, rom), message)

        missing_sdma = root / "missing-sdma.csv"
        missing_rows = deepcopy(rows)
        del missing_rows[first_mem + 10]
        write_trace(missing_sdma, missing_rows, rom)
        must_fail(lambda: verify_trace(missing_sdma, rom), "address mismatch")

        bad_terminal = root / "bad-terminal.csv"
        terminal_rows = deepcopy(rows)
        terminal_rows[MIN_TERMINAL_TAIL]["physical_pc"] = TERMINAL_PC + 1
        terminal_rows[MIN_TERMINAL_TAIL]["ip"] = TERMINAL_IP + 1
        write_trace(bad_terminal, terminal_rows, rom)
        must_fail(lambda: verify_trace(bad_terminal, rom), "left terminal loop")

        fail_result = root / "fail-result.csv"
        fail_rows = deepcopy(rows)
        fail_rows[first_bg]["tile_index"] = 6
        fail_rows[first_bg]["map_value"] = 6
        write_trace(fail_result, fail_rows, rom)
        must_fail(lambda: verify_trace(fail_result, rom), "contains FAIL tile")

        wrong_position = root / "wrong-position.csv"
        position_rows = deepcopy(rows)
        position_rows[first_bg]["map_x"] = 25
        write_trace(wrong_position, position_rows, rom)
        must_fail(lambda: verify_trace(wrong_position, rom), "unexpected (25, 0)")

        missing_pass = root / "missing-pass.csv"
        pass_rows = deepcopy(rows)
        del pass_rows[first_bg + 7]
        write_trace(missing_pass, pass_rows, rom)
        must_fail(lambda: verify_trace(missing_pass, rom), "only 7 PASS rows")

        reordered = root / "reordered-pass.csv"
        reordered_rows = deepcopy(rows)
        for field in ("tile_row", "tile_row_address", "tile_row_value"):
            reordered_rows[first_bg][field], reordered_rows[first_bg + 1][field] = (
                reordered_rows[first_bg + 1][field],
                reordered_rows[first_bg][field],
            )
        write_trace(reordered, reordered_rows, rom)
        must_fail(lambda: verify_trace(reordered, rom), "row sequence mismatch")

        bad_frame = root / "bad-frame.rgb"
        changed_frame = bytearray(frame)
        changed_frame[0] ^= 0xFF
        bad_frame.write_bytes(changed_frame)
        must_fail(lambda: verify_frame(bad_frame, rom), "22-PASS frame")

        stale = root / "stale.csv"
        write_trace(stale, rows, rom)
        with stale.open("a", encoding="utf-8") as output:
            output.write("\n")
        must_fail(lambda: verify_trace(stale, rom), "trace manifest mismatch")

        bad_manifest = root / "bad-manifest.csv"
        write_trace(bad_manifest, rows, rom)
        manifest_path = Path(f"{bad_manifest}.manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["memory_filters_active"] = False
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        must_fail(lambda: verify_trace(bad_manifest, rom), "trace manifest mismatch")

        different_trace = root / "different.csv"
        different_rows = deepcopy(rows)
        different_rows[0] = cpu_row(1, 0xFFFF3, 0xFFFF, 3)
        write_trace(different_trace, different_rows, rom)
        verify_trace(different_trace, rom)
        must_fail(
            lambda: verify_pair(
                fixture, trace_a, final_a, different_trace, final_b
            ),
            "not byte-identical",
        )

    print(
        "PASS pinned Sound-DMA verifier "
        "source/footer/checksum/346-sequence/provenance/segment-zero/"
        "terminal/22-results/frame/manifest/determinism mutations"
    )


if __name__ == "__main__":
    main()
