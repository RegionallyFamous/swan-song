#!/usr/bin/env python3
"""Verify the pinned open mono SoC interrupt fixture through final pixels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from verify_trace import FIELDS_V5


ROM_NAME = "interrupts.ws"
ROM_SIZE = 128 * 1024
ROM_SHA256 = "d8a4da6d6c33ad3f58e9bb9b105135788f832544db1b85f8f0e66e227d847da0"
ROM_FOOTER = bytes.fromhex("ea000018ff00000000000000040100f9")
FONT_OFFSET = 0x1ED80
FONT_SIZE = 128 * 8
FONT_SHA256 = "55aded7d9763f138df6f13bd4057381243bc45cf8c009e79db982282e3e6294b"
SOURCE_SHA256 = {
    "main.c": "4d30892baac71cbcba96f858ae76db4c5cba8768030416f551ee89328707bbce",
    "wfconfig.toml": "f82d4feb8d593407aad77ecffffc206861d6848c52b7495fb06400b6c419e088",
    "LICENSE.ws-test-suite": "266d82632cf7ed13f791b599ef6839d3c525f9f6eecfbe36e61dd1f01e77ca38",
    "LICENSE.target-wswan-syslibs": "8ee810c7d10a705880f7720051bff071cc801ce7feb4f462b1af43e4f0140661",
}

WIDTH = 224
HEIGHT = 144
FRAME_SIZE = WIDTH * HEIGHT * 3
BLANK_FRAME_SHA256 = "b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511"
PASS_FRAME_SHA256 = "7b300c12e228c9b2fb6ed7fbae7999f223aca316e2f920f0ee0c7519e182f5df"
LABELS = (b"IRQ 0 (UART TX):", b"Status affects vector:")
RESULT_COLUMNS = (tuple(range(20, 28)), tuple(range(23, 28)))
RESULT_POSITIONS = tuple(
    (column, row)
    for row, columns in enumerate(RESULT_COLUMNS)
    for column in columns
)
PASS_TILE = 5
FAIL_TILE = 6
BLANK_TILE = 32
TERMINAL_PC = 0xFF684
TERMINAL_CS = 0xFF18
TERMINAL_IP = 0x0504
MIN_TERMINAL_TAIL = 128
# Six default-timing framebuffer publications from reset release. This leaves
# two complete stable rasters after the fixture reaches its terminal loop.
CAPTURE_CYCLES = 2_887_553
CAPTURE_FRAMES = 6
DEFAULT_MONO_OPEN_IPL_FNV1A64 = "bcae6dfa69fd72ab"
EXPECTED_EVENTS = {
    "cpu": True,
    "bank": False,
    "vram": False,
    "mem": False,
    "bg_cell": True,
}

CPU_FIELDS = {"cycle", "event", "physical_pc", "cs", "ip"}
BG_FIELDS = {
    "cycle",
    "event",
    "bg_layer",
    "map_address",
    "map_value",
    "map_x",
    "map_y",
    "tile_bank_enabled",
    "tile_index",
    "palette",
    "hflip",
    "vflip",
    "bpp",
    "packed",
    "tile_row",
    "tile_row_address",
    "tile_row_bytes",
    "tile_row_value",
    "map_collision",
    "tile_row_collision",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def integer(value: str, field: str, line: int, maximum: int) -> int:
    if not value or not value.isdecimal():
        raise ValueError(f"line {line}: {field} is not decimal: {value!r}")
    result = int(value, 10)
    if result > maximum:
        raise ValueError(f"line {line}: {field} exceeds {maximum}: {result}")
    return result


def verify_sources(root: Path) -> None:
    for name, expected in SOURCE_SHA256.items():
        digest = sha256((root / name).read_bytes())
        if digest != expected:
            raise ValueError(f"pinned source/license {name} SHA-256 mismatch: {digest}")


def verify_rom(path: Path) -> bytes:
    rom = path.read_bytes()
    if len(rom) != ROM_SIZE:
        raise ValueError(f"ROM size mismatch: {len(rom)} != {ROM_SIZE}")
    if rom[-len(ROM_FOOTER) :] != ROM_FOOTER:
        raise ValueError("ROM reset-vector/header footer identity mismatch")
    checksum = int.from_bytes(rom[-2:], "little")
    expected_checksum = sum(rom[:-2]) & 0xFFFF
    if checksum != expected_checksum:
        raise ValueError(
            f"ROM footer checksum mismatch: {checksum:#06x} != {expected_checksum:#06x}"
        )
    digest = sha256(rom)
    if digest != ROM_SHA256:
        raise ValueError(f"ROM SHA-256 mismatch: {digest}")
    font = rom[FONT_OFFSET : FONT_OFFSET + FONT_SIZE]
    if len(font) != FONT_SIZE or sha256(font) != FONT_SHA256:
        raise ValueError("ROM embedded font identity mismatch")
    return rom


def expected_frame(rom: bytes) -> bytes:
    """Derive the all-PASS raster from the bound font and upstream source layout."""

    font = rom[FONT_OFFSET : FONT_OFFSET + FONT_SIZE]
    frame = bytearray(b"\xff" * FRAME_SIZE)

    def draw(tile: int, tile_x: int, tile_y: int) -> None:
        for row, bits in enumerate(font[tile * 8 : tile * 8 + 8]):
            for column in range(8):
                if bits & (0x80 >> column):
                    pixel = ((tile_y * 8 + row) * WIDTH + tile_x * 8 + column) * 3
                    frame[pixel : pixel + 3] = b"\x00\x00\x00"

    for tile_y, label in enumerate(LABELS):
        for tile_x, character in enumerate(label):
            draw(character, tile_x, tile_y)
    for tile_y, columns in enumerate(RESULT_COLUMNS):
        for tile_x in columns:
            draw(PASS_TILE, tile_x, tile_y)
    result = bytes(frame)
    digest = sha256(result)
    if digest != PASS_FRAME_SHA256:
        raise ValueError(f"derived all-PASS frame identity mismatch: {digest}")
    return result


def verify_manifest(trace: Path, rom: bytes) -> None:
    manifest_path = Path(f"{trace}.manifest.json")
    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {manifest_path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"trace manifest {manifest_path} is not an object")

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
        "open_ipl_size",
        "open_ipl_fnv1a64",
        "iram_initial_state",
        "savestate_inputs_asserted",
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
        "completed_frames": CAPTURE_FRAMES,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "open_ipl_size": 4096,
        "open_ipl_fnv1a64": DEFAULT_MONO_OPEN_IPL_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": True,
    }
    mismatches = [
        f"{field}={manifest.get(field)!r} (expected {wanted!r})"
        for field, wanted in expected.items()
        if manifest.get(field) != wanted
    ]
    if mismatches:
        raise ValueError("trace manifest mismatch: " + "; ".join(mismatches))


def verify_trace(path: Path, rom: bytes) -> dict[str, int]:
    verify_manifest(path, rom)
    font = rom[FONT_OFFSET : FONT_OFFSET + FONT_SIZE]
    expected_pass_rows = tuple(font[PASS_TILE * 8 : PASS_TILE * 8 + 8])
    pass_rows: dict[tuple[int, int], list[tuple[int, int]]] = {
        position: [] for position in RESULT_POSITIONS
    }
    cpu_rows: list[tuple[int, int, int, int]] = []
    previous_cycle = -1

    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(f"interrupt fixture requires exact v5 header: {reader.fieldnames!r}")
        for line, row in enumerate(reader, start=2):
            cycle = integer(row["cycle"], "cycle", line, (1 << 64) - 1)
            if cycle < previous_cycle:
                raise ValueError(f"line {line}: trace cycle order regressed")
            previous_cycle = cycle
            event = row["event"]
            if event == "cpu":
                populated = {field for field in FIELDS_V5 if row[field]}
                if populated != CPU_FIELDS:
                    raise ValueError(
                        f"line {line}: CPU field set mismatch: {sorted(populated)!r}"
                    )
                pc = integer(row["physical_pc"], "physical_pc", line, 0xFFFFF)
                cs = integer(row["cs"], "cs", line, 0xFFFF)
                ip = integer(row["ip"], "ip", line, 0xFFFF)
                if pc != ((cs << 4) + ip) & 0xFFFFF:
                    raise ValueError(f"line {line}: CPU CS:IP does not resolve to physical PC")
                cpu_rows.append((cycle, pc, cs, ip))
                continue
            if event != "bg_cell":
                raise ValueError(f"line {line}: unexpected event {event!r}")
            populated = {field for field in FIELDS_V5 if row[field]}
            if populated != BG_FIELDS:
                raise ValueError(
                    f"line {line}: bg_cell field set mismatch: {sorted(populated)!r}"
                )
            map_x = integer(row["map_x"], "map_x", line, 31)
            map_y = integer(row["map_y"], "map_y", line, 31)
            position = (map_x, map_y)
            if position not in pass_rows:
                continue
            tile_index = integer(row["tile_index"], "tile_index", line, 0x1FF)
            map_value = integer(row["map_value"], "map_value", line, 0xFFFF)
            if tile_index == FAIL_TILE or map_value == FAIL_TILE:
                raise ValueError(
                    f"line {line}: result marker ({map_x},{map_y}) contains the FAIL tile"
                )
            # init_pass_fail() fills the screen with ASCII space before the
            # individual assertions execute. It is not evidence either way.
            if tile_index == BLANK_TILE and map_value == BLANK_TILE:
                continue
            if tile_index != PASS_TILE or map_value != PASS_TILE:
                raise ValueError(
                    f"line {line}: result marker ({map_x},{map_y}) has unexpected tile "
                    f"index/value {tile_index}/{map_value}"
                )
            if row["bg_layer"] != "1":
                raise ValueError(f"line {line}: result marker is not on Screen 1")
            tile_row = integer(row["tile_row"], "tile_row", line, 7)
            expected = {
                "map_address": 0x1800 + map_y * 64 + map_x * 2,
                "tile_bank_enabled": 0,
                "palette": 0,
                "hflip": 0,
                "vflip": 0,
                "bpp": 2,
                "packed": 0,
                "tile_row_address": 0x2000 + PASS_TILE * 16 + tile_row * 2,
                "tile_row_bytes": 2,
                "tile_row_value": expected_pass_rows[tile_row],
                "map_collision": 0,
                "tile_row_collision": 0,
            }
            for field, wanted in expected.items():
                if integer(row[field], field, line, 0xFFFF) != wanted:
                    raise ValueError(
                        f"line {line}: result marker ({map_x},{map_y}) {field} "
                        f"mismatch: {row[field]} != {wanted}"
                    )
            pass_rows[position].append((tile_row, cycle))

    if len(cpu_rows) < MIN_TERMINAL_TAIL:
        raise ValueError(f"CPU trace has only {len(cpu_rows)} rows")
    terminal = (TERMINAL_PC, TERMINAL_CS, TERMINAL_IP)
    first_terminal_index = next(
        (
            index
            for index, (_, pc, cs, ip) in enumerate(cpu_rows)
            if (pc, cs, ip) == terminal
        ),
        None,
    )
    if first_terminal_index is None:
        raise ValueError(f"terminal PC {TERMINAL_PC:#07x} was never reached")
    terminal_rows = cpu_rows[first_terminal_index:]
    if any((pc, cs, ip) != terminal for _, pc, cs, ip in terminal_rows):
        raise ValueError(f"CPU left terminal loop at PC {TERMINAL_PC:#07x}")
    if len(terminal_rows) < MIN_TERMINAL_TAIL:
        raise ValueError(
            f"terminal loop has only {len(terminal_rows)} rows; "
            f"expected at least {MIN_TERMINAL_TAIL}"
        )
    first_terminal_cycle = terminal_rows[0][0]

    for position, rows in pass_rows.items():
        if len(rows) < 8:
            raise ValueError(f"result marker {position} has only {len(rows)} PASS rows")
        final = rows[-8:]
        observed = tuple(tile_row for tile_row, _ in final)
        if observed != tuple(range(8)):
            raise ValueError(
                f"result marker {position} final PASS row sequence mismatch: {observed!r}"
            )
        if final[0][1] <= first_terminal_cycle:
            raise ValueError(
                f"result marker {position} has no complete post-terminal PASS raster"
            )
    return {
        "cpu_rows": len(cpu_rows),
        "terminal_tail": MIN_TERMINAL_TAIL,
        "pass_results": len(pass_rows),
        "pass_rows": len(pass_rows) * 8,
    }


def verify_frames(blank_path: Path, final_path: Path, rom: bytes) -> None:
    blank = blank_path.read_bytes()
    if len(blank) != FRAME_SIZE or sha256(blank) != BLANK_FRAME_SHA256:
        raise ValueError(
            f"first frame identity mismatch: size={len(blank)} sha256={sha256(blank)}"
        )
    final = final_path.read_bytes()
    expected = expected_frame(rom)
    if len(final) != FRAME_SIZE or final != expected or sha256(final) != PASS_FRAME_SHA256:
        raise ValueError(
            f"final thirteen-PASS frame identity mismatch: "
            f"size={len(final)} sha256={sha256(final)}"
        )


def verify_pair(
    fixture: Path,
    trace_a: Path,
    frame0_a: Path,
    final_a: Path,
    trace_b: Path,
    frame0_b: Path,
    final_b: Path,
) -> dict[str, int]:
    verify_sources(fixture)
    rom = verify_rom(fixture / ROM_NAME)
    counts_a = verify_trace(trace_a, rom)
    counts_b = verify_trace(trace_b, rom)
    verify_frames(frame0_a, final_a, rom)
    verify_frames(frame0_b, final_b, rom)
    if trace_a.read_bytes() != trace_b.read_bytes() or counts_a != counts_b:
        raise ValueError("paired CPU/background traces are not byte-identical")
    if frame0_a.read_bytes() != frame0_b.read_bytes() or final_a.read_bytes() != final_b.read_bytes():
        raise ValueError("paired framebuffer outputs are not byte-identical")
    return counts_a


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--trace-a", required=True, type=Path)
    parser.add_argument("--frame0-a", required=True, type=Path)
    parser.add_argument("--final-a", required=True, type=Path)
    parser.add_argument("--trace-b", required=True, type=Path)
    parser.add_argument("--frame0-b", required=True, type=Path)
    parser.add_argument("--final-b", required=True, type=Path)
    args = parser.parse_args()
    try:
        counts = verify_pair(
            args.fixture,
            args.trace_a,
            args.frame0_a,
            args.final_a,
            args.trace_b,
            args.frame0_b,
            args.final_b,
        )
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"interrupt fixture: {error}") from error
    print(
        "PASS pinned SoC interrupts "
        + " ".join(f"{name}={value}" for name, value in counts.items())
        + f" terminal_pc={TERMINAL_PC:#07x} frame_sha256={PASS_FRAME_SHA256} paired=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
