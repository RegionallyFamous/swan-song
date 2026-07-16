#!/usr/bin/env python3
"""Verify the paired runtime mapper probe from bound inputs through exact events."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from verify_trace import FIELDS_V5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_open_ipl import make_open_ipl  # noqa: E402


ROM_SIZE = 2 * 1024 * 1024
OPEN_IPL_SIZE = 4096
OPEN_IPL_FNV1A64 = "bcae6dfa69fd72ab"
OPEN_IPL = make_open_ipl(
    color=False, word_width=True, protect_owner_area=True
)
PRESENT_SHA256 = "c65deea47f2e05671c27c07b8d4180e758bfaa94a9f38ca9114dbadf937b083f"
ABSENT_SHA256 = "ffe265c47d79621f76708b9e9b2ed85f8d1a9f5f8c460e11b46fc1b507e575b5"
EXPECTED_EVENTS = {"cpu": False, "bank": True, "vram": False, "mem": True, "bg_cell": False}
EXPECTED_COUNTS = Counter({"mem": 37035, "bank": 5})
EXPECTED_SPACES = Counter(
    {
        "cart_rom_linear": 36917,
        "boot_rom": 83,
        "sram_variant": 5,
        "unmapped": 4,
        "iram": 24,
        "cart_rom0": 1,
        "cart_rom1": 1,
    }
)


@dataclass(frozen=True)
class MemEvent:
    cycle: int
    access: str
    address: int
    value: int
    byte_enable: int
    space: str
    mapped_offset: int | None
    instruction_id: int | None
    origin_pc: int | None
    origin_status: str


@dataclass(frozen=True)
class BankEvent:
    cycle: int
    address: int
    value: int
    instruction_id: int
    origin_pc: int


def open_ipl_word(offset: int) -> int:
    return OPEN_IPL[offset] | (OPEN_IPL[offset + 1] << 8)


_RESET_CYCLES = (21, 33, 45, 57, 69, 81, 93, 129)
BOOT_EVENTS = tuple(
    MemEvent(
        cycle,
        "read",
        0xFFFF0 + index * 2,
        open_ipl_word(0xFF0 + index * 2),
        0,
        "boot_rom",
        0xFF0 + index * 2,
        None,
        None,
        "unattributed",
    )
    for index, cycle in enumerate(_RESET_CYCLES)
) + tuple(
    MemEvent(
        189 + index * 12,
        "read",
        0xFFF00 + index * 2,
        open_ipl_word(0xF00 + index * 2),
        0,
        "boot_rom",
        0xF00 + index * 2,
        None,
        None,
        "unattributed",
    )
    for index in range(75)
)

BANK_EVENTS = (
    BankEvent(2183, 0xC0, 0x01, 52, 0xF0003),
    BankEvent(2279, 0xC1, 0x01, 54, 0xF0007),
    BankEvent(2375, 0xC2, 0x15, 56, 0xF000B),
    BankEvent(2471, 0xC3, 0x16, 58, 0xF000F),
    BankEvent(2663, 0xC1, 0x03, 67, 0xF0029),
)

COMMON_PROBE_EVENTS = (
    MemEvent(2751, "write", 0x04000, 0x3CC3, 3, "unmapped", None, 72, 0xF0036, "exact"),
    MemEvent(2766, "read", 0x04000, 0x9090, 0, "unmapped", None, 73, 0xF0039, "exact"),
    MemEvent(2796, "write", 0x04001, 0x007D, 1, "unmapped", None, 74, 0xF003C, "exact"),
    MemEvent(2826, "read", 0x04001, 0x0090, 0, "unmapped", None, 75, 0xF0041, "exact"),
    MemEvent(2886, "read", 0x21234, 0xA10F, 0, "cart_rom0", 0x151234, 78, 0xF0049, "exact"),
    MemEvent(2946, "read", 0x31234, 0xB20E, 0, "cart_rom1", 0x161234, 81, 0xF0051, "exact"),
    MemEvent(3006, "read", 0x51234, 0xA10F, 0, "cart_rom_linear", 0x151234, 84, 0xF0059, "exact"),
    MemEvent(3066, "read", 0x61234, 0xB20E, 0, "cart_rom_linear", 0x161234, 87, 0xF0061, "exact"),
    MemEvent(3126, "read", 0x71234, 0xC30D, 0, "cart_rom_linear", 0x171234, 90, 0xF0069, "exact"),
)


def sram_events(present: bool) -> tuple[MemEvent, ...]:
    space = "cart_sram" if present else "absent_sram"
    offset = lambda value: value if present else None
    read_word = 0xA55A if present else 0
    read_byte = 0x7E if present else 0
    alias_word = 0x7E5A if present else 0
    return (
        MemEvent(2547, "write", 0x11234, 0xA55A, 3, space, offset(0x11234), 62, 0xF0019, "exact"),
        MemEvent(2562, "read", 0x11234, read_word, 0, space, offset(0x11234), 63, 0xF001C, "exact"),
        MemEvent(2592, "write", 0x11235, 0x007E, 1, space, offset(0x11235), 64, 0xF001F, "exact"),
        MemEvent(2610, "read", 0x11235, read_byte, 0, space, offset(0x11235), 65, 0xF0024, "exact"),
        MemEvent(2694, "read", 0x11234, alias_word, 0, space, offset(0x11234), 68, 0xF002B, "exact"),
    )


def fnv1a64(path: Path) -> str:
    value = 0xCBF29CE484222325
    with path.open("rb") as source:
        while chunk := source.read(16384):
            for byte in chunk:
                value ^= byte
                value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def verify_input(path: Path, size: int, sha256: str, description: str) -> None:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != size or digest != sha256:
        raise ValueError(
            f"unexpected {description}: size={len(data)} sha256={digest}"
        )


def positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def verify_manifest(trace: Path, rom: Path) -> None:
    manifest_path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {manifest_path}: {error}") from error

    expected = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_size_bytes": trace.stat().st_size,
        "trace_fnv1a64": fnv1a64(trace),
        "capture_start": "reset_release",
        "capture_completed": True,
        "rom_size": rom.stat().st_size,
        "rom_fnv1a64": fnv1a64(rom),
        "open_ipl_size": OPEN_IPL_SIZE,
        "open_ipl_fnv1a64": OPEN_IPL_FNV1A64,
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": EXPECTED_EVENTS,
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
    }
    mismatches = [
        f"{field}={manifest.get(field)!r} (expected {wanted!r})"
        for field, wanted in expected.items()
        if manifest.get(field) != wanted
    ]
    if not positive_integer(manifest.get("capture_cycles")):
        mismatches.append("capture_cycles is not a positive integer")
    if manifest.get("completed_frames") != 1:
        mismatches.append(f"completed_frames={manifest.get('completed_frames')!r} (expected 1)")
    if mismatches:
        raise ValueError("trace lacks complete bound authority: " + "; ".join(mismatches))


def integer(row: dict[str, str], field: str, line: int, maximum: int) -> int:
    try:
        value = int(row[field], 10)
    except (KeyError, ValueError) as error:
        raise ValueError(f"line {line}: invalid {field}: {row.get(field)!r}") from error
    if not 0 <= value <= maximum:
        raise ValueError(f"line {line}: {field} is outside 0..{maximum}: {value}")
    return value


def mem_event(row: dict[str, str], line: int) -> MemEvent:
    offset = None if not row["mapped_offset"] else integer(row, "mapped_offset", line, 0xFFFFFF)
    instruction = None if not row["instruction_id"] else integer(row, "instruction_id", line, 0xFFFFFFFF)
    origin_pc = None if not row["origin_pc"] else integer(row, "origin_pc", line, 0xFFFFF)
    return MemEvent(
        integer(row, "cycle", line, (1 << 64) - 1),
        row["access"],
        integer(row, "address", line, 0xFFFFF),
        integer(row, "value", line, 0xFFFF),
        integer(row, "byte_enable", line, 3),
        row["space"],
        offset,
        instruction,
        origin_pc,
        row["origin_status"],
    )


def bank_event(row: dict[str, str], line: int) -> BankEvent:
    if row["origin_status"] != "exact":
        raise ValueError(f"line {line}: bank origin is not exact")
    return BankEvent(
        integer(row, "cycle", line, (1 << 64) - 1),
        integer(row, "address", line, 0xFF),
        integer(row, "value", line, 0xFF),
        integer(row, "instruction_id", line, 0xFFFFFFFF),
        integer(row, "origin_pc", line, 0xFFFFF),
    )


def read_trace(path: Path) -> tuple[list[MemEvent], list[BankEvent]]:
    mem: list[MemEvent] = []
    banks: list[BankEvent] = []
    previous_cycle = -1
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(f"mapper probe requires exact v5 header: {reader.fieldnames!r}")
        for line, row in enumerate(reader, start=2):
            event = row["event"]
            cycle = integer(row, "cycle", line, (1 << 64) - 1)
            if cycle < previous_cycle:
                raise ValueError(f"line {line}: event cycles move backwards")
            previous_cycle = cycle
            if event == "mem":
                unexpected = [
                    field
                    for field in (
                        "physical_pc", "cs", "ip", "role", "fetch_value",
                        "fetch_collision", "bg_layer", "map_address", "map_value",
                        "map_x", "map_y", "tile_bank_enabled", "tile_index",
                        "palette", "hflip", "vflip", "bpp", "packed", "tile_row",
                        "tile_row_address", "tile_row_bytes", "tile_row_value",
                        "map_collision", "tile_row_collision",
                    )
                    if row[field]
                ]
                if unexpected:
                    raise ValueError(f"line {line}: unexpected mem fields: {unexpected}")
                item = mem_event(row, line)
                if row["initiator"] != "cpu":
                    raise ValueError(f"line {line}: mapper probe contains non-CPU memory")
                if item.access not in {"read", "write"}:
                    raise ValueError(f"line {line}: invalid access {item.access!r}")
                if item.access == "read" and item.byte_enable != 0:
                    raise ValueError(f"line {line}: CPU read byte_enable convention is not zero")
                if item.space in {"unmapped", "absent_sram"}:
                    if item.mapped_offset is not None:
                        raise ValueError(f"line {line}: {item.space} has a mapped offset")
                elif item.mapped_offset is None:
                    raise ValueError(f"line {line}: {item.space} lacks a mapped offset")
                if item.origin_status == "exact":
                    if item.instruction_id is None or item.instruction_id == 0 or item.origin_pc is None:
                        raise ValueError(f"line {line}: exact CPU origin is incomplete")
                elif item.origin_status == "unattributed":
                    if item.instruction_id is not None or item.origin_pc is not None:
                        raise ValueError(f"line {line}: unattributed CPU origin is populated")
                else:
                    raise ValueError(f"line {line}: invalid CPU origin {item.origin_status!r}")
                mem.append(item)
            elif event == "bank":
                populated = {
                    "cycle", "event", "address", "value", "instruction_id",
                    "origin_pc", "origin_status",
                }
                unexpected = [field for field in FIELDS_V5 if field not in populated and row[field]]
                if unexpected:
                    raise ValueError(f"line {line}: unexpected bank fields: {unexpected}")
                banks.append(bank_event(row, line))
            else:
                raise ValueError(f"line {line}: unexpected event {event!r}")
    return mem, banks


def footer_events(rom: Path) -> tuple[MemEvent, ...]:
    data = rom.read_bytes()
    base = len(data) - 16
    return tuple(
        MemEvent(
            1917 + index * 12,
            "read",
            0xFFFF0 + index * 2,
            int.from_bytes(
                data[base + index * 2 : base + index * 2 + 2], "little"
            ),
            0,
            "cart_rom_linear",
            ROM_SIZE - 16 + index * 2,
            None,
            None,
            "unattributed",
        )
        for index in range(8)
    )


def verify_open_ipl_events(events: tuple[MemEvent, ...]) -> None:
    if len(events) != 83:
        raise ValueError(f"unexpected Open IPL event count: {len(events)}")
    for item in events:
        if (
            item.access != "read"
            or item.byte_enable != 0
            or item.mapped_offset is None
            or item.address != 0xFF000 + item.mapped_offset
            or item.value != open_ipl_word(item.mapped_offset)
        ):
            raise ValueError(f"unexpected Open IPL event: {item!r}")


def verify_one(rom: Path, trace: Path, present: bool) -> None:
    verify_manifest(trace, rom)
    mem, banks = read_trace(trace)
    counts = Counter({"mem": len(mem), "bank": len(banks)})
    if counts != EXPECTED_COUNTS:
        raise ValueError(f"unexpected event counts: {counts}")

    spaces = Counter(item.space for item in mem)
    variant = "cart_sram" if present else "absent_sram"
    normalized = Counter(spaces)
    normalized["sram_variant"] = normalized.pop(variant, 0)
    if normalized != EXPECTED_SPACES:
        raise ValueError(f"unexpected memory-space counts: {spaces}")

    observed_boot = tuple(item for item in mem if item.space == "boot_rom")
    verify_open_ipl_events(observed_boot)
    if tuple(banks) != BANK_EVENTS:
        raise ValueError(f"unexpected bank sequence: {banks!r}")

    observed_footer = tuple(
        item
        for item in mem
        if item.space == "cart_rom_linear" and 0xFFFF0 <= item.address <= 0xFFFFF
    )
    if observed_footer != footer_events(rom):
        raise ValueError("unexpected cartridge reset-footer sequence")

    wanted_exact = (*sram_events(present), *COMMON_PROBE_EVENTS)
    observed_exact = tuple(
        item
        for item in mem
        if item.origin_status == "exact"
        and item.origin_pc is not None
        and item.origin_pc < 0xFF000
    )
    if observed_exact != wanted_exact:
        raise ValueError(f"unexpected exact-origin memory sequence: {observed_exact!r}")


def verify(present_rom: Path, present_trace: Path, absent_rom: Path, absent_trace: Path) -> None:
    verify_input(present_rom, ROM_SIZE, PRESENT_SHA256, "SRAM-present mapper ROM")
    verify_input(absent_rom, ROM_SIZE, ABSENT_SHA256, "SRAM-absent mapper ROM")
    verify_one(present_rom, present_trace, True)
    verify_one(absent_rom, absent_trace, False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("present_rom", type=Path)
    parser.add_argument("present_trace", type=Path)
    parser.add_argument("absent_rom", type=Path)
    parser.add_argument("absent_trace", type=Path)
    args = parser.parse_args()
    try:
        verify(args.present_rom, args.present_trace, args.absent_rom, args.absent_trace)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"mapper-memory probe: {error}") from error
    print(
        "PASS mapper-memory probe open_ipl=83 bank=5 sram=5 absent=5 "
        "unmapped=4 rom0=1 rom1=1 linear_exact=3 inputs=bound"
    )


if __name__ == "__main__":
    main()
