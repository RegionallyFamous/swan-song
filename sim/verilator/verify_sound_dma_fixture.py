#!/usr/bin/env python3
"""Verify the pinned open WSC Sound-DMA fixture through bus reads and pixels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from verify_trace import FIELDS_V5


ROM_NAME = "sound_dma.wsc"
ROM_SIZE = 128 * 1024
ROM_SHA256 = "89b57284c70d24837b686153cff99b6e4332d3682f001bc6209d0da3a4c1333f"
ROM_FOOTER = bytes.fromhex("ea0000d9fe000001000000010401cb7b")
FONT_OFFSET = 0x1E990
FONT_SIZE = 128 * 8
FONT_SHA256 = "55aded7d9763f138df6f13bd4057381243bc45cf8c009e79db982282e3e6294b"
SOURCE_SHA256 = {
    "main.c": "aed792acdf685e09668d324a857e344039b1f54ddc7fd33bb1a3f493187955a5",
    "wfconfig.toml": "ccf7a81c479c07d617f15ba58c3d2c5b3a1a35f794ebb39501e35a955f1197b3",
    "LICENSE.ws-test-suite": "266d82632cf7ed13f791b599ef6839d3c525f9f6eecfbe36e61dd1f01e77ca38",
    "LICENSE.target-wswan-syslibs": "8ee810c7d10a705880f7720051bff071cc801ce7feb4f462b1af43e4f0140661",
}

WIDTH = 224
HEIGHT = 144
FRAME_SIZE = WIDTH * HEIGHT * 3
PASS_FRAME_SHA256 = "b4166e27c8d6c686b854e4bddb9816e967c9a406afe2886d128abf1059ca927a"
LABELS = (
    b"SDMA source 20-bit:",
    b"SDMA length 20-bit:",
    b"SDMA<-slow ROM OK:",
    b"SDMA<-fast ROM OK:",
    b"SDMA<-IRAM OK:",
    b"SDMA<-slow SRAM OK:",
    b"SDMA<-fast SRAM OK:",
    b"SDMA hold OK:",
    b"SDMA finish zeroes:",
    b"SDMA overflow wraps:",
    b"Ends on last byte:",
)
RESULT_POSITIONS = (
    (26, 0),
    (27, 0),
    (26, 1),
    (27, 1),
    (27, 2),
    (27, 3),
    (27, 4),
    (27, 5),
    (27, 6),
    *((column, 7) for column in range(23, 28)),
    *((column, 8) for column in range(23, 28)),
    (26, 9),
    (27, 9),
    (27, 10),
)
PASS_TILE = 5
FAIL_TILE = 6
BLANK_TILE = 32
TERMINAL_PC = 0xFF63A
TERMINAL_CS = 0xFED9
TERMINAL_IP = 0x08AA
MIN_TERMINAL_TAIL = 128
CAPTURE_CYCLES = 7_280_513
CAPTURE_FRAMES = 15
DEFAULT_COLOR_BIOS_FNV1A64 = "bde71f09ac34c168"
EXPECTED_EVENTS = {
    "cpu": True,
    "bank": False,
    "vram": False,
    "mem": True,
    "bg_cell": True,
}

CPU_FIELDS = {"cycle", "event", "physical_pc", "cs", "ip"}
MEM_FIELDS = {
    "cycle",
    "event",
    "address",
    "value",
    "initiator",
    "access",
    "byte_enable",
    "space",
    "mapped_offset",
    "origin_status",
}
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


@dataclass(frozen=True)
class ExpectedSdma:
    phase: str
    address: int
    value: int
    space: str
    mapped_offset: int


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


def _bus_value(memory: dict[int, int], address: int) -> int:
    low = memory.get(address, 0)
    if address & 1:
        return low
    return low | (memory.get(address + 1, 0) << 8)


def _build_expected_sdma() -> tuple[ExpectedSdma, ...]:
    """Build the complete functional read contract, without pinning cycle timing."""

    rows: list[ExpectedSdma] = []

    def add(
        phase: str,
        addresses: Iterable[int],
        space: str,
        offset: Callable[[int], int],
        value: Callable[[int], int],
    ) -> None:
        rows.extend(
            ExpectedSdma(phase, address, value(address), space, offset(address))
            for address in addresses
        )

    sample_rom = {address: 0x55 for address in range(0xFE89E, 0xFE8AE)}
    sample_iram_before_sram_copy = {
        address: 0x55 for address in range(0x49, 0x59)
    }
    sample_and_segment_zero_sram = {
        address: 0x55 for address in range(0x49, 0x69)
    }

    add(
        "slow_rom",
        (*range(0xFE89E, 0xFE8AE), *range(0xFE89E, 0xFE8A4)),
        "cart_rom_linear",
        lambda address: address - 0xE0000,
        lambda address: _bus_value(sample_rom, address),
    )
    add(
        "fast_rom",
        (*range(0xFE89E, 0xFE8AE), *range(0xFE89E, 0xFE8A3)),
        "cart_rom_linear",
        lambda address: address - 0xE0000,
        lambda address: _bus_value(sample_rom, address),
    )
    add(
        "iram",
        (*range(0x49, 0x59), *range(0x49, 0x51)),
        "iram",
        lambda address: address,
        lambda address: _bus_value(sample_iram_before_sram_copy, address),
    )

    # The pinned Wonderful image places the source's .sram symbol in segment
    # zero. These two source-labeled SRAM phases therefore access IRAM, not
    # cartridge SRAM. Keep that toolchain limitation visible in phase names.
    add(
        "source_slow_sram_segment_zero_iram",
        (*range(0x59, 0x69), *range(0x59, 0x60)),
        "iram",
        lambda address: address,
        lambda address: _bus_value(sample_and_segment_zero_sram, address),
    )
    add(
        "source_fast_sram_segment_zero_iram",
        (*range(0x59, 0x69), *range(0x59, 0x5D)),
        "iram",
        lambda address: address,
        lambda address: _bus_value(sample_and_segment_zero_sram, address),
    )
    add(
        "hold",
        (
            *range(0x49, 0x59),
            0x49,
            *(0x4A for _ in range(29)),
            *range(0x4B, 0x59),
            *range(0x49, 0x4C),
        ),
        "iram",
        lambda address: address,
        lambda address: _bus_value(sample_and_segment_zero_sram, address),
    )
    add(
        "large_hold",
        (
            *range(0x20000, 0x20029),
            *(0x20028 for _ in range(33)),
            *range(0x20029, 0x20049),
            *(0x20048 for _ in range(35)),
        ),
        "cart_rom0",
        lambda address: address - 0x10000,
        lambda address: 0xFF if address & 1 else 0xFFFF,
    )
    add(
        "finish_zeroes",
        range(0x1234, 0x1244),
        "iram",
        lambda address: address,
        lambda address: 0,
    )
    overflow_memory = {0x0D: 0xFF, 0x0E: 0xAA, 0x0F: 0x55}
    add(
        "overflow_wrap",
        (0xFFFFF,),
        "cart_rom_linear",
        lambda _address: 0x1FFFF,
        lambda _address: 0x7B,
    )
    add(
        "overflow_wrap",
        range(0x00, 0x0F),
        "iram",
        lambda address: address,
        lambda address: _bus_value(overflow_memory, address),
    )

    if len(rows) != 346:
        raise AssertionError(f"internal Sound-DMA contract has {len(rows)} rows")
    return tuple(rows)


EXPECTED_SDMA_ROWS = _build_expected_sdma()


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
    for tile_x, tile_y in RESULT_POSITIONS:
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
        "completed_frames": CAPTURE_FRAMES,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "bios_size": 8192,
        "bios_fnv1a64": DEFAULT_COLOR_BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": True,
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


def _verify_sdma_row(row: dict[str, str], expected: ExpectedSdma, line: int) -> None:
    populated = {field for field in FIELDS_V5 if row[field]}
    if populated != MEM_FIELDS:
        raise ValueError(f"line {line}: SDMA field set mismatch: {sorted(populated)!r}")
    strings = {
        "initiator": "sdma",
        "access": "read",
        "space": expected.space,
        "origin_status": "not_applicable",
    }
    for field, wanted in strings.items():
        if row[field] != wanted:
            raise ValueError(
                f"line {line}: SDMA {expected.phase} {field} mismatch: "
                f"{row[field]!r} != {wanted!r}"
            )
    numbers = {
        "address": (expected.address, 0xFFFFF),
        "value": (expected.value, 0xFFFF),
        "byte_enable": (3, 3),
        "mapped_offset": (expected.mapped_offset, 0xFFFFFF),
    }
    for field, (wanted, maximum) in numbers.items():
        observed = integer(row[field], field, line, maximum)
        if observed != wanted:
            raise ValueError(
                f"line {line}: SDMA {expected.phase} {field} mismatch: "
                f"{observed:#x} != {wanted:#x}"
            )


def verify_trace(path: Path, rom: bytes) -> dict[str, int]:
    verify_manifest(path, rom)
    font = rom[FONT_OFFSET : FONT_OFFSET + FONT_SIZE]
    expected_pass_rows = tuple(font[PASS_TILE * 8 : PASS_TILE * 8 + 8])
    pass_rows: dict[tuple[int, int], list[tuple[int, int]]] = {
        position: [] for position in RESULT_POSITIONS
    }
    cpu_rows: list[tuple[int, int, int, int]] = []
    sdma_index = 0
    previous_cycle = -1

    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(
                f"Sound-DMA fixture requires exact v5 header: {reader.fieldnames!r}"
            )
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
                    raise ValueError(
                        f"line {line}: CPU CS:IP does not resolve to physical PC"
                    )
                cpu_rows.append((cycle, pc, cs, ip))
                continue
            if event == "mem":
                if sdma_index >= len(EXPECTED_SDMA_ROWS):
                    raise ValueError(f"line {line}: unexpected extra SDMA row")
                _verify_sdma_row(row, EXPECTED_SDMA_ROWS[sdma_index], line)
                sdma_index += 1
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
            tile_index = integer(row["tile_index"], "tile_index", line, 0x1FF)
            map_value = integer(row["map_value"], "map_value", line, 0xFFFF)
            if position not in pass_rows:
                if tile_index in (PASS_TILE, FAIL_TILE) or map_value in (
                    PASS_TILE,
                    FAIL_TILE,
                ):
                    raise ValueError(
                        f"line {line}: diagnostic tile appears at unexpected {position}"
                    )
                continue
            if tile_index == FAIL_TILE or map_value == FAIL_TILE:
                raise ValueError(f"line {line}: result marker {position} contains FAIL tile")
            if tile_index == BLANK_TILE and map_value == BLANK_TILE:
                continue
            if tile_index != PASS_TILE or map_value != PASS_TILE:
                raise ValueError(
                    f"line {line}: result marker {position} has unexpected tile "
                    f"index/value {tile_index}/{map_value}"
                )
            if row["bg_layer"] != "1":
                raise ValueError(f"line {line}: result marker is not on Screen 1")
            tile_row = integer(row["tile_row"], "tile_row", line, 7)
            expected_fields = {
                "map_address": 0x1800 + map_y * 64 + map_x * 2,
                "tile_bank_enabled": 1,
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
            for field, wanted in expected_fields.items():
                if integer(row[field], field, line, 0xFFFF) != wanted:
                    raise ValueError(
                        f"line {line}: result marker {position} {field} mismatch: "
                        f"{row[field]} != {wanted}"
                    )
            pass_rows[position].append((tile_row, cycle))

    if sdma_index != len(EXPECTED_SDMA_ROWS):
        raise ValueError(
            f"Sound-DMA row count mismatch: {sdma_index} != {len(EXPECTED_SDMA_ROWS)}"
        )
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

    segment_zero_rows = sum(
        row.phase.startswith("source_") for row in EXPECTED_SDMA_ROWS
    )
    return {
        "sdma_rows": sdma_index,
        "source_labeled_sram_iram_rows": segment_zero_rows,
        "actual_sram_rows": 0,
        "pass_results": len(pass_rows),
        "pass_rows": len(pass_rows) * 8,
        "terminal_tail": len(terminal_rows),
    }


def verify_frame(path: Path, rom: bytes) -> None:
    frame = path.read_bytes()
    expected = expected_frame(rom)
    if len(frame) != FRAME_SIZE or frame != expected or sha256(frame) != PASS_FRAME_SHA256:
        raise ValueError(
            f"final 22-PASS frame identity mismatch: "
            f"size={len(frame)} sha256={sha256(frame)}"
        )


def verify_pair(
    fixture: Path,
    trace_a: Path,
    final_a: Path,
    trace_b: Path,
    final_b: Path,
) -> dict[str, int]:
    verify_sources(fixture)
    rom = verify_rom(fixture / ROM_NAME)
    counts_a = verify_trace(trace_a, rom)
    counts_b = verify_trace(trace_b, rom)
    verify_frame(final_a, rom)
    verify_frame(final_b, rom)
    if trace_a.read_bytes() != trace_b.read_bytes() or counts_a != counts_b:
        raise ValueError("paired CPU/SDMA/background traces are not byte-identical")
    if final_a.read_bytes() != final_b.read_bytes():
        raise ValueError("paired final framebuffers are not byte-identical")
    return counts_a


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--trace-a", required=True, type=Path)
    parser.add_argument("--final-a", required=True, type=Path)
    parser.add_argument("--trace-b", required=True, type=Path)
    parser.add_argument("--final-b", required=True, type=Path)
    args = parser.parse_args()
    try:
        counts = verify_pair(
            args.fixture,
            args.trace_a,
            args.final_a,
            args.trace_b,
            args.final_b,
        )
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"Sound-DMA fixture: {error}") from error
    print(
        "PASS pinned Sound-DMA fixture "
        + " ".join(f"{name}={value}" for name, value in counts.items())
        + f" terminal_pc={TERMINAL_PC:#07x} frame_sha256={PASS_FRAME_SHA256} paired=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
