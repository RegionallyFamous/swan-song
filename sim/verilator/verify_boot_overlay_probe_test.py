#!/usr/bin/env python3
"""Focused tests for the built-in Open IPL boot-overlay verifier."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from generate_boot_overlay_probe import ROM_NAMES, generate
from verify_boot_overlay_probe import (
    MODELS,
    OPEN_IPL_IDENTITY,
    expected_open_ipl,
    fnv1a64,
    startup_end,
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


def expected_rows(model_name: str, rom: bytes) -> list[dict[str, object]]:
    model = MODELS[model_name]
    open_ipl = expected_open_ipl(model)
    rows = [
        mem_row(
            10 + index,
            address,
            word(open_ipl, model.reset_offset + index * 2),
            "boot_rom",
            model.reset_offset + index * 2,
        )
        for index, address in enumerate(range(0xFFFF0, 0x100000, 2))
    ]
    first_startup = len(open_ipl) - 256
    for index, offset in enumerate(
        range(first_startup, (startup_end(open_ipl) + 1) & ~1, 2)
    ):
        rows.append(
            mem_row(
                20 + index,
                model.base + offset,
                word(open_ipl, offset),
                "boot_rom",
                offset,
            )
        )
    reset_offset = len(rom) - 16
    cart_cycle = 20 + len(rows)
    rows.extend(
        mem_row(
            cart_cycle + index,
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
    open_ipl: bytes,
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
        "open_ipl_size": len(open_ipl),
        "open_ipl_fnv1a64": fnv1a64(open_ipl),
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
    expected: str,
) -> None:
    try:
        verify(model, trace, rom_path)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid {model} case passed: {trace.name}")


def exercise_model(root: Path, model_name: str, rom_path: Path) -> None:
    rom = rom_path.read_bytes()
    open_ipl = expected_open_ipl(MODELS[model_name])
    rows = expected_rows(model_name, rom)
    cart_index = len(rows) - 8

    valid = root / f"{model_name}-valid.csv"
    write_case(valid, rows, rom, open_ipl)
    verify(model_name, valid, rom_path)

    bad_startup = [dict(row) for row in rows]
    bad_startup[8]["value"] = int(bad_startup[8]["value"]) ^ 1
    path = root / f"{model_name}-bad-startup.csv"
    write_case(path, bad_startup, rom, open_ipl)
    must_fail(model_name, path, rom_path, "Open IPL fetch provenance")

    bad_provenance = [dict(row) for row in rows]
    bad_provenance[9]["instruction_id"] = 6
    path = root / f"{model_name}-bad-provenance.csv"
    write_case(path, bad_provenance, rom, open_ipl)
    must_fail(model_name, path, rom_path, "Open IPL fetch provenance")

    bad_cart = [dict(row) for row in rows]
    bad_cart[cart_index + 2]["mapped_offset"] = len(rom) - 14
    path = root / f"{model_name}-bad-cart.csv"
    write_case(path, bad_cart, rom, open_ipl)
    must_fail(model_name, path, rom_path, "post-lockout cartridge")

    bad_intermediate = [dict(row) for row in rows]
    bad_intermediate[9]["space"] = "cart_rom_linear"
    path = root / f"{model_name}-bad-intermediate.csv"
    write_case(path, bad_intermediate, rom, open_ipl)
    must_fail(model_name, path, rom_path, "startup fetch sequence")

    path = root / f"{model_name}-bad-manifest.csv"
    write_case(
        path,
        rows,
        rom,
        open_ipl,
        manifest_updates={"open_ipl_fnv1a64": "0" * 16},
    )
    must_fail(model_name, path, rom_path, "open_ipl_fnv1a64 mismatch")

    path = root / f"{model_name}-bad-trace-binding.csv"
    write_case(path, rows, rom, open_ipl)
    with path.open("a", encoding="utf-8") as output:
        output.write("\n")
    must_fail(model_name, path, rom_path, "trace_size_bytes mismatch")

    corrupt_rom = root / f"{model_name}-corrupt.ws"
    changed = bytearray(rom)
    changed[0x100] ^= 1
    corrupt_rom.write_bytes(changed)
    must_fail(model_name, valid, corrupt_rom, "size/hash mismatch")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-boot-overlay-test-") as directory:
        root = Path(directory)
        paths = generate(root)
        if set(paths) != set(MODELS) or {
            variant: path.name for variant, path in paths.items()
        } != ROM_NAMES:
            raise AssertionError("boot-overlay generator/verifier variant matrix drifted")
        for variant, path in paths.items():
            exercise_model(root, variant, path)
        generated = {path.name for path in root.iterdir() if path.is_file()}
        if any(name.endswith(".bin") for name in generated):
            raise AssertionError(f"boot-overlay probe generated a BIOS input: {generated}")
        if OPEN_IPL_IDENTITY != "open-bootstrap-v3":
            raise AssertionError(f"unexpected Open IPL identity: {OPEN_IPL_IDENTITY}")
    print("PASS built-in Open IPL boot-overlay verifier")


if __name__ == "__main__":
    main()
