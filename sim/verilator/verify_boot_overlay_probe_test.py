#!/usr/bin/env python3
"""Focused negative tests for the generated boot-overlay verifier."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from generate_boot_overlay_probe import generate
from verify_boot_overlay_probe import (
    BOOT_PROGRAM_OFFSETS,
    MODELS,
    fnv1a64,
    verify,
    word,
)
from verify_trace import FIELDS_V5


def mem_row(
    cycle: int,
    address: int,
    value: int,
    space: str,
    mapped_offset: int,
    *,
    instruction_id: int | str = "",
    origin_pc: int | str = "",
    origin_status: str = "unattributed",
) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V5}
    row.update(
        {
            "cycle": cycle,
            "event": "mem",
            "address": address,
            "value": value,
            "initiator": "cpu",
            "access": "read",
            "byte_enable": 0,
            "space": space,
            "mapped_offset": mapped_offset,
            "instruction_id": instruction_id,
            "origin_pc": origin_pc,
            "origin_status": origin_status,
        }
    )
    return row


def expected_rows(model_name: str, rom: bytes, bios: bytes) -> list[dict[str, object]]:
    model = MODELS[model_name]
    rows = [
        mem_row(
            10 + index,
            address,
            word(bios, model.reset_offset + index * 2),
            "boot_rom",
            model.reset_offset + index * 2,
        )
        for index, address in enumerate(range(0xFFFF0, 0x100000, 2))
    ]
    for index, offset in enumerate(BOOT_PROGRAM_OFFSETS):
        if offset == 0x100:
            rows.append(
                mem_row(
                    20 + index,
                    model.base + offset,
                    model.marker,
                    "boot_rom",
                    offset,
                    instruction_id=5,
                    origin_pc=model.base + 6,
                    origin_status="exact",
                )
            )
        else:
            rows.append(
                mem_row(
                    20 + index,
                    model.base + offset,
                    word(bios, offset),
                    "boot_rom",
                    offset,
                )
            )
    reset_offset = len(rom) - 16
    rows.extend(
        mem_row(
            40 + index,
            address,
            word(rom, reset_offset + index * 2),
            "cart_rom_linear",
            reset_offset + index * 2,
        )
        for index, address in enumerate(range(0xFFFF0, 0x100000, 2))
    )
    return rows


def write_case(
    trace: Path,
    rows: list[dict[str, object]],
    rom: bytes,
    bios: bytes,
    *,
    manifest_updates: dict[str, object] | None = None,
) -> None:
    with trace.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    manifest: dict[str, object] = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "trace_file": str(trace),
        "trace_size_bytes": trace.stat().st_size,
        "trace_fnv1a64": fnv1a64(trace.read_bytes()),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": 1000,
        "completed_frames": 1,
        "rom_size": len(rom),
        "rom_fnv1a64": fnv1a64(rom),
        "bios_size": len(bios),
        "bios_fnv1a64": fnv1a64(bios),
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": {
            "cpu": False,
            "bank": False,
            "vram": False,
            "mem": True,
            "bg_cell": False,
        },
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": False,
        "complete_bg_cell_history": False,
    }
    if manifest_updates:
        manifest.update(manifest_updates)
    Path(f"{trace}.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def must_fail(
    model: str,
    trace: Path,
    rom_path: Path,
    bios_path: Path,
    expected: str,
) -> None:
    try:
        verify(model, trace, rom_path, bios_path)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid {model} case passed: {trace.name}")


def exercise_model(
    root: Path, model_name: str, rom_path: Path, bios_path: Path
) -> None:
    rom, bios = rom_path.read_bytes(), bios_path.read_bytes()
    rows = expected_rows(model_name, rom, bios)

    valid = root / f"{model_name}-valid.csv"
    write_case(valid, rows, rom, bios)
    verify(model_name, valid, rom_path, bios_path)

    bad_zero = [dict(row) for row in rows]
    bad_zero[8]["value"] = 0
    path = root / f"{model_name}-bad-zero.csv"
    write_case(path, bad_zero, rom, bios)
    must_fail(model_name, path, rom_path, bios_path, "boot byte-zero fetch")

    bad_marker = [dict(row) for row in rows]
    bad_marker[18]["instruction_id"] = 6
    path = root / f"{model_name}-bad-marker.csv"
    write_case(path, bad_marker, rom, bios)
    must_fail(model_name, path, rom_path, bios_path, "boot marker provenance")

    bad_cart = [dict(row) for row in rows]
    bad_cart[22]["mapped_offset"] = len(rom) - 14
    path = root / f"{model_name}-bad-cart.csv"
    write_case(path, bad_cart, rom, bios)
    must_fail(model_name, path, rom_path, bios_path, "post-lockout cartridge")

    bad_intermediate = [dict(row) for row in rows]
    bad_intermediate[9]["space"] = "cart_rom_linear"
    path = root / f"{model_name}-bad-intermediate.csv"
    write_case(path, bad_intermediate, rom, bios)
    must_fail(model_name, path, rom_path, bios_path, "complete")

    path = root / f"{model_name}-bad-manifest.csv"
    write_case(path, rows, rom, bios, manifest_updates={"bios_fnv1a64": "0" * 16})
    must_fail(model_name, path, rom_path, bios_path, "bios_fnv1a64 mismatch")

    path = root / f"{model_name}-bad-trace-binding.csv"
    write_case(path, rows, rom, bios)
    with path.open("a", encoding="utf-8") as output:
        output.write("\n")
    must_fail(model_name, path, rom_path, bios_path, "trace_size_bytes mismatch")

    corrupt_bios = root / f"{model_name}-corrupt.bin"
    changed = bytearray(bios)
    changed[0x100] ^= 1
    corrupt_bios.write_bytes(changed)
    must_fail(model_name, valid, rom_path, corrupt_bios, "size/hash mismatch")

    corrupt_rom = root / f"{model_name}-corrupt.ws"
    changed = bytearray(rom)
    changed[0x100] ^= 1
    corrupt_rom.write_bytes(changed)
    must_fail(model_name, valid, corrupt_rom, bios_path, "size/hash mismatch")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-boot-overlay-test-") as directory:
        root = Path(directory)
        rom, mono, color = generate(root)
        exercise_model(root, "mono", rom, mono)
        exercise_model(root, "color", rom, color)
    print("PASS generated boot-overlay verifier")


if __name__ == "__main__":
    main()
