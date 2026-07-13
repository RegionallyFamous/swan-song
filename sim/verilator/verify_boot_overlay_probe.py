#!/usr/bin/env python3
"""Verify exact mono/color boot-overlay provenance and stimulus bindings."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from verify_trace import FIELDS_V5


ROM_SHA256 = "a1cdf59af325da51e7111b86f89fb5242e10d99141cc7a1c0aedd44fa960c783"


@dataclass(frozen=True)
class Model:
    bios_size: int
    bios_sha256: str
    base: int
    reset_offset: int
    marker: int


MODELS = {
    "mono": Model(
        4096,
        "34b8ce35aafaab0df826b833b6a1e1e9d9b1b6a99eae6f22b867900d51108cd6",
        0xFF000,
        0xFF0,
        0xB007,
    ),
    "color": Model(
        8192,
        "2533e2320302e29e8d47b9ef997e3bbd140882c7625a83deb1a501eef6a3acf2",
        0xFE000,
        0x1FF0,
        0xC007,
    ),
}

# Synchronous word fetches made while executing the generated boot program.
# The data-marker read at 0x100 completes before prefetch resumes at 0x14.
BOOT_PROGRAM_OFFSETS = (
    *range(0x00, 0x14, 2),
    0x100,
    *range(0x14, 0x1A, 2),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def number(value: str, field: str, line: int, maximum: int) -> int:
    if not value:
        raise ValueError(f"line {line}: {field} is empty")
    try:
        result = int(value, 10)
    except ValueError as error:
        raise ValueError(
            f"line {line}: {field} is not a decimal integer: {value!r}"
        ) from error
    if not 0 <= result <= maximum:
        raise ValueError(f"line {line}: {field} is outside 0..{maximum}: {result}")
    return result


def optional_number(value: str, field: str, line: int, maximum: int) -> int | None:
    return None if not value else number(value, field, line, maximum)


def word(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def read_manifest(trace: Path, rom: bytes, bios: bytes) -> None:
    path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {path}: {error}") from error

    expected_events = {
        "cpu": False,
        "bank": False,
        "vram": False,
        "mem": True,
        "bg_cell": False,
    }
    expected = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_size_bytes": trace.stat().st_size,
        "trace_fnv1a64": fnv1a64(trace.read_bytes()),
        "capture_start": "reset_release",
        "capture_completed": True,
        "completed_frames": 1,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "bios_size": len(bios),
        "bios_fnv1a64": fnv1a64(bios),
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": expected_events,
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(
                f"trace manifest {key} mismatch: {manifest.get(key)!r} != {value!r}"
            )
    cycles = manifest.get("capture_cycles")
    if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles <= 0:
        raise ValueError(f"trace manifest capture_cycles is invalid: {cycles!r}")


def signature(row: dict[str, str], line: int) -> tuple[object, ...]:
    if row["event"] != "mem":
        raise ValueError(f"line {line}: unexpected event {row['event']!r}")
    return (
        row["initiator"],
        row["access"],
        number(row["address"], "address", line, 0xFFFFF),
        number(row["value"], "value", line, 0xFFFF),
        number(row["byte_enable"], "byte_enable", line, 3),
        row["space"],
        optional_number(row["mapped_offset"], "mapped_offset", line, 0xFFFFFF),
        optional_number(row["instruction_id"], "instruction_id", line, 0xFFFFFFFF),
        optional_number(row["origin_pc"], "origin_pc", line, 0xFFFFF),
        row["origin_status"],
    )


def expected_prefetch(address: int, value: int, space: str, offset: int) -> tuple[object, ...]:
    return ("cpu", "read", address, value, 0, space, offset, None, None, "unattributed")


def verify(model_name: str, trace: Path, rom_path: Path, bios_path: Path) -> None:
    model = MODELS[model_name]
    rom = rom_path.read_bytes()
    bios = bios_path.read_bytes()
    if len(rom) != 128 * 1024 or sha256(rom) != ROM_SHA256:
        raise ValueError("carrier ROM size/hash mismatch")
    if len(bios) != model.bios_size or sha256(bios) != model.bios_sha256:
        raise ValueError(f"{model_name} test boot image size/hash mismatch")
    if word(bios, 0x100) != model.marker:
        raise ValueError(f"{model_name} test boot marker mismatch")

    read_manifest(trace, rom, bios)

    top_addresses = tuple(range(0xFFFF0, 0x100000, 2))
    top_set = set(top_addresses)
    boot_top: list[tuple[int, tuple[object, ...]]] = []
    cart_top: list[tuple[int, tuple[object, ...]]] = []
    boot_base: list[tuple[int, tuple[object, ...]]] = []
    marker: list[tuple[int, tuple[object, ...]]] = []
    boot_events: list[tuple[int, tuple[object, ...]]] = []
    previous_cycle = -1

    with trace.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(
                "boot-overlay provenance requires the exact v5 trace header; "
                f"got {reader.fieldnames!r}"
            )
        for line, row in enumerate(reader, start=2):
            cycle = number(row["cycle"], "cycle", line, (1 << 64) - 1)
            if cycle <= previous_cycle:
                raise ValueError(
                    f"line {line}: cycle {cycle} does not follow cycle {previous_cycle}"
                )
            previous_cycle = cycle
            sig = signature(row, line)
            address = sig[2]
            space = sig[5]
            if space == "boot_rom":
                boot_events.append((cycle, sig))
            if address in top_set and space == "boot_rom":
                boot_top.append((cycle, sig))
            if address in top_set and space == "cart_rom_linear":
                cart_top.append((cycle, sig))
            if address == model.base and space == "boot_rom":
                boot_base.append((cycle, sig))
            if address == model.base + 0x100 and space == "boot_rom":
                marker.append((cycle, sig))

    expected_boot_top = [
        expected_prefetch(
            address,
            word(bios, model.reset_offset + index * 2),
            "boot_rom",
            model.reset_offset + index * 2,
        )
        for index, address in enumerate(top_addresses)
    ]
    if [sig for _, sig in boot_top] != expected_boot_top:
        raise ValueError(f"unexpected {model_name} boot reset-vector sequence")

    expected_base = expected_prefetch(
        model.base, word(bios, 0), "boot_rom", 0
    )
    if [sig for _, sig in boot_base] != [expected_base]:
        raise ValueError(f"unexpected {model_name} boot byte-zero fetch")

    expected_marker = (
        "cpu",
        "read",
        model.base + 0x100,
        model.marker,
        0,
        "boot_rom",
        0x100,
        5,
        model.base + 6,
        "exact",
    )
    if [sig for _, sig in marker] != [expected_marker]:
        raise ValueError(f"unexpected {model_name} boot marker provenance")

    expected_program = []
    for offset in BOOT_PROGRAM_OFFSETS:
        if offset == 0x100:
            expected_program.append(expected_marker)
        else:
            expected_program.append(
                expected_prefetch(
                    model.base + offset,
                    word(bios, offset),
                    "boot_rom",
                    offset,
                )
            )
    expected_boot = [*expected_boot_top, *expected_program]
    if [sig for _, sig in boot_events] != expected_boot:
        raise ValueError(f"unexpected complete {model_name} boot-ROM sequence")

    rom_reset_offset = len(rom) - 16
    expected_cart_top = [
        expected_prefetch(
            address,
            word(rom, rom_reset_offset + index * 2),
            "cart_rom_linear",
            rom_reset_offset + index * 2,
        )
        for index, address in enumerate(top_addresses)
    ]
    if [sig for _, sig in cart_top] != expected_cart_top:
        raise ValueError(f"unexpected {model_name} post-lockout cartridge sequence")

    if not boot_top or not boot_base or not marker or not cart_top:
        raise ValueError(f"incomplete {model_name} boot-overlay sequence")
    if not (
        boot_top[-1][0] < boot_base[0][0] < marker[0][0] < cart_top[0][0]
    ):
        raise ValueError(f"invalid {model_name} boot-overlay event order")
    if not boot_events or boot_events[-1][0] >= cart_top[0][0]:
        raise ValueError(f"{model_name} boot ROM remained visible after lockout")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=MODELS)
    parser.add_argument("trace", type=Path)
    parser.add_argument("rom", type=Path)
    parser.add_argument("bios", type=Path)
    args = parser.parse_args()
    try:
        verify(args.model, args.trace, args.rom, args.bios)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    print(f"PASS {args.trace} exact {args.model} boot-overlay provenance")


if __name__ == "__main__":
    main()
