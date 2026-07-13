#!/usr/bin/env python3
"""Verify the pinned open V30MZ/80186 quirk ROM through final pixels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from verify_trace import FIELDS_V5


ROM_NAME = "80186_quirks.ws"
ROM_SIZE = 128 * 1024
ROM_SHA256 = "b44090665f0165c7e3279da13359a0b27c69e3127823d55b2bb16f3dd4a2eb1c"
ROM_FOOTER = bytes.fromhex("ea000027ff000000000000000401623a")
FONT_OFFSET = 0x1EE70
FONT_SIZE = 128 * 8
FONT_SHA256 = "55aded7d9763f138df6f13bd4057381243bc45cf8c009e79db982282e3e6294b"
SOURCE_SHA256 = {
    "main.c": "d5a9ca8bf553ceb64aa4c1a57011b8beae77cd6106025196709156f7499bda14",
    "tests.s": "afbcbf40ea45f6a1eaf552db068b5107343b270b31ee40e61ca1e0576f8784d5",
    "wfconfig.toml": "f82d4feb8d593407aad77ecffffc206861d6848c52b7495fb06400b6c419e088",
    "LICENSE.ws-test-suite": "266d82632cf7ed13f791b599ef6839d3c525f9f6eecfbe36e61dd1f01e77ca38",
    "LICENSE.target-wswan-syslibs": "8ee810c7d10a705880f7720051bff071cc801ce7feb4f462b1af43e4f0140661",
}

WIDTH = 224
HEIGHT = 144
FRAME_SIZE = WIDTH * HEIGHT * 3
BLANK_FRAME_SHA256 = "b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511"
PASS_FRAME_SHA256 = "871d7e2de2f915ceaae2a94fcf99b86825430f79588e43e640f9bfa8fed6dce0"
LABELS = (
    b"AAM, argument != 10:",
    b"AAD, argument != 10:",
    b"Opcode 0xD6 is SALC:",
)
PASS_TILE = 5
FAIL_TILE = 6
RESULT_X = 27
TERMINAL_PC = 0xFF686
TERMINAL_CS = 0xFF27
TERMINAL_IP = 0x0416
MIN_TERMINAL_TAIL = 128
CAPTURE_CYCLES = 930_689
DEFAULT_MONO_BIOS_FNV1A64 = "2c83c0c1976b8168"
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
        path = root / name
        digest = sha256(path.read_bytes())
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
        draw(PASS_TILE, RESULT_X, tile_y)
    result = bytes(frame)
    digest = sha256(result)
    if digest != PASS_FRAME_SHA256:
        raise ValueError(f"derived PASS frame identity mismatch: {digest}")
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
        "bios_size",
        "bios_fnv1a64",
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
    result_rows: dict[int, list[tuple[int, int, int]]] = {0: [], 1: [], 2: []}
    cpu_rows: list[tuple[int, int, int, int]] = []
    previous_cycle = -1

    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(f"80186 fixture requires exact v5 header: {reader.fieldnames!r}")
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
            if map_x != RESULT_X or map_y not in result_rows:
                continue
            if row["bg_layer"] != "1":
                raise ValueError(f"line {line}: result marker is not on Screen 1")
            tile_index = integer(row["tile_index"], "tile_index", line, 0x1FF)
            if tile_index == FAIL_TILE:
                raise ValueError(f"line {line}: result {map_y} contains the FAIL tile")
            if tile_index != PASS_TILE or integer(row["map_value"], "map_value", line, 0xFFFF) != PASS_TILE:
                raise ValueError(f"line {line}: result {map_y} does not contain the PASS tile")
            tile_row = integer(row["tile_row"], "tile_row", line, 7)
            expected = {
                "map_address": 0x1800 + map_y * 64 + RESULT_X * 2,
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
                        f"line {line}: result {map_y} {field} mismatch: "
                        f"{row[field]} != {wanted}"
                    )
            result_rows[map_y].append((tile_row, cycle, expected_pass_rows[tile_row]))

    if len(cpu_rows) < MIN_TERMINAL_TAIL:
        raise ValueError(f"CPU trace has only {len(cpu_rows)} rows")
    terminal = (TERMINAL_PC, TERMINAL_CS, TERMINAL_IP)
    if any((pc, cs, ip) != terminal for _, pc, cs, ip in cpu_rows[-MIN_TERMINAL_TAIL:]):
        raise ValueError(
            f"last {MIN_TERMINAL_TAIL} CPU rows do not remain at terminal PC {TERMINAL_PC:#07x}"
        )
    first_terminal_cycle = next(
        (cycle for cycle, pc, cs, ip in cpu_rows if (pc, cs, ip) == terminal), None
    )
    if first_terminal_cycle is None:
        raise ValueError(f"terminal PC {TERMINAL_PC:#07x} was never reached")
    for result, rows in result_rows.items():
        observed = tuple(row for row, _, _ in rows)
        if observed != tuple(range(8)):
            raise ValueError(f"result {result} PASS row sequence mismatch: {observed!r}")
        if rows[0][1] <= first_terminal_cycle:
            raise ValueError(f"result {result} was promoted before the terminal loop")
    return {
        "cpu_rows": len(cpu_rows),
        "terminal_tail": MIN_TERMINAL_TAIL,
        "pass_results": len(result_rows),
        "pass_rows": sum(len(rows) for rows in result_rows.values()),
    }


def verify_frames(blank_path: Path, final_path: Path, rom: bytes) -> None:
    blank = blank_path.read_bytes()
    if len(blank) != FRAME_SIZE or sha256(blank) != BLANK_FRAME_SHA256:
        raise ValueError(f"first frame identity mismatch: size={len(blank)} sha256={sha256(blank)}")
    final = final_path.read_bytes()
    expected = expected_frame(rom)
    if len(final) != FRAME_SIZE or final != expected or sha256(final) != PASS_FRAME_SHA256:
        raise ValueError(f"final three-PASS frame identity mismatch: size={len(final)} sha256={sha256(final)}")


def verify_pair(
    fixture: Path,
    trace_a: Path,
    frame0_a: Path,
    frame1_a: Path,
    trace_b: Path,
    frame0_b: Path,
    frame1_b: Path,
) -> dict[str, int]:
    verify_sources(fixture)
    rom = verify_rom(fixture / ROM_NAME)
    counts_a = verify_trace(trace_a, rom)
    counts_b = verify_trace(trace_b, rom)
    verify_frames(frame0_a, frame1_a, rom)
    verify_frames(frame0_b, frame1_b, rom)
    if trace_a.read_bytes() != trace_b.read_bytes() or counts_a != counts_b:
        raise ValueError("paired CPU/background traces are not byte-identical")
    if frame0_a.read_bytes() != frame0_b.read_bytes() or frame1_a.read_bytes() != frame1_b.read_bytes():
        raise ValueError("paired framebuffer outputs are not byte-identical")
    return counts_a


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--trace-a", required=True, type=Path)
    parser.add_argument("--frame0-a", required=True, type=Path)
    parser.add_argument("--frame1-a", required=True, type=Path)
    parser.add_argument("--trace-b", required=True, type=Path)
    parser.add_argument("--frame0-b", required=True, type=Path)
    parser.add_argument("--frame1-b", required=True, type=Path)
    args = parser.parse_args()
    try:
        counts = verify_pair(
            args.fixture,
            args.trace_a,
            args.frame0_a,
            args.frame1_a,
            args.trace_b,
            args.frame0_b,
            args.frame1_b,
        )
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"80186 quirk fixture: {error}") from error
    print(
        "PASS pinned 80186 quirks "
        + " ".join(f"{name}={value}" for name, value in counts.items())
        + f" terminal_pc={TERMINAL_PC:#07x} frame_sha256={PASS_FRAME_SHA256} paired=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
