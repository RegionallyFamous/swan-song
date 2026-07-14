#!/usr/bin/env python3
"""Verify the Color sprite-priority probe from bound ROM/trace to stable RGB."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from verify_trace import FIELDS_V6


ROM_NAME = "wsc_color_sprite_priority_probe.wsc"
ROM_SIZE = 128 * 1024
ROM_SHA256 = "dd2493e9f936ce30df72bcee70f2e705bb92bc10bcfb749b96da6251aa03e450"
ROM_FNV1A64 = "c7f84165a79985a9"
MARKER = b"SWANSONG-WSC-COLOR-SPRITE-PRIORITY-V1\0"
MARKER_OFFSET = 0x10400
PAYLOAD_OFFSET = 0x10200
PAYLOAD_ADDRESS = 0x4000

WIDTH = 224
HEIGHT = 144
FRAME_SIZE = WIDTH * HEIGHT * 3
GREEN = bytes((0, 255, 0))
BLUE = bytes((0, 0, 255))
RED = bytes((255, 0, 0))
BLACK = bytes((0, 0, 0))
STABLE_FRAME_SHA256 = "eb515b9c58a3fc7f386520937818d95b846a94cd43a86edef1daf54f3a4b5ef4"

# Filled from the first reviewed fixed-RTL capture.  They deliberately live in
# this independent verifier instead of the generator or the manifest.
TRACE_SIZE = 9_697_018
TRACE_FNV1A64 = "edd172d8cb8c5c46"
TRACE_SHA256 = "0bbbca0ce10d33b8da44955a62cfa7e33edd5bc73fab29fbb40ce990aca7115f"
CAPTURE_CYCLES = 933761
BIOS_FNV1A64 = "ef7d73ef979bfc94"
EXPECTED_EVENTS = {
    "cpu": False,
    "bank": False,
    "vram": True,
    "mem": True,
    "bg_cell": False,
    "sprite_row": True,
}
EXPECTED_SPRITE_ROWS = tuple(
    (line_y, slot) for line_y in range(64, 72) for slot in range(6)
)

TABLE_GROUP = (
    (0x1000, 0x0001),
    (0x1002, 0x4040),
    (0x1004, 0x2202),
    (0x1006, 0x6040),
    (0x1008, 0x0001),
    (0x100A, 0x7040),
    (0x100C, 0x2202),
    (0x100E, 0x7040),
    (0x1010, 0x0001),
    (0x1012, 0x5040),
    (0x1014, 0x2202),
    (0x1016, 0x5040),
)
CPU_FINAL_WORDS = dict(TABLE_GROUP) | {
    0x0210: 0x0003,
    0x0214: 0x0003,
    0x0218: 0x0003,
    0xFE02: 0x000F,
    0xFF04: 0x0F00,
    0xFF26: 0x00F0,
}
PAYLOAD = (
    bytes((0x00,)) * 32
    + bytes((0x22,)) * 32
    + bytes((0x33,)) * 32
    + bytes((0x11,)) * 32
)


@dataclass(frozen=True)
class VramFetch:
    cycle: int
    role: str
    address: int
    value: int
    collision: int


@dataclass
class TraceEvidence:
    vram: list[VramFetch]
    mem: list[tuple[int, dict[str, str]]]
    sprite_rows: list[tuple[int, int]]
    last_cycle: int


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def decimal(row: dict[str, str], field: str, context: str) -> int:
    value = row.get(field, "")
    if not value:
        raise ValueError(f"{context}: empty {field}")
    try:
        return int(value, 10)
    except ValueError as error:
        raise ValueError(f"{context}: invalid {field}: {value!r}") from error


def verify_sprite_row_sequence(rows: list[tuple[int, int]]) -> int:
    if tuple(rows) != EXPECTED_SPRITE_ROWS:
        raise ValueError(
            "exact sprite-row line/slot sequence mismatch: "
            f"{rows!r} != {list(EXPECTED_SPRITE_ROWS)!r}"
        )
    return len(rows)


def verify_rom(path: Path) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != ROM_SIZE or digest != ROM_SHA256:
        raise ValueError(f"ROM size/hash mismatch: size={len(data)} sha256={digest}")
    offsets = [index for index in range(len(data)) if data.startswith(MARKER, index)]
    if offsets != [MARKER_OFFSET]:
        raise ValueError(f"ROM marker offsets mismatch: {offsets}")
    if data[PAYLOAD_OFFSET : PAYLOAD_OFFSET + len(PAYLOAD)] != PAYLOAD:
        raise ValueError("ROM packed tile payload mismatch")
    expected_footer = bytes.fromhex("ea000000f0000001420100000400")
    if data[-16:-2] != expected_footer:
        raise ValueError("ROM footer metadata mismatch")
    checksum = sum(data[:-2]) & 0xFFFF
    if int.from_bytes(data[-2:], "little") != checksum:
        raise ValueError("ROM footer checksum mismatch")
    if fnv1a64(data) != ROM_FNV1A64:
        raise AssertionError("pinned ROM SHA-256 and FNV-1a identities disagree")
    return data


def verify_manifest(trace: Path, rom: bytes) -> None:
    if TRACE_SIZE <= 0 or TRACE_FNV1A64 == "TO-BE-PINNED":
        raise AssertionError("trace identity constants have not been pinned")
    manifest_path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest: {error}") from error

    expected = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 6,
        "trace_size_bytes": TRACE_SIZE,
        "trace_fnv1a64": TRACE_FNV1A64,
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": CAPTURE_CYCLES,
        "completed_frames": 2,
        "rom_size": ROM_SIZE,
        "rom_fnv1a64": ROM_FNV1A64,
        "bios_size": 8192,
        "bios_fnv1a64": BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": True,
        "complete_bg_cell_history": False,
        "complete_sprite_row_history": True,
    }
    if set(manifest) != {*expected, "trace_file"}:
        raise ValueError("trace manifest field set mismatch")
    for field, wanted in expected.items():
        if manifest.get(field) != wanted:
            raise ValueError(
                f"trace manifest {field} mismatch: {manifest.get(field)!r} != {wanted!r}"
            )
    trace_file = manifest.get("trace_file")
    if not isinstance(trace_file, str) or not trace_file.endswith(
        "/color-sprite-priority-probe/events.csv"
    ):
        raise ValueError(f"trace manifest trace_file mismatch: {trace_file!r}")

    trace_data = trace.read_bytes()
    actual = (len(trace_data), fnv1a64(trace_data), hashlib.sha256(trace_data).hexdigest())
    wanted = (TRACE_SIZE, TRACE_FNV1A64, TRACE_SHA256)
    if actual != wanted:
        raise ValueError(f"trace integrity mismatch: {actual!r} != {wanted!r}")
    if fnv1a64(rom) != manifest["rom_fnv1a64"]:
        raise ValueError("trace manifest is not bound to the verified ROM")


def read_trace(path: Path) -> TraceEvidence:
    vram: list[VramFetch] = []
    mem: list[tuple[int, dict[str, str]]] = []
    sprite_rows: list[tuple[int, int]] = []
    previous_cycle = -1
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V6:
            raise ValueError(f"probe requires exact v6 trace header: {reader.fieldnames!r}")
        for line, row in enumerate(reader, start=2):
            context = f"trace line {line}"
            cycle = decimal(row, "cycle", context)
            if cycle < previous_cycle:
                raise ValueError(f"{context}: cycles move backwards")
            previous_cycle = cycle
            event = row["event"]
            if event == "vram":
                populated = {
                    "cycle", "event", "address", "role", "fetch_value",
                    "fetch_collision",
                }
                unexpected = [
                    field for field in FIELDS_V6
                    if field not in populated and row[field]
                ]
                if unexpected:
                    raise ValueError(f"{context}: unexpected vram fields: {unexpected}")
                vram.append(
                    VramFetch(
                        cycle,
                        row["role"],
                        decimal(row, "address", context),
                        decimal(row, "fetch_value", context),
                        decimal(row, "fetch_collision", context),
                    )
                )
            elif event == "mem":
                mem.append((line, row))
            elif event == "sprite_row":
                # The exact trace identity above and correlate_sprite_rows.py
                # bind the atomic descriptor/row payload. This probe retains
                # ownership of its exact admitted line/slot lattice.
                sprite_rows.append(
                    (
                        decimal(row, "sprite_line_y", context),
                        decimal(row, "sprite_line_slot", context),
                    )
                )
            else:
                raise ValueError(f"{context}: unexpected event {event!r}")
    if not vram or not mem:
        raise ValueError("trace does not contain both complete vram and mem histories")
    verify_sprite_row_sequence(sprite_rows)
    return TraceEvidence(vram, mem, sprite_rows, previous_cycle)


def expected_sprite_tiles() -> tuple[tuple[int, int], ...]:
    rows: list[tuple[int, int]] = []
    for tile_base, value in ((0x4020, 0x2222), (0x4040, 0x3333)):
        # Kept below in scanline order by rebuilding after this validation loop.
        if tile_base & 0x1F:
            raise AssertionError("sprite tile base is not tile-aligned")
    for tile_row in range(8):
        for tile_base, value in (
            (0x4020, 0x2222), (0x4040, 0x3333),
            (0x4020, 0x2222), (0x4040, 0x3333),
            (0x4020, 0x2222), (0x4040, 0x3333),
        ):
            rows.extend(
                (
                    (tile_base + tile_row * 4, value),
                    (tile_base + tile_row * 4 + 2, value),
                )
            )
    return tuple(rows)


def expected_sprite_table() -> tuple[tuple[int, int], ...]:
    """Return the complete line-144 512-byte table transfer."""
    return TABLE_GROUP + tuple(
        (address, 0) for address in range(0x1018, 0x1200, 2)
    )


def verify_vram(fetches: list[VramFetch]) -> dict[str, int]:
    for fetch in fetches:
        if fetch.collision != 0:
            raise ValueError(
                f"{fetch.role} fetch at {fetch.address:#06x} has a collision"
            )

    table = [(item.address, item.value) for item in fetches if item.role == "sprite_table"]
    wanted_table = list(expected_sprite_table())
    wanted_table += wanted_table[:244]
    if table != wanted_table:
        raise ValueError(f"exact sprite-table fetch sequence mismatch: {table!r}")

    tiles = [(item.address, item.value) for item in fetches if item.role == "sprite_tile"]
    wanted_tiles = list(expected_sprite_tiles())
    if tiles != wanted_tiles:
        raise ValueError(f"exact sprite-tile fetch sequence mismatch: {tiles!r}")

    screen_maps = {
        (item.address, item.value)
        for item in fetches if item.role == "screen2_map"
    }
    required_screen_maps = {
        (0x0210, 0x0003), (0x0214, 0x0003), (0x0218, 0x0003)
    }
    if missing := required_screen_maps - screen_maps:
        raise ValueError(f"missing exact opaque Screen 2 map fetches: {sorted(missing)!r}")
    screen_tiles = {
        (item.address, item.value)
        for item in fetches if item.role == "screen2_tile"
    }
    required_screen_tiles = {
        (0x4060 + offset, 0x1111) for offset in range(0, 32, 2)
    }
    if missing := required_screen_tiles - screen_tiles:
        raise ValueError(f"missing exact opaque Screen 2 tile fetches: {sorted(missing)!r}")
    return {
        "sprite_table_words": len(table),
        "sprite_tile_words": len(tiles),
        "screen2_tile_words": sum(
            item.role == "screen2_tile" for item in fetches
        ),
        "screen2_required_unique_words": len(required_screen_tiles),
    }


def verify_gdma(mem: list[tuple[int, dict[str, str]]]) -> int:
    events = [(line, row) for line, row in mem if row["initiator"] == "gdma"]
    if len(events) != len(PAYLOAD):
        raise ValueError(f"expected {len(PAYLOAD)} GDMA events, got {len(events)}")
    previous_cycle = -1
    for word in range(len(PAYLOAD) // 2):
        value = int.from_bytes(PAYLOAD[word * 2 : word * 2 + 2], "little")
        source_offset = PAYLOAD_OFFSET + word * 2
        destination = PAYLOAD_ADDRESS + word * 2
        for kind, (line, row), access, address, space, offset in (
            (
                "read", events[word * 2], "read", 0xF0200 + word * 2,
                "cart_rom_linear", source_offset,
            ),
            (
                "write", events[word * 2 + 1], "write", destination,
                "iram", destination,
            ),
        ):
            context = f"GDMA {kind} word {word} at trace line {line}"
            actual = (
                row["event"], row["initiator"], row["access"],
                decimal(row, "address", context), decimal(row, "value", context),
                decimal(row, "byte_enable", context), row["space"],
                decimal(row, "mapped_offset", context), row["origin_status"],
                row["instruction_id"], row["origin_pc"],
            )
            wanted = (
                "mem", "gdma", access, address, value, 3, space, offset,
                "not_applicable", "", "",
            )
            if actual != wanted:
                raise ValueError(f"{context} mismatch: {actual!r}")
            cycle = decimal(row, "cycle", context)
            if cycle <= previous_cycle:
                raise ValueError("GDMA event cycles are not strictly increasing")
            previous_cycle = cycle
    return len(PAYLOAD) // 2


def verify_cpu_final_words(mem: list[tuple[int, dict[str, str]]]) -> int:
    writes: dict[int, list[tuple[int, dict[str, str]]]] = {
        address: [] for address in CPU_FINAL_WORDS
    }
    for line, row in mem:
        if row["initiator"] != "cpu" or row["access"] != "write":
            continue
        context = f"CPU write at trace line {line}"
        address = decimal(row, "address", context)
        if address in writes:
            writes[address].append((line, row))
    for address, wanted_value in CPU_FINAL_WORDS.items():
        if not writes[address]:
            raise ValueError(f"missing CPU write to {address:#06x}")
        line, row = writes[address][-1]
        context = f"final CPU write to {address:#06x} at trace line {line}"
        actual = (
            decimal(row, "value", context),
            decimal(row, "byte_enable", context),
            row["space"],
            decimal(row, "mapped_offset", context),
            row["origin_status"],
            bool(row["instruction_id"]),
            bool(row["origin_pc"]),
        )
        wanted = (wanted_value, 3, "iram", address, "exact", True, True)
        if actual != wanted:
            raise ValueError(f"{context} mismatch: {actual!r} != {wanted!r}")
    return len(CPU_FINAL_WORDS)


def expected_stable_frame() -> bytes:
    frame = bytearray(BLACK * (WIDTH * HEIGHT))
    for start_x, color in ((64, BLUE), (80, GREEN), (96, GREEN), (112, RED)):
        for y in range(64, 72):
            for x in range(start_x, start_x + 8):
                offset = (y * WIDTH + x) * 3
                frame[offset : offset + 3] = color
    return bytes(frame)


def pixel(frame: bytes, x: int, y: int) -> bytes:
    offset = (y * WIDTH + x) * 3
    return frame[offset : offset + 3]


def verify_frame(path: Path) -> bytes:
    frame = path.read_bytes()
    digest = hashlib.sha256(frame).hexdigest()
    key = pixel(frame, 80, 64) if len(frame) == FRAME_SIZE else b""
    if key == BLUE:
        raise ValueError(
            "key overlap pixel selected opaque Screen 2 blue instead of the "
            "later high-priority sprite green"
        )
    if key != GREEN:
        raise ValueError(f"key overlap pixel is {key.hex()}, expected 00ff00")
    panels = ((64, BLUE, "low-behind-Screen2"),
              (80, GREEN, "critical fallback"),
              (96, GREEN, "high-over-Screen2"),
              (112, RED, "earlier-sprite-order"))
    for start_x, color, label in panels:
        block = [
            pixel(frame, x, y)
            for y in range(64, 72) for x in range(start_x, start_x + 8)
        ]
        if block != [color] * 64:
            raise ValueError(f"{label} control is not exactly 64 {color.hex()} pixels")
    for x, y in (
        (63, 64), (72, 64), (79, 64), (88, 64),
        (95, 64), (104, 64), (111, 64), (120, 64),
        (80, 63), (80, 72),
    ):
        if pixel(frame, x, y) != BLACK:
            raise ValueError(f"diagnostic border pixel ({x},{y}) is not black")
    expected = expected_stable_frame()
    if len(frame) != FRAME_SIZE or digest != STABLE_FRAME_SHA256 or frame != expected:
        raise ValueError(
            f"whole stable frame mismatch: size={len(frame)} sha256={digest}"
        )
    return frame


def verify_root(root: Path) -> dict[str, int]:
    rom = verify_rom(root / "roms" / ROM_NAME)
    trace_path = root / "events.csv"
    verify_manifest(trace_path, rom)
    evidence = read_trace(trace_path)
    counts = verify_vram(evidence.vram)
    counts["sprite_rows"] = len(evidence.sprite_rows)
    counts["gdma_words"] = verify_gdma(evidence.mem)
    counts["cpu_final_words"] = verify_cpu_final_words(evidence.mem)
    verify_frame(root / "frames" / "frame-1.rgb")
    counts["diagnostic_pixels"] = 256
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        counts = verify_root(args.root)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"Color sprite-priority probe: {error}") from error
    print(
        "PASS Color sprite-priority fallback "
        + " ".join(f"{name}={value}" for name, value in counts.items())
    )


if __name__ == "__main__":
    main()
