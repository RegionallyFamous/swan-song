#!/usr/bin/env python3
"""Turn atomic background-cell provenance into glyph-candidate artifacts.

The input is the CSV produced by ``correlate_bg_cells.py``.  A candidate is a
tile-use epoch, not a character: this tool never guesses a codepoint or assumes
that a tile index is a stable character ID.  It reconstructs the pixels that
were presented by one map cell, preserves repeated occurrences, and retains
the writer/source evidence needed for later title-specific analysis.

The source CSV has no frame marker.  An occurrence therefore ends when the same
normalized visual row repeats or when that map slot's tile-use metadata changes;
its exact start/end cycles remain in the report so long gaps are visible rather
than silently assigned to a frame.
"""

from __future__ import annotations

import argparse
import binascii
import csv
import hashlib
import math
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from correlate_bg_cells import OUTPUT_FIELDS as BG_OUTPUT_FIELDS


BYTE_SUFFIXES = (
    "value",
    "write_line",
    "write_cycle",
    "initiator",
    "instruction_id",
    "origin_pc",
    "source_space",
    "source_offset",
    "source_read_cycle",
)
MAP_PREFIXES = ("map_lo", "map_hi")
ROW_PREFIXES = ("row_b0", "row_b1", "row_b2", "row_b3")

OUTPUT_FIELDS = [
    "epoch_index",
    "layer",
    "tile_index",
    "tile_bank_enabled",
    "map_address",
    "map_value",
    "map_x",
    "map_y",
    "palette",
    "bpp",
    "packed",
    "hflip",
    "vflip",
    "occurrence_count",
    "occurrence_cycles",
    "first_cycle",
    "last_cycle",
    "rows_observed",
    "missing_rows",
    "complete",
    "collision",
    "mixed",
    "confidence",
    "flags",
    "bitmap_rows",
    "bitmap_fingerprint",
    "coverage_statuses",
    "map_scoreboard_statuses",
    "row_scoreboard_statuses",
    "map_writer_summaries",
    "map_writer_initiators",
    "map_writer_instruction_ids",
    "map_writer_origin_pcs",
    "map_write_cycle_range",
    "row_writer_summaries",
    "row_writer_initiators",
    "row_writer_origin_pcs",
    "row_write_cycle_range",
    "tile_iram_ranges",
    "row_source_summaries",
    "row_source_ranges",
    "row_source_read_cycle_range",
]

CONTACT_MODES = ("all", "exact", "unique-exact")


@dataclass(frozen=True)
class TileUse:
    layer: str
    map_address: int
    map_value: int
    map_x: int
    map_y: int
    tile_index: int
    tile_bank_enabled: int
    palette: int
    bpp: int
    packed: int
    hflip: int
    vflip: int

    @property
    def slot(self) -> tuple[str, int]:
        return (self.layer, self.map_address)


@dataclass(frozen=True)
class CellRow:
    line: int
    cycle: int
    visual_row: int
    pixels: tuple[int, ...]
    values: dict[str, str]


@dataclass
class Occurrence:
    use: TileUse
    rows: dict[int, CellRow] = field(default_factory=dict)

    @property
    def first_cycle(self) -> int:
        return min(row.cycle for row in self.rows.values())

    @property
    def last_cycle(self) -> int:
        return max(row.cycle for row in self.rows.values())

    @property
    def complete(self) -> bool:
        return set(self.rows) == set(range(8))

    def bitmap_rows(self) -> str:
        rendered = []
        for index in range(8):
            row = self.rows.get(index)
            rendered.append(
                "????????" if row is None else "".join(format(value, "X") for value in row.pixels)
            )
        return "/".join(rendered)

    def provenance_signature(self) -> tuple[object, ...]:
        result: list[object] = [self.use, self.bitmap_rows()]
        for visual_row in range(8):
            row = self.rows.get(visual_row)
            if row is None:
                result.append(None)
                continue
            evidence = []
            for prefix in MAP_PREFIXES + ROW_PREFIXES[: tile_byte_count(self.use.bpp)]:
                evidence.extend(row.values[f"{prefix}_{suffix}"] for suffix in BYTE_SUFFIXES)
            evidence.extend(
                row.values[field]
                for field in (
                    "coverage_status",
                    "map_collision",
                    "tile_row_collision",
                    "map_scoreboard_status",
                    "row_scoreboard_status",
                    "map_writer_summary",
                    "map_source_summary",
                    "row_writer_summary",
                    "row_source_summary",
                )
            )
            result.append(tuple(evidence))
        result.append(tuple(sorted(occurrence_flags(self))))
        return tuple(result)


