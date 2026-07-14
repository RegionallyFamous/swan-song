#!/usr/bin/env python3
"""Verify the paired planar/packed 4bpp probe from ROM bytes to RGB pixels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from correlate_bg_cells import OUTPUT_FIELDS as BG_FIELDS
from correlate_provenance import OUTPUT_FIELDS as PROVENANCE_FIELDS
from report_glyphs import OUTPUT_FIELDS as GLYPH_FIELDS, build_report_records
from verify_trace import FIELDS_V5


PLANAR = "planar"
PACKED = "packed"
VARIANTS = (PLANAR, PACKED)
ROM_SIZE = 128 * 1024
PATTERN_OFFSET = 0x10100
PATTERN_PHYSICAL = 0xF0100
MARKER_OFFSET = 0x10400
TILE_ADDRESS = 0x4020
MAP_ADDRESSES = (0x1A14, 0x1A16, 0x1A18, 0x1A1A)
ROM_NAMES = {
    PLANAR: "wsc_4bpp_planar_probe.wsc",
    PACKED: "wsc_4bpp_packed_probe.wsc",
}
ROM_SHA256 = {
    PLANAR: "31731d330004bcb54338096654c7f4bb75c2ba8d186e139f8a4724f5d700bd42",
    PACKED: "9525d1de59e902745f0f7c8acd2229235bd6343ddedc17acb03f62411be28959",
}
ROM_FNV1A64 = {
    PLANAR: "8d65b6afb84cc752",
    PACKED: "8a9ca6a337b5c38e",
}
TRACE_SIZE = {PLANAR: 9600009, PACKED: 9600151}
TRACE_FNV1A64 = {PLANAR: "beff3a1376017692", PACKED: "7ce75e0f0d83bb9b"}
FRAME_SHA256 = {
    0: "42cbd40de83feff488f8c63cfbb0bf0a160f7c96416bcb74328b9982e1d04bdb",
    1: "7f672cb770893d021bb6c684efccb9b118894f657e65dd4e8b966a2d90fefa5d",
}
GLYPH_CONTACT_SHA256 = "68c7b6fefb9733ba5619b7c07a18f71fc3288f77b428ce8c5c691cf2428aac7d"
BIOS_FNV1A64 = "bde71f09ac34c168"
EXPECTED_EVENTS = {
    "cpu": False,
    "bank": False,
    "vram": True,
    "mem": True,
    "bg_cell": True,
}

PIXELS = (
    (1, 2, 3, 4, 5, 6, 7, 8),
    (8, 7, 6, 5, 4, 3, 2, 1),
    (1, 1, 2, 2, 3, 3, 4, 4),
    (5, 5, 6, 6, 7, 7, 8, 8),
    (9, 10, 11, 12, 13, 14, 15, 1),
    (15, 14, 13, 12, 11, 10, 9, 8),
    (2, 4, 6, 8, 10, 12, 14, 1),
    (1, 3, 5, 7, 9, 11, 13, 15),
)
PALETTE = (
    0x000, 0x00F, 0x0F0, 0xF00, 0x0FF, 0xF0F, 0xFF0, 0x888,
    0x444, 0x08F, 0x0F8, 0x80F, 0xF80, 0x8F0, 0xF08, 0xFFF,
)
KNOWN_TILE_BYTES = {
    PLANAR: bytes.fromhex(
        "aa661e0155667880cc3c0300cc3cfc03"
        "ab661efeaaccf0ff01aa661eff55330f"
    ),
    PACKED: bytes.fromhex(
        "12345678876543211122334455667788"
        "9abcdef1fedcba982468ace113579bdf"
    ),
}


@dataclass(frozen=True)
class Placement:
    address: int
    value: int
    x: int
    hflip: int
    vflip: int
    write_line: int
    write_cycle: int
    instruction_id: int
    origin_pc: int


PLACEMENTS = (
    Placement(0x1A14, 0x0001, 10, 0, 0, 2287, 38328, 28, 0xF002E),
    Placement(0x1A16, 0x4001, 11, 1, 0, 2290, 38352, 29, 0xF0034),
    Placement(0x1A18, 0x8001, 12, 0, 1, 2293, 38376, 30, 0xF003A),
    Placement(0x1A1A, 0xC001, 13, 1, 1, 2298, 38424, 31, 0xF0040),
)


@dataclass(frozen=True)
class GdmaWord:
    source_cycle: int
    write_cycle: int
    source_line: int
    write_line: int


@dataclass
class TraceEvidence:
    gdma: list[tuple[int, dict[str, str]]]
    lines: dict[int, dict[str, str]]
    selected_bg_cells: list[tuple[int, dict[str, str]]]
    last_cycle: int


def decimal(row: dict[str, str], field: str, context: str = "row") -> int:
    value = row.get(field, "")
    if not value:
        raise ValueError(f"{context}: empty {field}")
    try:
        return int(value, 10)
    except ValueError as error:
        raise ValueError(f"{context}: invalid {field}: {value!r}") from error


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def tile_bytes(variant: str) -> bytes:
    result = bytearray()
    for row in PIXELS:
        if variant == PACKED:
            result.extend(((row[index] << 4) | row[index + 1]) for index in range(0, 8, 2))
            continue
        planes = [0, 0, 0, 0]
        for x, pixel in enumerate(row):
            mask = 0x80 >> x
            for plane in range(4):
                if pixel & (1 << plane):
                    planes[plane] |= mask
        result.extend(planes)
    return bytes(result)


def decode_tile(payload: bytes, variant: str) -> tuple[tuple[int, ...], ...]:
    if len(payload) != 32:
        raise ValueError(f"{variant} 4bpp known-answer vector must be 32 bytes")
    decoded: list[tuple[int, ...]] = []
    for start in range(0, len(payload), 4):
        encoded = payload[start : start + 4]
        if variant == PACKED:
            decoded.append(
                tuple(component for byte in encoded for component in (byte >> 4, byte & 0xF))
            )
            continue
        row = []
        for x in range(8):
            row.append(
                sum(((encoded[plane] >> (7 - x)) & 1) << plane for plane in range(4))
            )
        decoded.append(tuple(row))
    return tuple(decoded)


def verify_known_vectors() -> None:
    for variant in VARIANTS:
        vector = KNOWN_TILE_BYTES[variant]
        if tile_bytes(variant) != vector:
            raise AssertionError(f"{variant} 4bpp encoder disagrees with literal known answer")
        if decode_tile(vector, variant) != PIXELS:
            raise AssertionError(f"{variant} literal known answer does not decode to PIXELS")


def marker(variant: str) -> bytes:
    return f"SWANSONG-WSC-4BPP-{variant.upper()}-V1\0".encode("ascii")


def verify_rom(path: Path, variant: str) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != ROM_SIZE or digest != ROM_SHA256[variant]:
        raise ValueError(
            f"{variant} ROM size/hash mismatch: size={len(data)} sha256={digest}"
        )
    expected_marker = marker(variant)
    offsets = [index for index in range(len(data)) if data.startswith(expected_marker, index)]
    if offsets != [MARKER_OFFSET]:
        raise ValueError(f"{variant} ROM marker offsets mismatch: {offsets}")
    if data[PATTERN_OFFSET : PATTERN_OFFSET + 32] != KNOWN_TILE_BYTES[variant]:
        raise ValueError(f"{variant} ROM 4bpp tile payload mismatch")

    expected_footer = bytes.fromhex("ea000000f0000001") + bytes(
        (0x40 if variant == PLANAR else 0x41, 0x01, 0x00, 0x00, 0x04, 0x00)
    )
    if data[-16:-2] != expected_footer:
        raise ValueError(f"{variant} ROM footer metadata mismatch")
    checksum = sum(data[:-2]) & 0xFFFF
    if int.from_bytes(data[-2:], "little") != checksum:
        raise ValueError(f"{variant} ROM footer checksum mismatch")
    if fnv1a64(data) != ROM_FNV1A64[variant]:
        raise AssertionError(f"{variant} pinned ROM identities disagree")
    return data


def verify_manifest(trace: Path, rom: bytes, variant: str) -> None:
    path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {variant} trace manifest: {error}") from error
    expected = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_size_bytes": TRACE_SIZE[variant],
        "trace_fnv1a64": TRACE_FNV1A64[variant],
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": 930689,
        "completed_frames": 2,
        "rom_size": ROM_SIZE,
        "rom_fnv1a64": ROM_FNV1A64[variant],
        "bios_size": 8192,
        "bios_fnv1a64": BIOS_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": True,
        "complete_bg_cell_history": True,
    }
    if set(manifest) != {*expected, "trace_file"}:
        raise ValueError(f"{variant} trace manifest field set mismatch")
    for field, wanted in expected.items():
        if manifest.get(field) != wanted:
            raise ValueError(
                f"{variant} trace manifest {field} mismatch: "
                f"{manifest.get(field)!r} != {wanted!r}"
            )
    trace_file = manifest.get("trace_file")
    if not isinstance(trace_file, str) or not trace_file.endswith(f"/{variant}/events.csv"):
        raise ValueError(f"{variant} trace manifest trace_file mismatch: {trace_file!r}")
    actual_size = trace.stat().st_size
    actual_fnv = fnv1a64(trace.read_bytes())
    if actual_size != TRACE_SIZE[variant] or actual_fnv != TRACE_FNV1A64[variant]:
        raise ValueError(
            f"{variant} trace integrity mismatch: size={actual_size} fnv1a64={actual_fnv}"
        )
    if fnv1a64(rom) != manifest["rom_fnv1a64"]:
        raise ValueError(f"{variant} trace manifest is not bound to its ROM")


def read_csv(path: Path, fields: list[str], description: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != fields:
            raise ValueError(f"{description} requires exact header")
        return list(reader)


def selected_cells(path: Path) -> tuple[list[dict[str, str]], set[int]]:
    rows = read_csv(path, BG_FIELDS, "4bpp atomic-cell artifact")
    selected = [row for row in rows if decimal(row, "map_address") in MAP_ADDRESSES]
    wanted_lines: set[int] = set()
    for row in selected:
        for field in (
            "line", "map_raw_line", "tile0_raw_line", "tile1_raw_line",
            "map_lo_write_line", "map_hi_write_line",
            "row_b0_write_line", "row_b1_write_line",
            "row_b2_write_line", "row_b3_write_line",
        ):
            wanted_lines.add(decimal(row, field, "atomic cell"))
    return selected, wanted_lines


def read_trace(path: Path, wanted_lines: set[int]) -> TraceEvidence:
    gdma: list[tuple[int, dict[str, str]]] = []
    lines: dict[int, dict[str, str]] = {}
    selected_bg_cells: list[tuple[int, dict[str, str]]] = []
    previous_cycle = -1
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError("4bpp probe requires the exact v5 trace header")
        for line, row in enumerate(reader, start=2):
            cycle = decimal(row, "cycle", f"trace line {line}")
            if cycle < previous_cycle:
                raise ValueError(f"trace line {line}: cycles are not monotonic")
            previous_cycle = cycle
            if row["event"] not in {"mem", "vram", "bg_cell"}:
                raise ValueError(f"trace line {line}: unexpected event {row['event']!r}")
            if row["event"] == "mem" and row["initiator"] == "gdma":
                gdma.append((line, row))
            if row["event"] == "bg_cell" and decimal(
                row, "map_address", f"trace line {line}"
            ) in MAP_ADDRESSES:
                selected_bg_cells.append((line, row))
            if line in wanted_lines:
                lines[line] = row
    missing = sorted(wanted_lines - set(lines))
    if missing:
        raise ValueError(f"trace lacks atomic-cell evidence lines: {missing[:4]}")
    return TraceEvidence(
        gdma=gdma,
        lines=lines,
        selected_bg_cells=selected_bg_cells,
        last_cycle=previous_cycle,
    )


def verify_gdma(
    events: list[tuple[int, dict[str, str]]], variant: str
) -> dict[int, GdmaWord]:
    payload = KNOWN_TILE_BYTES[variant]
    if len(events) != 32:
        raise ValueError(f"{variant}: expected 32 GDMA events, got {len(events)}")
    result: dict[int, GdmaWord] = {}
    previous_cycle = -1
    for word in range(16):
        (read_line, read), (write_line, write) = events[word * 2 : word * 2 + 2]
        value = int.from_bytes(payload[word * 2 : word * 2 + 2], "little")
        source_offset = PATTERN_OFFSET + word * 2
        destination = TILE_ADDRESS + word * 2
        for context, row, access, address, space, offset in (
            ("read", read, "read", PATTERN_PHYSICAL + word * 2, "cart_rom_linear", source_offset),
            ("write", write, "write", destination, "iram", destination),
        ):
            actual = (
                row["event"], row["initiator"], row["access"],
                decimal(row, "address"), decimal(row, "value"),
                decimal(row, "byte_enable"), row["space"],
                decimal(row, "mapped_offset"), row["origin_status"],
                row["instruction_id"], row["origin_pc"],
            )
            wanted = (
                "mem", "gdma", access, address, value, 3, space, offset,
                "not_applicable", "", "",
            )
            if actual != wanted:
                raise ValueError(
                    f"{variant} GDMA {context} word {word} mismatch: {actual!r}"
                )
            cycle = decimal(row, "cycle")
            if cycle <= previous_cycle:
                raise ValueError(f"{variant} GDMA cycles are not strictly increasing")
            previous_cycle = cycle
        result[source_offset] = GdmaWord(
            decimal(read, "cycle"), decimal(write, "cycle"), read_line, write_line
        )
    return result


def _require_fields(row: dict[str, str], expected: dict[str, str], context: str) -> None:
    for field, wanted in expected.items():
        if row.get(field) != wanted:
            raise ValueError(
                f"{context}: {field} expected {wanted!r}, got {row.get(field)!r}"
            )


def verify_cell_semantics(
    cells: list[dict[str, str]], variant: str, gdma: dict[int, GdmaWord]
) -> None:
    payload = KNOWN_TILE_BYTES[variant]
    packed = "1" if variant == PACKED else "0"
    if len(cells) != 64:
        raise ValueError(f"{variant}: expected 64 selected rows, got {len(cells)}")
    identities = [
        (decimal(cell, "line", "atomic cell"), decimal(cell, "cycle", "atomic cell"))
        for cell in cells
    ]
    if len(set(identities)) != 64:
        raise ValueError(f"{variant}: selected atomic-cell line/cycle identities are not unique")
    raw_lines: list[int] = []
    for placement in PLACEMENTS:
        chosen = [row for row in cells if decimal(row, "map_address") == placement.address]
        counts = Counter(decimal(row, "tile_row") for row in chosen)
        if len(chosen) != 16 or counts != Counter({row: 2 for row in range(8)}):
            raise ValueError(f"{variant} map 0x{placement.address:04x}: rows are not two frames")
        ordered = sorted(chosen, key=lambda row: decimal(row, "cycle"))
        expected_rows = list(reversed(range(8))) if placement.vflip else list(range(8))
        occurrences = [ordered[:8], ordered[8:]]
        if any(
            [decimal(row, "tile_row") for row in occurrence] != expected_rows
            for occurrence in occurrences
        ):
            raise ValueError(
                f"{variant} map 0x{placement.address:04x}: not exactly two complete occurrences"
            )
        for cell in chosen:
            tile_row = decimal(cell, "tile_row")
            context = f"{variant} map 0x{placement.address:04x} row {tile_row}"
            start = tile_row * 4
            row_bytes = payload[start : start + 4]
            row_address = TILE_ADDRESS + start
            cell_line = decimal(cell, "line", context)
            cell_cycle = decimal(cell, "cycle", context)
            for prefix, line_delta, cycle_delta in (
                ("map", 10, 90), ("tile0", 9, 82), ("tile1", 7, 74)
            ):
                raw_line = decimal(cell, f"{prefix}_raw_line", context)
                raw_cycle = decimal(cell, f"{prefix}_raw_cycle", context)
                if raw_line != cell_line - line_delta or raw_cycle != cell_cycle - cycle_delta:
                    raise ValueError(
                        f"{context}: {prefix} raw group is not the adjacent measured fetch"
                    )
                raw_lines.append(raw_line)
            _require_fields(
                cell,
                {
                    "bg_layer": "screen1", "map_x": str(placement.x), "map_y": "8",
                    "map_value": str(placement.value), "tile_bank_enabled": "1",
                    "tile_index": "1", "palette": "0", "hflip": str(placement.hflip),
                    "vflip": str(placement.vflip), "bpp": "4", "packed": packed,
                    "tile_row_address": str(row_address), "tile_row_bytes": "4",
                    "tile_row_value": str(int.from_bytes(row_bytes, "little")),
                    "map_collision": "0", "tile_row_collision": "0",
                    "coverage_status": "complete_from_reset", "map_raw_collision": "0",
                    "map_scoreboard_status": "match", "map_writer_summary": "cpu_exact",
                    "map_source_summary": "cpu_write", "tile0_raw_address": str(row_address),
                    "tile0_raw_value": str(int.from_bytes(row_bytes[:2], "little")),
                    "tile0_raw_collision": "0", "tile1_raw_address": str(row_address + 2),
                    "tile1_raw_value": str(int.from_bytes(row_bytes[2:], "little")),
                    "tile1_raw_collision": "0", "row_scoreboard_status": "match",
                    "row_writer_summary": "gdma", "row_source_summary": "gdma_rom",
                },
                context,
            )
            if cell["contributing_raw_lines"] != f"{cell['tile0_raw_line']};{cell['tile1_raw_line']}":
                raise ValueError(f"{context}: raw line pair mismatch")
            if cell["contributing_raw_cycles"] != f"{cell['tile0_raw_cycle']};{cell['tile1_raw_cycle']}":
                raise ValueError(f"{context}: raw cycle pair mismatch")

            map_cycle = decimal(cell, "map_lo_write_cycle", context)
            map_raw = decimal(cell, "map_raw_cycle", context)
            if not map_cycle < map_raw < decimal(cell, "cycle", context):
                raise ValueError(f"{context}: invalid map write/fetch/cell order")
            for prefix, value in (("map_lo", placement.value & 0xFF), ("map_hi", placement.value >> 8)):
                _require_fields(
                    cell,
                    {
                        f"{prefix}_value": str(value), f"{prefix}_initiator": "cpu",
                        f"{prefix}_write_line": str(placement.write_line),
                        f"{prefix}_write_cycle": str(placement.write_cycle),
                        f"{prefix}_instruction_id": str(placement.instruction_id),
                        f"{prefix}_origin_pc": str(placement.origin_pc),
                        f"{prefix}_source_space": "", f"{prefix}_source_offset": "",
                        f"{prefix}_source_read_cycle": "",
                    },
                    context,
                )
                if decimal(cell, f"{prefix}_write_cycle", context) != map_cycle:
                    raise ValueError(f"{context}: split map write")
            if cell["map_lo_write_line"] != cell["map_hi_write_line"]:
                raise ValueError(f"{context}: split map write line")

            for lane, value in enumerate(row_bytes):
                prefix = f"row_b{lane}"
                source_offset = PATTERN_OFFSET + start + lane
                word = gdma.get(source_offset & ~1)
                if word is None:
                    raise ValueError(f"{context}: missing GDMA word for lane {lane}")
                _require_fields(
                    cell,
                    {
                        f"{prefix}_value": str(value), f"{prefix}_initiator": "gdma",
                        f"{prefix}_instruction_id": "", f"{prefix}_origin_pc": "",
                        f"{prefix}_source_space": "cart_rom_linear",
                        f"{prefix}_source_offset": str(source_offset),
                        f"{prefix}_source_read_cycle": str(word.source_cycle),
                        f"{prefix}_write_cycle": str(word.write_cycle),
                        f"{prefix}_write_line": str(word.write_line),
                    },
                    context,
                )
                raw_cycle = decimal(cell, "tile0_raw_cycle" if lane < 2 else "tile1_raw_cycle")
                if not word.source_cycle < word.write_cycle < raw_cycle < decimal(cell, "cycle"):
                    raise ValueError(f"{context}: invalid lane {lane} source/write/fetch order")
    if len(raw_lines) != 192 or len(set(raw_lines)) != 192:
        raise ValueError(f"{variant}: selected cells do not have unique adjacent raw fetch lines")


def verify_cell_trace_links(cells: list[dict[str, str]], trace: TraceEvidence) -> None:
    csv_identities = {
        (decimal(cell, "line", "atomic cell"), decimal(cell, "cycle", "atomic cell"))
        for cell in cells
    }
    trace_identities = {
        (line, decimal(row, "cycle", f"trace line {line}"))
        for line, row in trace.selected_bg_cells
    }
    if (
        len(cells) != 64
        or len(csv_identities) != 64
        or len(trace.selected_bg_cells) != 64
        or len(trace_identities) != 64
        or csv_identities != trace_identities
    ):
        raise ValueError(
            "selected atomic-cell CSV and authentic trace bg_cell events are not one-to-one"
        )
    for cell in cells:
        context = f"cell line {cell['line']}"
        placement = next(item for item in PLACEMENTS if item.address == decimal(cell, "map_address"))
        atomic = trace.lines[decimal(cell, "line")]
        expected_atomic = {
            "event": "bg_cell", "cycle": cell["cycle"], "bg_layer": "1",
            "map_address": cell["map_address"], "map_value": cell["map_value"],
            "map_x": cell["map_x"], "map_y": cell["map_y"],
            "tile_bank_enabled": "1", "tile_index": "1", "palette": "0",
            "hflip": str(placement.hflip), "vflip": str(placement.vflip),
            "bpp": "4", "packed": cell["packed"], "tile_row": cell["tile_row"],
            "tile_row_address": cell["tile_row_address"], "tile_row_bytes": "4",
            "tile_row_value": cell["tile_row_value"], "map_collision": "0",
            "tile_row_collision": "0",
        }
        _require_fields(atomic, expected_atomic, context)
        for prefix, role in (("map", "screen1_map"), ("tile0", "screen1_tile"), ("tile1", "screen1_tile")):
            raw = trace.lines[decimal(cell, f"{prefix}_raw_line")]
            value_field = "map_value" if prefix == "map" else f"{prefix}_raw_value"
            address_field = "map_address" if prefix == "map" else f"{prefix}_raw_address"
            _require_fields(
                raw,
                {
                    "event": "vram", "cycle": cell[f"{prefix}_raw_cycle"],
                    "role": role, "address": cell[address_field],
                    "fetch_value": cell[value_field], "fetch_collision": "0",
                },
                context,
            )
        write = trace.lines[decimal(cell, "map_lo_write_line")]
        _require_fields(
            write,
            {
                "event": "mem", "cycle": cell["map_lo_write_cycle"],
                "address": cell["map_address"], "value": cell["map_value"],
                "initiator": "cpu", "access": "write", "byte_enable": "3",
                "space": "iram", "mapped_offset": cell["map_address"],
                "instruction_id": cell["map_lo_instruction_id"],
                "origin_pc": cell["map_lo_origin_pc"], "origin_status": "exact",
            },
            context,
        )


def verify_provenance(path: Path, cells: list[dict[str, str]]) -> None:
    rows = read_csv(path, PROVENANCE_FIELDS, "4bpp provenance artifact")
    if len(rows) != 25921:
        raise ValueError(f"provenance row count mismatch: {len(rows)} != 25921")
    keys = [(row["cycle"], row["role"], row["address"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("provenance contains duplicate (cycle, role, address) keys")
    indexed = dict(zip(keys, rows))
    for cell in cells:
        for prefix in ("tile0", "tile1"):
            key = (cell[f"{prefix}_raw_cycle"], "screen1_tile", cell[f"{prefix}_raw_address"])
            row = indexed.get(key)
            if row is None:
                raise ValueError(f"provenance lacks selected fetch {key!r}")
            lane = 0 if prefix == "tile0" else 2
            expected = {
                "fetch_value": cell[f"{prefix}_raw_value"], "fetch_collision": "0",
                "reconstructed_value": cell[f"{prefix}_raw_value"],
                "scoreboard_status": "match", "ram_status": "complete_same_write",
                "writer_summary": "gdma", "source_summary": "gdma_rom_same_transfer",
                "coverage_status": "complete_from_reset",
            }
            for side, offset in (("lo", 0), ("hi", 1)):
                cell_prefix = f"row_b{lane + offset}"
                expected.update(
                    {
                        f"{side}_value": cell[f"{cell_prefix}_value"],
                        f"{side}_write_line": cell[f"{cell_prefix}_write_line"],
                        f"{side}_write_cycle": cell[f"{cell_prefix}_write_cycle"],
                        f"{side}_initiator": "gdma", f"{side}_instruction_id": "",
                        f"{side}_origin_pc": "", f"{side}_source_space": "cart_rom_linear",
                        f"{side}_source_offset": cell[f"{cell_prefix}_source_offset"],
                        f"{side}_source_read_cycle": cell[f"{cell_prefix}_source_read_cycle"],
                    }
                )
            _require_fields(row, expected, f"provenance fetch {key!r}")


def bitmap_rows(placement: Placement) -> str:
    rows = list(PIXELS)
    if placement.vflip:
        rows.reverse()
    if placement.hflip:
        rows = [tuple(reversed(row)) for row in rows]
    return "/".join("".join(f"{pixel:X}" for pixel in row) for row in rows)


def verify_glyph_rows(
    rows: list[dict[str, str]], variant: str, gdma: dict[int, GdmaWord]
) -> None:
    counts = Counter(row["confidence"] for row in rows)
    if len(rows) != 592 or counts != {"exact": 558, "incomplete": 34}:
        raise ValueError(f"{variant} glyph epoch population mismatch: {len(rows)} {dict(counts)}")
    sourced = [row for row in rows if row["row_source_ranges"]]
    if len(sourced) != 4:
        raise ValueError(f"{variant}: expected four ROM-sourced glyph epochs, got {len(sourced)}")
    read_cycles = ";".join(str(gdma[offset].source_cycle) for offset in sorted(gdma))
    write_cycles = ";".join(str(gdma[offset].write_cycle) for offset in sorted(gdma))
    packed = "1" if variant == PACKED else "0"
    for epoch, (row, placement) in enumerate(zip(sourced, PLACEMENTS), start=228):
        bitmap = bitmap_rows(placement)
        expected = {
            "epoch_index": str(epoch), "layer": "screen1", "tile_index": "1",
            "tile_bank_enabled": "1", "map_address": f"0x{placement.address:04x}",
            "map_value": f"0x{placement.value:04x}", "map_x": str(placement.x),
            "map_y": "8", "palette": "0", "bpp": "4", "packed": packed,
            "hflip": str(placement.hflip), "vflip": str(placement.vflip),
            "occurrence_count": "2", "rows_observed": "0,1,2,3,4,5,6,7",
            "missing_rows": "", "complete": "1", "collision": "0", "mixed": "0",
            "confidence": "exact", "flags": "", "bitmap_rows": bitmap,
            "bitmap_fingerprint": hashlib.sha256(bitmap.encode("ascii")).hexdigest(),
            "coverage_statuses": "complete_from_reset", "map_scoreboard_statuses": "match",
            "row_scoreboard_statuses": "match", "map_writer_summaries": "cpu_exact",
            "map_writer_initiators": "cpu", "row_writer_summaries": "gdma",
            "row_writer_initiators": "gdma", "row_writer_origin_pcs": "",
            "tile_iram_ranges": "0x4020-0x403f", "row_source_summaries": "gdma_rom",
            "row_source_ranges": "cart_rom_linear:0x010100-0x01011f",
            "row_source_read_cycle_range": read_cycles, "row_write_cycle_range": write_cycles,
        }
        _require_fields(row, expected, f"{variant} glyph epoch {epoch}")
        for field in (
            "occurrence_cycles", "first_cycle", "last_cycle", "map_writer_instruction_ids",
            "map_writer_origin_pcs", "map_write_cycle_range",
        ):
            if not row[field]:
                raise ValueError(f"{variant} glyph epoch {epoch}: empty {field}")


def verify_glyph_report(path: Path, cells_path: Path, variant: str, gdma: dict[int, GdmaWord]) -> None:
    rows = read_csv(path, GLYPH_FIELDS, "4bpp glyph report")
    expected = build_report_records(cells_path)
    if rows != expected:
        raise ValueError(f"{variant} glyph report does not match its atomic-cell input")
    verify_glyph_rows(rows, variant, gdma)


def expected_frame(index: int) -> bytes:
    width, height = 224, 144
    data = bytearray(b"\x00\x00\x00" * (width * height))
    if index == 0:
        data[: 58 * 3] = b"\xff\xff\xff" * 58
    for placement in PLACEMENTS:
        rows = list(PIXELS)
        if placement.vflip:
            rows.reverse()
        if placement.hflip:
            rows = [tuple(reversed(row)) for row in rows]
        for y, row in enumerate(rows):
            for x, color in enumerate(row):
                rgb = PALETTE[color]
                offset = (((8 * 8 + y) * width) + placement.x * 8 + x) * 3
                data[offset : offset + 3] = bytes(
                    (((rgb >> 8) & 0xF) * 17, ((rgb >> 4) & 0xF) * 17, (rgb & 0xF) * 17)
                )
    return bytes(data)


def verify_frame(path: Path, index: int) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != FRAME_SHA256[index] or data != expected_frame(index):
        raise ValueError(f"frame {index} pixel mismatch: size={len(data)} sha256={digest}")
    return data


def verify_glyph_contact(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ValueError(f"missing glyph contact sheet: {path}") from error
    digest = hashlib.sha256(data).hexdigest()
    if digest != GLYPH_CONTACT_SHA256 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"glyph contact sheet hash/format mismatch: sha256={digest}")
    return data


def verify_variant(root: Path, variant: str) -> tuple[bytes, bytes, bytes]:
    rom_path = root / "roms" / ROM_NAMES[variant]
    variant_root = root / variant
    trace_path = variant_root / "events.csv"
    cells_path = variant_root / "bg-cells.csv"
    rom = verify_rom(rom_path, variant)
    verify_manifest(trace_path, rom, variant)
    cells, wanted_lines = selected_cells(cells_path)
    trace = read_trace(trace_path, wanted_lines)
    if trace.last_cycle >= 930689:
        raise ValueError(f"{variant} trace extends beyond its capture window")
    gdma = verify_gdma(trace.gdma, variant)
    verify_cell_semantics(cells, variant, gdma)
    verify_cell_trace_links(cells, trace)
    verify_provenance(variant_root / "provenance.csv", cells)
    verify_glyph_report(variant_root / "glyph-epochs.csv", cells_path, variant, gdma)
    return (
        verify_frame(variant_root / "frames/frame-0.rgb", 0),
        verify_frame(variant_root / "frames/frame-1.rgb", 1),
        verify_glyph_contact(variant_root / "glyph-contact.png"),
    )


def verify_root(root: Path) -> None:
    verify_known_vectors()
    frames = {variant: verify_variant(root, variant) for variant in VARIANTS}
    for index in (0, 1):
        if frames[PLANAR][index] != frames[PACKED][index]:
            raise ValueError(f"planar/packed frame {index} cross-format mismatch")
    if frames[PLANAR][2] != frames[PACKED][2]:
        raise ValueError("planar/packed glyph contact cross-format mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="paired 4bpp probe artifact root")
    args = parser.parse_args()
    try:
        verify_root(args.root)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"4bpp probe: {error}") from error
    print(
        "PASS 4bpp probe variants=2 per_variant_frames=2 total_frames=4 "
        "per_variant_gdma_words=16 total_gdma_words=32 per_variant_placements=4 "
        "total_placements=8 per_variant_promoted_rows=64 total_promoted_rows=128 "
        "per_variant_provenance_rows=25921 total_provenance_rows=51842 "
        "contacts=2 pixels_and_contacts=cross-format-exact"
    )


if __name__ == "__main__":
    main()
