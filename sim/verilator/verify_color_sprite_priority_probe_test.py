#!/usr/bin/env python3
"""Positive and mutation tests for the Color sprite-priority verifier."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from verify_color_sprite_priority_probe import (
    BLUE,
    CPU_FINAL_WORDS,
    FIELDS_V6,
    GREEN,
    PAYLOAD,
    PAYLOAD_ADDRESS,
    PAYLOAD_OFFSET,
    ROM_NAME,
    TABLE_GROUP,
    VramFetch,
    expected_sprite_table,
    expected_sprite_tiles,
    expected_stable_frame,
    read_trace,
    verify_cpu_final_words,
    verify_frame,
    verify_gdma,
    verify_manifest,
    verify_rom,
    verify_root,
    verify_sprite_row_sequence,
    verify_vram,
)


REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO / "build/sim/color-sprite-priority-probe"


def must_fail(function, *args, contains: str | None = None) -> None:
    try:
        function(*args)
    except ValueError as error:
        if contains is not None and contains not in str(error):
            raise AssertionError(f"expected {contains!r} in {str(error)!r}") from error
        return
    raise AssertionError(f"mutation passed {function.__name__}")


def synthetic_vram() -> list[VramFetch]:
    result: list[VramFetch] = []
    cycle = 1
    for address, value in expected_sprite_table():
        result.append(VramFetch(cycle, "sprite_table", address, value, 0))
        cycle += 1
    for address, value in expected_sprite_tiles():
        result.append(VramFetch(cycle, "sprite_tile", address, value, 0))
        cycle += 1
    for address in (0x0210, 0x0214, 0x0218):
        result.append(VramFetch(cycle, "screen2_map", address, 0x0003, 0))
        cycle += 1
    for address in range(0x4060, 0x4080, 2):
        result.append(VramFetch(cycle, "screen2_tile", address, 0x1111, 0))
        cycle += 1
    return result


def mem_row(**values: object) -> dict[str, str]:
    row = {field: "" for field in FIELDS_V6}
    row.update({field: str(value) for field, value in values.items()})
    return row


def synthetic_gdma() -> list[tuple[int, dict[str, str]]]:
    rows: list[tuple[int, dict[str, str]]] = []
    cycle = 100
    line = 2
    for word in range(len(PAYLOAD) // 2):
        value = int.from_bytes(PAYLOAD[word * 2 : word * 2 + 2], "little")
        rows.append(
            (
                line,
                mem_row(
                    cycle=cycle,
                    event="mem",
                    address=0xF0200 + word * 2,
                    value=value,
                    initiator="gdma",
                    access="read",
                    byte_enable=3,
                    space="cart_rom_linear",
                    mapped_offset=PAYLOAD_OFFSET + word * 2,
                    origin_status="not_applicable",
                ),
            )
        )
        rows.append(
            (
                line + 1,
                mem_row(
                    cycle=cycle + 1,
                    event="mem",
                    address=PAYLOAD_ADDRESS + word * 2,
                    value=value,
                    initiator="gdma",
                    access="write",
                    byte_enable=3,
                    space="iram",
                    mapped_offset=PAYLOAD_ADDRESS + word * 2,
                    origin_status="not_applicable",
                ),
            )
        )
        cycle += 2
        line += 2
    return rows


def synthetic_cpu_writes() -> list[tuple[int, dict[str, str]]]:
    rows = [
        (
            2,
            mem_row(
                cycle=1,
                event="mem",
                address=0x0214,
                value=0,
                initiator="cpu",
                access="write",
                byte_enable=3,
                space="iram",
                mapped_offset=0x0214,
                instruction_id=1,
                origin_pc=0xF0020,
                origin_status="exact",
            ),
        )
    ]
    for index, (address, value) in enumerate(CPU_FINAL_WORDS.items(), start=2):
        rows.append(
            (
                index + 1,
                mem_row(
                    cycle=index,
                    event="mem",
                    address=address,
                    value=value,
                    initiator="cpu",
                    access="write",
                    byte_enable=3,
                    space="iram",
                    mapped_offset=address,
                    instruction_id=index,
                    origin_pc=0xF0040 + index,
                    origin_status="exact",
                ),
            )
        )
    return rows


def unit_mutations() -> None:
    sprite_rows = [
        (line_y, slot) for line_y in range(64, 72) for slot in range(6)
    ]
    assert verify_sprite_row_sequence(sprite_rows) == 48
    must_fail(
        verify_sprite_row_sequence,
        sprite_rows[:-1],
        contains="exact sprite-row line/slot sequence mismatch",
    )
    reordered_sprite_rows = list(sprite_rows)
    reordered_sprite_rows[0], reordered_sprite_rows[1] = (
        reordered_sprite_rows[1], reordered_sprite_rows[0]
    )
    must_fail(
        verify_sprite_row_sequence,
        reordered_sprite_rows,
        contains="exact sprite-row line/slot sequence mismatch",
    )

    vram = synthetic_vram()
    counts = verify_vram(vram)
    assert counts["sprite_table_words"] == 256
    assert counts["sprite_tile_words"] == 96

    priority_cleared = deepcopy(vram)
    target = next(
        index
        for index, item in enumerate(priority_cleared)
        if item.role == "sprite_table" and item.address == 0x1004
    )
    item = priority_cleared[target]
    priority_cleared[target] = VramFetch(
        item.cycle, item.role, item.address, 0x0202, item.collision
    )
    must_fail(verify_vram, priority_cleared, contains="sprite-table")

    reordered = deepcopy(vram)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    must_fail(verify_vram, reordered, contains="sprite-table")

    wrong_tile = deepcopy(vram)
    target = next(
        index for index, item in enumerate(wrong_tile) if item.role == "sprite_tile"
    )
    item = wrong_tile[target]
    wrong_tile[target] = VramFetch(
        item.cycle, item.role, item.address, item.value ^ 1, item.collision
    )
    must_fail(verify_vram, wrong_tile, contains="sprite-tile")

    missing_tile = deepcopy(vram)
    del missing_tile[target]
    must_fail(verify_vram, missing_tile, contains="sprite-tile")

    collided = deepcopy(vram)
    item = collided[target]
    collided[target] = VramFetch(item.cycle, item.role, item.address, item.value, 1)
    must_fail(verify_vram, collided, contains="collision")

    missing_map = [
        item
        for item in vram
        if not (item.role == "screen2_map" and item.address == 0x0214)
    ]
    must_fail(verify_vram, missing_map, contains="Screen 2 map")

    gdma = synthetic_gdma()
    assert verify_gdma(gdma) == 64
    wrong_value = deepcopy(gdma)
    wrong_value[0][1]["value"] = "1"
    must_fail(verify_gdma, wrong_value, contains="GDMA read word 0")
    wrong_source = deepcopy(gdma)
    wrong_source[0][1]["mapped_offset"] = str(PAYLOAD_OFFSET + 2)
    must_fail(verify_gdma, wrong_source, contains="GDMA read word 0")
    reordered_gdma = deepcopy(gdma)
    reordered_gdma[1], reordered_gdma[2] = reordered_gdma[2], reordered_gdma[1]
    must_fail(verify_gdma, reordered_gdma, contains="GDMA write word 0")
    must_fail(verify_gdma, gdma[:-1], contains="expected 128 GDMA events")

    cpu = synthetic_cpu_writes()
    assert verify_cpu_final_words(cpu) == len(CPU_FINAL_WORDS)
    wrong_descriptor = deepcopy(cpu)
    descriptor = next(row for _, row in wrong_descriptor if row["address"] == str(0x1014))
    descriptor["value"] = str(0x0202)
    must_fail(verify_cpu_final_words, wrong_descriptor, contains="0x1014")
    missing_origin = deepcopy(cpu)
    descriptor = next(row for _, row in missing_origin if row["address"] == str(0x1014))
    descriptor["instruction_id"] = ""
    must_fail(verify_cpu_final_words, missing_origin, contains="0x1014")


def artifact_mutations(root: Path) -> None:
    verify_root(root)
    evidence = read_trace(root / "events.csv")
    verify_vram(evidence.vram)
    verify_gdma(evidence.mem)
    verify_cpu_final_words(evidence.mem)

    with tempfile.TemporaryDirectory(prefix="swansong-color-priority-verifier-") as name:
        temp = Path(name)
        frame = temp / "frame-1.rgb"
        frame.write_bytes(expected_stable_frame())
        verify_frame(frame)

        divergent = bytearray(expected_stable_frame())
        for y in range(64, 72):
            for x in range(80, 88):
                offset = (y * 224 + x) * 3
                divergent[offset : offset + 3] = BLUE
        frame.write_bytes(divergent)
        must_fail(verify_frame, frame, contains="opaque Screen 2 blue")

        damaged = bytearray(expected_stable_frame())
        damaged[(64 * 224 + 80) * 3 + 1] ^= 1
        frame.write_bytes(damaged)
        must_fail(verify_frame, frame, contains="key overlap pixel")

        frame.write_bytes(expected_stable_frame() + b"\x00")
        must_fail(verify_frame, frame, contains="key overlap pixel")

        rom_path = root / "roms" / ROM_NAME
        rom = verify_rom(rom_path)
        copied_rom = temp / ROM_NAME
        copied_rom.write_bytes(rom)
        damaged_rom = bytearray(rom)
        damaged_rom[0x10400] ^= 1
        copied_rom.write_bytes(damaged_rom)
        must_fail(verify_rom, copied_rom, contains="size/hash mismatch")

        copied_root = temp / "color-sprite-priority-probe"
        copied_root.mkdir()
        copied_trace = copied_root / "events.csv"
        shutil.copyfile(root / "events.csv", copied_trace)
        manifest = json.loads(
            Path(f"{root / 'events.csv'}.manifest.json").read_text(encoding="utf-8")
        )
        Path(f"{copied_trace}.manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        verify_manifest(copied_trace, rom)

        wrong_manifest = deepcopy(manifest)
        wrong_manifest["events"]["mem"] = False
        Path(f"{copied_trace}.manifest.json").write_text(
            json.dumps(wrong_manifest), encoding="utf-8"
        )
        must_fail(verify_manifest, copied_trace, rom, contains="events mismatch")

        Path(f"{copied_trace}.manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        copied_trace.write_bytes(copied_trace.read_bytes() + b"\n")
        must_fail(verify_manifest, copied_trace, rom, contains="trace integrity")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    if not args.root.is_dir():
        raise SystemExit(f"verifier test requires a completed capture: {args.root}")
    unit_mutations()
    artifact_mutations(args.root)
    print(
        "PASS Color sprite-priority verifier mutations "
        "controls=blue,green,green,red table_words=256 tile_words=96 gdma_words=64"
    )


if __name__ == "__main__":
    main()