@dataclass
class Epoch:
    use: TileUse
    occurrences: list[Occurrence]

    @property
    def first_cycle(self) -> int:
        return self.occurrences[0].first_cycle

    @property
    def last_cycle(self) -> int:
        return self.occurrences[-1].last_cycle


def decimal(row: dict[str, str], field_name: str, line: int, *, blank: bool = False) -> int | None:
    value = row[field_name]
    if value == "" and blank:
        return None
    if value == "":
        raise ValueError(f"line {line}: empty {field_name}")
    try:
        return int(value, 10)
    except ValueError as error:
        raise ValueError(f"line {line}: invalid {field_name} {value!r}") from error


def bit(row_byte: int, pixel: int) -> int:
    return (row_byte >> (7 - pixel)) & 1


def tile_byte_count(bpp: int) -> int:
    return 2 if bpp == 2 else 4


def decode_pixels(row_bytes: list[int], bpp: int, packed: int, hflip: int) -> tuple[int, ...]:
    if packed:
        if bpp == 2:
            pixels = tuple(
                (value >> shift) & 0x3
                for value in row_bytes
                for shift in (6, 4, 2, 0)
            )
        else:
            pixels = tuple(
                nibble
                for value in row_bytes
                for nibble in ((value >> 4) & 0xF, value & 0xF)
            )
    else:
        pixels = tuple(
            sum(bit(row_bytes[plane], pixel) << plane for plane in range(bpp))
            for pixel in range(8)
        )
    if hflip:
        pixels = tuple(reversed(pixels))
    return pixels


def parse_cell(raw: dict[str, str], line: int) -> tuple[TileUse, CellRow]:
    layer = raw["bg_layer"]
    if layer not in {"screen1", "screen2"}:
        raise ValueError(f"line {line}: invalid bg_layer {layer!r}")
    bpp = decimal(raw, "bpp", line)
    packed = decimal(raw, "packed", line)
    hflip = decimal(raw, "hflip", line)
    vflip = decimal(raw, "vflip", line)
    if bpp not in {2, 4}:
        raise ValueError(f"line {line}: unsupported bpp {bpp}")
    if packed not in {0, 1} or hflip not in {0, 1} or vflip not in {0, 1}:
        raise ValueError(f"line {line}: invalid packed/flip flag")
    stored_row = decimal(raw, "tile_row", line)
    if stored_row is None or not 0 <= stored_row <= 7:
        raise ValueError(f"line {line}: tile_row must be 0..7")
    byte_count = tile_byte_count(bpp)
    reported_count = decimal(raw, "tile_row_bytes", line)
    if reported_count != byte_count:
        raise ValueError(
            f"line {line}: bpp {bpp} requires {byte_count} row bytes, got {reported_count}"
        )
    row_bytes = []
    for index in range(byte_count):
        value = decimal(raw, f"row_b{index}_value", line)
        if value is None or not 0 <= value <= 0xFF:
            raise ValueError(f"line {line}: row_b{index}_value must be a byte")
        row_bytes.append(value)
    assembled = sum(value << (8 * index) for index, value in enumerate(row_bytes))
    if decimal(raw, "tile_row_value", line) != assembled:
        raise ValueError(f"line {line}: tile_row_value disagrees with row byte evidence")

    tile_bank_enabled = decimal(raw, "tile_bank_enabled", line)
    if tile_bank_enabled not in {0, 1}:
        raise ValueError(f"line {line}: tile_bank_enabled must be 0 or 1")
    use = TileUse(
        layer=layer,
        map_address=int(decimal(raw, "map_address", line)),
        map_value=int(decimal(raw, "map_value", line)),
        map_x=int(decimal(raw, "map_x", line)),
        map_y=int(decimal(raw, "map_y", line)),
        tile_index=int(decimal(raw, "tile_index", line)),
        tile_bank_enabled=tile_bank_enabled,
        palette=int(decimal(raw, "palette", line)),
        bpp=bpp,
        packed=packed,
        hflip=hflip,
        vflip=vflip,
    )
    visual_row = 7 - stored_row if vflip else stored_row
    cell = CellRow(
        line=line,
        cycle=int(decimal(raw, "cycle", line)),
        visual_row=visual_row,
        pixels=decode_pixels(row_bytes, bpp, packed, hflip),
        values=raw,
    )
    return use, cell


