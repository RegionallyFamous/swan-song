#!/usr/bin/env python3
"""Verify the licensed Shift-JIS fixture from ROM bytes through visible pixels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from correlate_bg_cells import BYTE_SUFFIXES, correlate
from verify_trace import FIELDS_V5


ROM_SIZE = 128 * 1024
ROM_SHA256 = "b199451af07c3693c7f4329a01710b4616187a73084f7fb791804855ffbe81fa"
FRAME_SHA256 = "99b3a3ed704299c02d4ce7ecedca38746799cee6187285f94caaaf2a67832187"
MESSAGE_OFFSET = 0x1FD52
PACKED_OFFSET = 0x1FDB6
PACKED_PHYSICAL = 0xFFDB6
MAP_WRITE_ORIGIN = 0xFFEF3
MAP_WRITE_IDS = (198, 264, 337, 417, 504, 598)
MESSAGE = bytes.fromhex("93fa967b8cea82a982c88abf00")
BDF_SUBSET = "misaki_gothic_subset.bdf"
BDF_SUBSET_SHA256 = "d4a1a4702e297dbd079119a1221bc9225164ce3f116444b50d158a04d25f58e7"


@dataclass(frozen=True)
class Glyph:
    text: str
    codepoint: int
    sjis: int
    rows: bytes


GLYPHS = (
    Glyph("日", 0x65E5, 0x93FA, bytes.fromhex("7e42427e42427e00")),
    Glyph("本", 0x672C, 0x967B, bytes.fromhex("10fe103854ba1000")),
    Glyph("語", 0x8A9E, 0x8CEA, bytes.fromhex("5cc83cd43ed4dc00")),
    Glyph("か", 0x304B, 0x82A9, bytes.fromhex("2020f42a4a48b000")),
    Glyph("な", 0x306A, 0x82C8, bytes.fromhex("20f422449c261800")),
    Glyph("漢", 0x6F22, 0x8ABF, bytes.fromhex("947eaa3efe88b600")),
)


def packed_glyphs() -> bytes:
    result = bytearray()
    for glyph in GLYPHS:
        for row in glyph.rows:
            result.extend((0, row))
    return bytes(result)


PACKED = packed_glyphs()


def read_bdf_subset(path: Path) -> dict[int, bytes]:
    lines = path.read_text(encoding="ascii").splitlines()
    glyphs: dict[int, bytes] = {}
    index = 0
    while index < len(lines):
        if not lines[index].startswith("STARTCHAR "):
            index += 1
            continue
        block: dict[str, list[str]] = {}
        index += 1
        while index < len(lines) and lines[index] != "ENDCHAR":
            key, _, value = lines[index].partition(" ")
            if key == "BITMAP":
                bitmap = []
                index += 1
                while index < len(lines) and lines[index] != "ENDCHAR":
                    bitmap.append(lines[index])
                    index += 1
                block["BITMAP"] = bitmap
                break
            block[key] = value.split()
            index += 1
        if index >= len(lines) or lines[index] != "ENDCHAR":
            raise ValueError("unterminated BDF glyph")

        try:
            encoding = int(block["ENCODING"][0])
            width, height, x_offset, y_offset = map(int, block["BBX"])
            bitmap_rows = [int(value, 16) for value in block["BITMAP"]]
        except (KeyError, ValueError, IndexError) as error:
            raise ValueError("invalid BDF glyph record") from error
        if height != len(bitmap_rows) or not 0 <= width <= 8:
            raise ValueError(f"invalid BDF bitmap dimensions for U+{encoding:04X}")

        # FONTBOUNDINGBOX is 8x8 at y=-2..5. Place the BBX bitmap into that
        # canvas; BDF rows are MSB-first and x_offset moves them right.
        canvas = [0] * 8
        top_y = y_offset + height - 1
        for source_row, value in enumerate(bitmap_rows):
            y = top_y - source_row
            canvas_row = 5 - y
            if not 0 <= canvas_row < 8 or x_offset < 0:
                raise ValueError(f"unsupported BDF placement for U+{encoding:04X}")
            canvas[canvas_row] = value >> x_offset
        if encoding in glyphs:
            raise ValueError(f"duplicate BDF encoding U+{encoding:04X}")
        glyphs[encoding] = bytes(canvas)
        index += 1
    return glyphs


def decimal(row: dict[str, str], field: str) -> int:
    value = row[field]
    if not value:
        raise ValueError(f"empty {field} on trace line {row.get('_line', '?')}")
    try:
        return int(value, 10)
    except ValueError as error:
        raise ValueError(
            f"invalid {field} on trace line {row.get('_line', '?')}: {value!r}"
        ) from error


def empty(row: dict[str, str], fields: tuple[str, ...], context: str) -> None:
    populated = [field for field in fields if row[field]]
    if populated:
        raise ValueError(f"{context}: unexpected fields: {', '.join(populated)}")


def read_trace(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError("Shift-JIS fixture requires the exact v5 trace header")
        rows = []
        for line, row in enumerate(reader, start=2):
            row["_line"] = str(line)
            rows.append(row)
    return rows


def verify_rom(path: Path) -> bytes:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != ROM_SIZE or digest != ROM_SHA256:
        raise ValueError(f"unexpected fixture ROM: size={len(data)} sha256={digest}")

    if data[-16:-11] != bytes.fromhex("ea0000f4ff") or data[-9] != 1:
        raise ValueError("fixture footer lost its reset vector or Color flag")
    checksum = sum(data[:-2]) & 0xFFFF
    if int.from_bytes(data[-2:], "little") != checksum:
        raise ValueError("fixture footer checksum is invalid")

    message_offsets = [
        offset for offset in range(len(data)) if data.startswith(MESSAGE, offset)
    ]
    packed_offsets = [
        offset for offset in range(len(data)) if data.startswith(PACKED, offset)
    ]
    if message_offsets != [MESSAGE_OFFSET]:
        raise ValueError(f"unexpected Shift-JIS message offsets: {message_offsets}")
    if packed_offsets != [PACKED_OFFSET] or PACKED_OFFSET & 1:
        raise ValueError(f"unexpected/alignment-unsafe packed glyph offsets: {packed_offsets}")

    manifest_message = bytearray()
    for glyph in GLYPHS:
        if len(glyph.text) != 1 or ord(glyph.text) != glyph.codepoint:
            raise AssertionError(f"invalid Unicode manifest entry for {glyph.text!r}")
        encoded = glyph.text.encode("shift_jis")
        if encoded != glyph.sjis.to_bytes(2, "big"):
            raise AssertionError(f"invalid Shift-JIS manifest entry for {glyph.text}")
        manifest_message.extend(encoded)
    manifest_message.append(0)
    if bytes(manifest_message) != MESSAGE:
        raise AssertionError("Shift-JIS message is not derived from the glyph manifest")

    bdf_path = path.parent / BDF_SUBSET
    bdf_digest = hashlib.sha256(bdf_path.read_bytes()).hexdigest()
    if bdf_digest != BDF_SUBSET_SHA256:
        raise ValueError(f"unexpected vendored Misaki BDF subset sha256={bdf_digest}")
    bdf_rows = read_bdf_subset(bdf_path)
    expected_codepoints = {glyph.codepoint for glyph in GLYPHS}
    if set(bdf_rows) != expected_codepoints:
        raise ValueError("vendored Misaki BDF subset has unexpected codepoints")
    for glyph in GLYPHS:
        if bdf_rows[glyph.codepoint] != glyph.rows:
            raise ValueError(f"vendored Misaki BDF rows disagree for {glyph.text}")

    canonical = b"".join(glyph.rows for glyph in GLYPHS)
    if hashlib.sha256(canonical).hexdigest() != (
        "97d6e2c5e3657f6931731db65726e4e9016432d7347db562d420d691b7754c3e"
    ):
        raise AssertionError("internal canonical glyph manifest changed")
    if hashlib.sha256(PACKED).hexdigest() != (
        "d53b19c215d3e3f897a810dcb6181a1f99e7fa500ee0ebc1fbf2661f2811b8f9"
    ):
        raise AssertionError("internal planar packing changed")
    if data[MAP_WRITE_ORIGIN - 0xE0000 : MAP_WRITE_ORIGIN - 0xE0000 + 2] != b"\x89\x01":
        raise ValueError("map-write origin no longer decodes as MOV word [BX+DI],AX")
    return data


def verify_gdma(rows: list[dict[str, str]]) -> None:
    events = [row for row in rows if row["event"] == "mem" and row["initiator"] == "gdma"]
    if len(events) != len(PACKED):
        raise ValueError(f"expected {len(PACKED)} GDMA events, got {len(events)}")

    previous_cycle = -1
    for word_index in range(len(PACKED) // 2):
        read, write = events[word_index * 2 : word_index * 2 + 2]
        value = PACKED[word_index * 2] | (PACKED[word_index * 2 + 1] << 8)
        source_offset = PACKED_OFFSET + word_index * 2
        source_address = PACKED_PHYSICAL + word_index * 2
        destination = 0x2010 + word_index * 2

        expected = (
            (read, "read", source_address, "cart_rom_linear", source_offset),
            (write, "write", destination, "iram", destination),
        )
        for row, access, address, space, mapped_offset in expected:
            context = f"GDMA {access} word {word_index}"
            cycle = decimal(row, "cycle")
            if cycle <= previous_cycle:
                raise ValueError(f"{context}: cycles are not strictly increasing")
            previous_cycle = cycle
            actual = (
                row["access"],
                decimal(row, "address"),
                decimal(row, "value"),
                decimal(row, "byte_enable"),
                row["space"],
                decimal(row, "mapped_offset"),
                row["origin_status"],
            )
            wanted = (access, address, value, 3, space, mapped_offset, "not_applicable")
            if actual != wanted:
                raise ValueError(f"{context}: expected {wanted!r}, got {actual!r}")
            empty(row, ("instruction_id", "origin_pc"), context)


def verify_map_writes(rows: list[dict[str, str]]) -> None:
    addresses = tuple(0x1A14 + index * 2 for index in range(len(GLYPHS)))
    writes = [
        row
        for row in rows
        if row["event"] == "mem"
        and row["initiator"] == "cpu"
        and row["access"] == "write"
        and decimal(row, "address") in addresses
        and decimal(row, "byte_enable") == 3
    ]
    if len(writes) != len(GLYPHS):
        raise ValueError(f"expected six final map writes, got {len(writes)}")

    previous_cycle = -1
    for index, row in enumerate(writes):
        actual = (
            decimal(row, "address"),
            decimal(row, "value"),
            decimal(row, "mapped_offset"),
            decimal(row, "instruction_id"),
            decimal(row, "origin_pc"),
            row["origin_status"],
            row["space"],
        )
        address = addresses[index]
        wanted = (
            address,
            index + 1,
            address,
            MAP_WRITE_IDS[index],
            MAP_WRITE_ORIGIN,
            "exact",
            "iram",
        )
        if actual != wanted:
            raise ValueError(f"map write {index}: expected {wanted!r}, got {actual!r}")
        cycle = decimal(row, "cycle")
        if cycle <= previous_cycle:
            raise ValueError("map writes are not strictly ordered")
        previous_cycle = cycle


def verify_cells(trace: Path) -> None:
    output = io.StringIO()
    correlate(trace, output, require_complete_coverage=True)
    output.seek(0)
    cells = list(csv.DictReader(output))

    for glyph_index, glyph in enumerate(GLYPHS):
        tile = glyph_index + 1
        map_address = 0x1A14 + glyph_index * 2
        selected = [cell for cell in cells if decimal(cell, "map_address") == map_address]
        if len(selected) != 16:
            raise ValueError(
                f"{glyph.text}: expected 16 promoted rows across two frames, got {len(selected)}"
            )

        row_counts = {row: 0 for row in range(8)}
        for cell in selected:
            tile_row = decimal(cell, "tile_row")
            row_counts[tile_row] += 1
            row_byte = glyph.rows[tile_row]
            expected_fields = {
                "bg_layer": "screen1",
                "map_x": str(10 + glyph_index),
                "map_y": "8",
                "map_value": str(tile),
                "tile_bank_enabled": "1",
                "tile_index": str(tile),
                "palette": "0",
                "hflip": "0",
                "vflip": "0",
                "bpp": "2",
                "packed": "0",
                "tile_row_address": str(0x2000 + tile * 16 + tile_row * 2),
                "tile_row_bytes": "2",
                "tile_row_value": str(row_byte << 8),
                "map_collision": "0",
                "tile_row_collision": "0",
                "coverage_status": "complete_from_reset",
                "map_scoreboard_status": "match",
                "map_writer_summary": "cpu_exact",
                "map_source_summary": "cpu_write",
                "row_scoreboard_status": "match",
                "row_writer_summary": "gdma",
                "row_source_summary": "gdma_rom",
            }
            for field, wanted in expected_fields.items():
                if cell[field] != wanted:
                    raise ValueError(
                        f"{glyph.text} row {tile_row}: {field} expected {wanted!r}, "
                        f"got {cell[field]!r}"
                    )

            for lane, value in enumerate((tile, 0)):
                prefix = "map_lo" if lane == 0 else "map_hi"
                expected_map = {
                    f"{prefix}_value": str(value),
                    f"{prefix}_initiator": "cpu",
                    f"{prefix}_instruction_id": str(MAP_WRITE_IDS[glyph_index]),
                    f"{prefix}_origin_pc": str(MAP_WRITE_ORIGIN),
                    f"{prefix}_source_space": "",
                    f"{prefix}_source_offset": "",
                    f"{prefix}_source_read_cycle": "",
                }
                for field, wanted in expected_map.items():
                    if cell[field] != wanted:
                        raise ValueError(f"{glyph.text} row {tile_row}: invalid {field}")

            source_cycles = []
            write_cycles = []
            write_lines = []
            raw_cycle = decimal(cell, "contributing_raw_cycles")
            raw_line = decimal(cell, "contributing_raw_lines")
            selected_raw = (
                "tile0" if decimal(cell, "tile_row_address") & 2 == 0 else "tile1"
            )
            if (
                decimal(cell, f"{selected_raw}_raw_cycle") != raw_cycle
                or decimal(cell, f"{selected_raw}_raw_line") != raw_line
            ):
                raise ValueError(
                    f"{glyph.text} row {tile_row}: contributing raw fetch is not the "
                    "selected 2bpp word"
                )
            for lane, value in enumerate((0, row_byte)):
                prefix = f"row_b{lane}"
                source_offset = PACKED_OFFSET + glyph_index * 16 + tile_row * 2 + lane
                expected_row = {
                    f"{prefix}_value": str(value),
                    f"{prefix}_initiator": "gdma",
                    f"{prefix}_instruction_id": "",
                    f"{prefix}_origin_pc": "",
                    f"{prefix}_source_space": "cart_rom_linear",
                    f"{prefix}_source_offset": str(source_offset),
                }
                for field, wanted in expected_row.items():
                    if cell[field] != wanted:
                        raise ValueError(f"{glyph.text} row {tile_row}: invalid {field}")

                source_cycle = decimal(cell, f"{prefix}_source_read_cycle")
                write_cycle = decimal(cell, f"{prefix}_write_cycle")
                if not source_cycle < write_cycle < raw_cycle < decimal(cell, "cycle"):
                    raise ValueError(f"{glyph.text} row {tile_row}: invalid source/write/fetch order")
                source_cycles.append(source_cycle)
                write_cycles.append(write_cycle)
                write_lines.append(decimal(cell, f"{prefix}_write_line"))

            if (
                len(set(source_cycles)) != 1
                or len(set(write_cycles)) != 1
                or len(set(write_lines)) != 1
            ):
                raise ValueError(f"{glyph.text} row {tile_row}: split GDMA word provenance")

            empty(
                cell,
                tuple(
                    f"row_b{lane}_{suffix}"
                    for lane in (2, 3)
                    for suffix in BYTE_SUFFIXES
                ),
                f"{glyph.text} row {tile_row}",
            )

            map_write_cycle = decimal(cell, "map_lo_write_cycle")
            if (
                cell["map_hi_write_cycle"] != str(map_write_cycle)
                or cell["map_hi_write_line"] != cell["map_lo_write_line"]
            ):
                raise ValueError(f"{glyph.text} row {tile_row}: split map writer")
            if not map_write_cycle < decimal(cell, "map_raw_cycle") < decimal(cell, "cycle"):
                raise ValueError(f"{glyph.text} row {tile_row}: invalid map write/fetch order")

        if set(row_counts.values()) != {2}:
            raise ValueError(f"{glyph.text}: incomplete row repetition {row_counts}")


def expected_frame() -> bytes:
    width, height = 224, 144
    pixels = bytearray(b"\xff\xff\xff" * (width * height))
    for glyph_index, glyph in enumerate(GLYPHS):
        base_x = (10 + glyph_index) * 8
        base_y = 8 * 8
        for y, row in enumerate(glyph.rows):
            for x in range(8):
                if row & (0x80 >> x):
                    offset = ((base_y + y) * width + base_x + x) * 3
                    pixels[offset : offset + 3] = b"\x00\x00\x00"
    return bytes(pixels)


def verify_frame(path: Path) -> None:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    expected = expected_frame()
    if len(data) != len(expected) or digest != FRAME_SHA256:
        raise ValueError(
            f"unexpected visible frame: size={len(data)} sha256={digest}"
        )
    if data != expected:
        mismatch = next(index for index, values in enumerate(zip(data, expected)) if values[0] != values[1])
        pixel = mismatch // 3
        raise ValueError(f"visible pixels differ at ({pixel % 224}, {pixel // 224})")


def verify(rom: Path, trace: Path, frame: Path) -> None:
    verify_rom(rom)
    rows = read_trace(trace)
    verify_gdma(rows)
    verify_map_writes(rows)
    verify_cells(trace)
    verify_frame(frame)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("frame", type=Path, help="raw 224x144 RGB frame")
    args = parser.parse_args()
    try:
        verify(args.rom, args.trace, args.frame)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"Shift-JIS glyph fixture: {error}") from error
    print(
        "PASS Shift-JIS glyph fixture "
        "glyphs=6 gdma_words=48 promoted_rows=96 visible_pixels=exact"
    )


if __name__ == "__main__":
    main()