def read_occurrences(path: Path) -> list[Occurrence]:
    occurrences: list[Occurrence] = []
    active: dict[tuple[str, int], Occurrence] = {}
    previous_cycle = -1
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        missing = [field for field in BG_OUTPUT_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing bg-cell fields: {', '.join(missing)}")
        for line, raw in enumerate(reader, 2):
            use, cell = parse_cell(raw, line)
            if cell.cycle < previous_cycle:
                raise ValueError(f"line {line}: cycles are not monotonic")
            previous_cycle = cell.cycle
            current = active.get(use.slot)
            if current is not None and (
                current.use != use or cell.visual_row in current.rows
            ):
                occurrences.append(current)
                current = None
            if current is None:
                current = Occurrence(use)
                active[use.slot] = current
            current.rows[cell.visual_row] = cell
            if current.complete:
                occurrences.append(current)
                del active[use.slot]
    occurrences.extend(active.values())
    occurrences.sort(key=lambda item: (item.first_cycle, item.use.layer, item.use.map_address))
    return occurrences


def nonempty(rows: Iterable[CellRow], fields: Iterable[str]) -> set[str]:
    return {
        row.values[field]
        for row in rows
        for field in fields
        if row.values[field] != ""
    }


def integer_values(rows: Iterable[CellRow], fields: Iterable[str]) -> list[int]:
    return sorted(
        {
            int(row.values[field], 10)
            for row in rows
            for field in fields
            if row.values[field] != ""
        }
    )


def occurrence_flags(occurrence: Occurrence) -> set[str]:
    rows = list(occurrence.rows.values())
    flags: set[str] = set()
    if not occurrence.complete:
        flags.add("incomplete")

    contributing_collision = any(
        row.values[field] != "0"
        for row in rows
        for field in ("map_collision", "tile_row_collision")
    )
    raw_collision = any(
        row.values[field] not in {"", "0"}
        for row in rows
        for field in (
            "map_raw_collision",
            "tile0_raw_collision",
            "tile1_raw_collision",
        )
    )
    if contributing_collision:
        flags.add("collision")
    elif raw_collision:
        flags.add("raw_collision")

    if any(row.values["coverage_status"] != "complete_from_reset" for row in rows):
        flags.add("incomplete_coverage")
    if any(row.values["map_scoreboard_status"] != "match" for row in rows):
        flags.add("map_scoreboard_uncertain")
    if any(row.values["row_scoreboard_status"] != "match" for row in rows):
        flags.add("row_scoreboard_uncertain")

    map_summaries = nonempty(rows, ("map_writer_summary", "map_source_summary"))
    row_summaries = nonempty(rows, ("row_writer_summary", "row_source_summary"))
    uncertain_words = ("mixed", "partial", "unobserved", "mismatch", "collision")
    if any(word in value for value in map_summaries | row_summaries for word in uncertain_words):
        flags.add("mixed_provenance")

    map_initiators = nonempty(
        rows, ("map_lo_initiator", "map_hi_initiator")
    )
    row_fields = tuple(
        f"row_b{index}_initiator"
        for index in range(tile_byte_count(occurrence.use.bpp))
    )
    row_initiators = nonempty(rows, row_fields)
    if len(map_initiators) > 1 or len(row_initiators) > 1:
        flags.add("mixed_provenance")
    if len(nonempty(rows, ("row_writer_summary",))) > 1:
        flags.add("mixed_provenance")
    if len(nonempty(rows, ("row_source_summary",))) > 1:
        flags.add("mixed_provenance")

    write_fields = tuple(
        [f"{prefix}_write_cycle" for prefix in MAP_PREFIXES]
        + [
            f"row_b{index}_write_cycle"
            for index in range(tile_byte_count(occurrence.use.bpp))
        ]
    )
    raw_cycles = [
        int(value, 10)
        for row in rows
        for field in ("map_raw_cycle", "contributing_raw_cycles")
        for value in row.values[field].split(";")
        if value
    ]
    first_raw_cycle = min(raw_cycles) if raw_cycles else occurrence.first_cycle
    if any(value >= first_raw_cycle for value in integer_values(rows, write_fields)):
        flags.add("dynamic_during_occurrence")
    return flags


def build_epochs(occurrences: list[Occurrence]) -> list[Epoch]:
    epochs: list[Epoch] = []
    previous: dict[tuple[str, int], tuple[tuple[object, ...], Epoch]] = {}
    for occurrence in occurrences:
        signature = occurrence.provenance_signature()
        prior = previous.get(occurrence.use.slot)
        if occurrence.complete and prior is not None and prior[0] == signature:
            prior[1].occurrences.append(occurrence)
            continue
        epoch = Epoch(occurrence.use, [occurrence])
        epochs.append(epoch)
        previous[occurrence.use.slot] = (signature, epoch)
    epochs.sort(key=lambda item: (item.first_cycle, item.use.layer, item.use.map_address))
    return epochs


def ranges(values: Iterable[int], formatter=str) -> str:
    ordered = sorted(set(values))
    if not ordered:
        return ""
    groups: list[tuple[int, int]] = []
    start = end = ordered[0]
    for value in ordered[1:]:
        if value == end + 1:
            end = value
        else:
            groups.append((start, end))
            start = end = value
    groups.append((start, end))
    return ";".join(
        formatter(start) if start == end else f"{formatter(start)}-{formatter(end)}"
        for start, end in groups
    )


def joined(values: Iterable[str]) -> str:
    return ";".join(sorted(set(value for value in values if value != "")))


def pc_ranges(values: Iterable[int]) -> str:
    return ranges(values, lambda value: f"0x{value:05x}")


def source_ranges(rows: list[CellRow], byte_count: int) -> str:
    grouped: dict[str, list[int]] = {}
    for row in rows:
        for index in range(byte_count):
            space = row.values[f"row_b{index}_source_space"]
            offset = row.values[f"row_b{index}_source_offset"]
            if space and offset:
                grouped.setdefault(space, []).append(int(offset, 10))
    return ";".join(
        f"{space}:{ranges(offsets, lambda value: f'0x{value:06x}')}"
        for space, offsets in sorted(grouped.items())
    )


def tile_iram_ranges(rows: list[CellRow], byte_count: int) -> str:
    addresses = []
    for row in rows:
        start = int(row.values["tile_row_address"], 10)
        addresses.extend(range(start, start + byte_count))
    return ranges(addresses, lambda value: f"0x{value:04x}")


def confidence(flags: set[str]) -> str:
    if "collision" in flags:
        return "collision"
    if "incomplete" in flags:
        return "incomplete"
    if flags & {
        "incomplete_coverage",
        "map_scoreboard_uncertain",
        "row_scoreboard_uncertain",
    }:
        return "uncertain"
    if flags & {"mixed_provenance", "dynamic_during_occurrence"}:
        return "mixed"
    if "raw_collision" in flags:
        return "exact_with_raw_warning"
    return "exact"


def epoch_record(index: int, epoch: Epoch) -> dict[str, str]:
    occurrences = epoch.occurrences
    representative = occurrences[0]
    rows = [row for occurrence in occurrences for row in occurrence.rows.values()]
    flags = set().union(*(occurrence_flags(item) for item in occurrences))
    observed = sorted(set(row.visual_row for row in rows))
    bitmap = representative.bitmap_rows()
    byte_count = tile_byte_count(epoch.use.bpp)
    map_origin_fields = tuple(f"{prefix}_origin_pc" for prefix in MAP_PREFIXES)
    map_id_fields = tuple(f"{prefix}_instruction_id" for prefix in MAP_PREFIXES)
    map_cycle_fields = tuple(f"{prefix}_write_cycle" for prefix in MAP_PREFIXES)
    map_initiator_fields = tuple(f"{prefix}_initiator" for prefix in MAP_PREFIXES)
    row_origin_fields = tuple(f"row_b{i}_origin_pc" for i in range(byte_count))
    row_cycle_fields = tuple(f"row_b{i}_write_cycle" for i in range(byte_count))
    row_initiator_fields = tuple(f"row_b{i}_initiator" for i in range(byte_count))
    row_source_cycle_fields = tuple(
        f"row_b{i}_source_read_cycle" for i in range(byte_count)
    )
    occurrence_cycles = ";".join(
        str(item.first_cycle)
        if item.first_cycle == item.last_cycle
        else f"{item.first_cycle}-{item.last_cycle}"
        for item in occurrences
    )
    mixed = bool(flags & {"mixed_provenance", "dynamic_during_occurrence"})
    return {
        "epoch_index": str(index),
        "layer": epoch.use.layer,
        "tile_index": str(epoch.use.tile_index),
        "tile_bank_enabled": str(epoch.use.tile_bank_enabled),
        "map_address": f"0x{epoch.use.map_address:04x}",
        "map_value": f"0x{epoch.use.map_value:04x}",
        "map_x": str(epoch.use.map_x),
        "map_y": str(epoch.use.map_y),
        "palette": str(epoch.use.palette),
        "bpp": str(epoch.use.bpp),
        "packed": str(epoch.use.packed),
        "hflip": str(epoch.use.hflip),
        "vflip": str(epoch.use.vflip),
        "occurrence_count": str(len(occurrences)),
        "occurrence_cycles": occurrence_cycles,
        "first_cycle": str(epoch.first_cycle),
        "last_cycle": str(epoch.last_cycle),
        "rows_observed": ",".join(map(str, observed)),
        "missing_rows": ",".join(str(value) for value in range(8) if value not in observed),
        "complete": "1" if representative.complete else "0",
        "collision": "1" if "collision" in flags else "0",
        "mixed": "1" if mixed else "0",
        "confidence": confidence(flags),
        "flags": ";".join(sorted(flags)),
        "bitmap_rows": bitmap,
        "bitmap_fingerprint": hashlib.sha256(bitmap.encode("ascii")).hexdigest(),
        "coverage_statuses": joined(row.values["coverage_status"] for row in rows),
        "map_scoreboard_statuses": joined(
            row.values["map_scoreboard_status"] for row in rows
        ),
        "row_scoreboard_statuses": joined(
            row.values["row_scoreboard_status"] for row in rows
        ),
        "map_writer_summaries": joined(
            row.values["map_writer_summary"] for row in rows
        ),
        "map_writer_initiators": joined(
            nonempty(rows, map_initiator_fields)
        ),
        "map_writer_instruction_ids": ranges(integer_values(rows, map_id_fields)),
        "map_writer_origin_pcs": pc_ranges(integer_values(rows, map_origin_fields)),
        "map_write_cycle_range": ranges(integer_values(rows, map_cycle_fields)),
        "row_writer_summaries": joined(
            row.values["row_writer_summary"] for row in rows
        ),
        "row_writer_initiators": joined(
            nonempty(rows, row_initiator_fields)
        ),
        "row_writer_origin_pcs": pc_ranges(integer_values(rows, row_origin_fields)),
        "row_write_cycle_range": ranges(integer_values(rows, row_cycle_fields)),
        "tile_iram_ranges": tile_iram_ranges(rows, byte_count),
        "row_source_summaries": joined(
            row.values["row_source_summary"] for row in rows
        ),
        "row_source_ranges": source_ranges(rows, byte_count),
        "row_source_read_cycle_range": ranges(
            integer_values(rows, row_source_cycle_fields)
        ),
    }


# A dependency-free 3x5 font.  The contact-sheet labels intentionally contain
# only ASCII identifiers and confidence words; they never contain a character
# guess.
FONT = {
    " ": ("000",) * 5,
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("110", "001", "010", "100", "111"),
    "3": ("110", "001", "010", "001", "110"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "110", "001", "110"),
    "6": ("011", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "110"),
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("101", "111", "111", "111", "101"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "?": ("110", "001", "010", "000", "010"),
}


def fill(
    rgb: bytearray,
    width: int,
    x: int,
    y: int,
    w: int,
    h: int,
    color: tuple[int, int, int],
) -> None:
    for py in range(y, y + h):
        if not 0 <= py < len(rgb) // (width * 3):
            continue
        for px in range(x, x + w):
            if 0 <= px < width:
                offset = (py * width + px) * 3
                rgb[offset : offset + 3] = bytes(color)


def text(rgb: bytearray, width: int, x: int, y: int, value: str) -> None:
    for character in value.upper():
        glyph = FONT.get(character, FONT["?"])
        for gy, row in enumerate(glyph):
            for gx, enabled in enumerate(row):
                if enabled == "1":
                    fill(rgb, width, x + gx * 2, y + gy * 2, 2, 2, (20, 20, 20))
        x += 8


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return (
        struct.pack(">I", len(payload))
        + body
        + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    stride = width * 3
    scanlines = b"".join(
        b"\0" + rgb[y * stride : (y + 1) * stride] for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(scanlines, 9))
        + png_chunk(b"IEND", b"")
    )


def short_confidence(value: str) -> str:
    return {
        "exact": "EXACT",
        "exact_with_raw_warning": "RAW WARN",
        "incomplete": "INCOMPLETE",
        "collision": "COLLISION",
        "mixed": "MIXED",
        "uncertain": "UNCERTAIN",
    }[value]


def contact_indices(records: list[dict[str, str]], mode: str) -> list[int]:
    if mode not in CONTACT_MODES:
        raise ValueError(f"unsupported contact-sheet mode {mode!r}")
    if mode == "all":
        return list(range(len(records)))

    exact = [index for index, record in enumerate(records) if record["confidence"] == "exact"]
    if mode == "exact":
        return exact

    # The CSV remains the complete provenance ledger.  This compact visual
    # index keeps one exact epoch for each normalized bitmap so large captures
    # do not bury useful glyph shapes under hundreds of blank or repeated map
    # cells. Prefer ROM-sourced and origin-rich representatives when the same
    # bitmap recurs. E### labels retain the original CSV epoch index.
    unique: list[int] = []
    fingerprint_positions: dict[str, int] = {}

    def evidence_rank(index: int) -> tuple[int, int, int, int, int]:
        record = records[index]
        return (
            int(bool(record["row_source_ranges"])),
            int(bool(record["row_writer_origin_pcs"])),
            int(bool(record["map_writer_origin_pcs"])),
            int(record["occurrence_count"]),
            -int(record["epoch_index"]),
        )

    for index in exact:
        fingerprint = records[index]["bitmap_fingerprint"]
        position = fingerprint_positions.get(fingerprint)
        if position is not None:
            if evidence_rank(index) > evidence_rank(unique[position]):
                unique[position] = index
            continue
        fingerprint_positions[fingerprint] = len(unique)
        unique.append(index)
    return unique


def render_contact_sheet(
    records: list[dict[str, str]], columns: int, contact_mode: str = "all"
) -> bytes:
    if columns <= 0:
        raise ValueError("contact-sheet columns must be positive")
    selected = contact_indices(records, contact_mode)
    cell_width, cell_height = 184, 68
    rows = max(1, math.ceil(len(selected) / columns))
    width, height = columns * cell_width, rows * cell_height
    rgb = bytearray(b"\xff" * (width * height * 3))
    border_colors = {
        "exact": (35, 145, 70),
        "exact_with_raw_warning": (80, 120, 160),
        "incomplete": (220, 145, 20),
        "collision": (190, 35, 35),
        "mixed": (135, 60, 160),
        "uncertain": (100, 100, 100),
    }
    for grid_index, epoch_index in enumerate(selected):
        record = records[epoch_index]
        cell_x = (grid_index % columns) * cell_width
        cell_y = (grid_index // columns) * cell_height
        border = border_colors[record["confidence"]]
        fill(rgb, width, cell_x, cell_y, cell_width, 2, border)
        fill(rgb, width, cell_x, cell_y + cell_height - 2, cell_width, 2, border)
        fill(rgb, width, cell_x, cell_y, 2, cell_height, border)
        fill(rgb, width, cell_x + cell_width - 2, cell_y, 2, cell_height, border)

        bitmap_rows = record["bitmap_rows"].split("/")
        if len(bitmap_rows) != 8 or any(len(row) != 8 for row in bitmap_rows):
            raise ValueError(f"epoch {record['epoch_index']}: invalid bitmap_rows")
        bpp = int(record["bpp"], 10)
        if bpp not in {2, 4}:
            raise ValueError(f"epoch {record['epoch_index']}: invalid bpp {bpp}")
        for visual_row, row in enumerate(bitmap_rows):
            for pixel, value in enumerate(row):
                if value == "?":
                    color = (225, 80, 180) if (visual_row + pixel) % 2 else (255, 210, 240)
                else:
                    try:
                        pixel_value = int(value, 16)
                    except ValueError as error:
                        raise ValueError(
                            f"epoch {record['epoch_index']}: invalid bitmap pixel {value!r}"
                        ) from error
                    maximum = (1 << bpp) - 1
                    if pixel_value > maximum:
                        raise ValueError(
                            f"epoch {record['epoch_index']}: pixel {pixel_value} exceeds "
                            f"{bpp}bpp"
                        )
                    shade = 255 - (pixel_value * 220 // maximum)
                    color = (shade, shade, shade)
                fill(rgb, width, cell_x + 6 + pixel * 6, cell_y + 10 + visual_row * 6, 6, 6, color)
        text(
            rgb,
            width,
            cell_x + 60,
            cell_y + 8,
            f"E{int(record['epoch_index']):03d} S{record['layer'][-1]} "
            f"T{int(record['tile_index']):03X}",
        )
        text(
            rgb,
            width,
            cell_x + 60,
            cell_y + 25,
            f"M{int(record['map_address'], 16):04X} "
            f"X{int(record['map_x']):02d} Y{int(record['map_y']):02d}",
        )
        text(
            rgb,
            width,
            cell_x + 60,
            cell_y + 42,
            f"N{int(record['occurrence_count'])} "
            f"{short_confidence(record['confidence'])}",
        )
    return encode_png(width, height, bytes(rgb))


def build_report_records(source: Path) -> list[dict[str, str]]:
    occurrences = read_occurrences(source)
    epochs = build_epochs(occurrences)
    return [epoch_record(index, epoch) for index, epoch in enumerate(epochs)]


def generate_report(
    source: Path,
    csv_output: Path,
    png_output: Path,
    *,
    columns: int = 4,
    contact_mode: str = "all",
) -> list[dict[str, str]]:
    records = build_report_records(source)
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    with csv_output.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    png_output.parent.mkdir(parents=True, exist_ok=True)
    png_output.write_bytes(render_contact_sheet(records, columns, contact_mode))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="correlate_bg_cells.py CSV output")
    parser.add_argument("--csv", required=True, type=Path, help="candidate report CSV")
    parser.add_argument("--png", required=True, type=Path, help="labeled contact-sheet PNG")
    parser.add_argument(
        "--columns", type=int, default=4, help="contact-sheet columns (default: 4)"
    )
    parser.add_argument(
        "--contact-mode",
        choices=CONTACT_MODES,
        default="all",
        help="all epochs, exact epochs, or one representative per exact bitmap",
    )
    args = parser.parse_args()
    try:
        records = generate_report(
            args.input,
            args.csv,
            args.png,
            columns=args.columns,
            contact_mode=args.contact_mode,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"glyph report: {error}") from error
    print(
        f"glyph report epochs={len(records)} "
        f"contact_epochs={len(contact_indices(records, args.contact_mode))} "
        f"contact_mode={args.contact_mode} csv={args.csv} png={args.png} "
        "character_identity=inferred_never"
    )


if __name__ == "__main__":
    main()
