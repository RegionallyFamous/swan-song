#!/usr/bin/env python3
"""Positive, structural, and mutation tests for the generated CPU quirk probe."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Callable

from generate_cpu_quirks_probe import (
    FOOTER_OFFSET,
    MARKER,
    MARKER_OFFSET,
    PROGRAM_OFFSET,
    PROGRAM_PC,
    ROM_SIZE,
    expected_results,
    image,
    program,
)
from verify_cpu_quirks_probe import (
    OPEN_IPL_FNV1A64,
    OPEN_IPL_SIZE,
    EXPECTED_EVENTS,
    FIELDS_V5,
    fnv1a64,
    verify,
)


IMAGE_SHA256 = "c0165695a4c236b61addd8cf1a27d1b9e5c0d47a67b1bc29f8e4af85d0b57ece"


def blank_row(cycle: int, event: str) -> dict[str, object]:
    result: dict[str, object] = {field: "" for field in FIELDS_V5}
    result.update(cycle=cycle, event=event)
    return result


def cpu_row(cycle: int, pc: int) -> dict[str, object]:
    result = blank_row(cycle, "cpu")
    result.update(physical_pc=pc, cs=0xF000, ip=pc - PROGRAM_PC)
    return result


def mem_row(
    cycle: int,
    address: int,
    value: int,
    instruction_id: int,
    origin_pc: int,
) -> dict[str, object]:
    result = blank_row(cycle, "mem")
    result.update(
        address=address,
        value=value,
        initiator="cpu",
        access="write",
        byte_enable=3,
        space="iram",
        mapped_offset=address,
        instruction_id=instruction_id,
        origin_pc=origin_pc,
        origin_status="exact",
    )
    return result


def unattributed_read(cycle: int, address: int) -> dict[str, object]:
    result = blank_row(cycle, "mem")
    result.update(
        address=address,
        value=0,
        initiator="cpu",
        access="read",
        byte_enable=0,
        space="iram",
        mapped_offset=address,
        origin_status="unattributed",
    )
    return result


def rom_prefetch(cycle: int, address: int, rom: bytes) -> dict[str, object]:
    offset = PROGRAM_OFFSET + (address - PROGRAM_PC)
    result = blank_row(cycle, "mem")
    result.update(
        address=address,
        value=rom[offset] | (rom[offset + 1] << 8),
        initiator="cpu",
        access="read",
        byte_enable=0,
        space="cart_rom_linear",
        mapped_offset=offset,
        origin_status="unattributed",
    )
    return result


def valid_rows(rom: bytes) -> list[dict[str, object]]:
    built = program()
    first, second = built.salc_origins
    rows = [
        cpu_row(10, first),
        rom_prefetch(40, (first + 1) & ~1, rom),
        cpu_row(73, first + 1),
        cpu_row(100, second),
        rom_prefetch(130, (second + 1) & ~1, rom),
        cpu_row(175, second + 1),
        cpu_row(200, PROGRAM_PC + built.labels["halt"]),
    ]
    cycle = 1000
    for instruction_id, (name, (address, expected, _)) in enumerate(
        expected_results(built).items(), start=1
    ):
        rows.append(
            mem_row(cycle, address, expected, instruction_id, built.result_origins[name])
        )
        cycle += 10
    return sorted(rows, key=lambda row: int(row["cycle"]))


def write_case(
    trace: Path,
    rows: list[dict[str, object]],
    rom: bytes,
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
        "trace_file": str(trace.resolve()),
        "trace_size_bytes": trace.stat().st_size,
        "trace_fnv1a64": fnv1a64(trace.read_bytes()),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": int(rows[-1]["cycle"]) + 100,
        "completed_frames": 1,
        "rom_size": len(rom),
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
    if manifest_updates:
        manifest.update(manifest_updates)
    Path(f"{trace}.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def result_index(rows: list[dict[str, object]], address: int) -> int:
    matches = [
        index
        for index, row in enumerate(rows)
        if row["event"] == "mem" and row["address"] == address
    ]
    if len(matches) != 1:
        raise AssertionError(f"result address {address:#x} is not unique: {matches}")
    return matches[0]


def must_fail(rom: Path, trace: Path, expected: str) -> None:
    try:
        verify(rom, trace)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid CPU quirk probe passed: {trace.name}")


def mutation_case(
    root: Path,
    rom_path: Path,
    rom: bytes,
    rows: list[dict[str, object]],
    name: str,
    mutate: Callable[[list[dict[str, object]]], None],
    expected: str,
) -> None:
    changed = deepcopy(rows)
    mutate(changed)
    trace = root / f"{name}.csv"
    write_case(trace, changed, rom)
    must_fail(rom_path, trace, expected)


def structural_tests() -> None:
    built = program()
    rom = image()
    assert len(rom) == ROM_SIZE
    assert hashlib.sha256(rom).hexdigest() == IMAGE_SHA256
    assert rom[PROGRAM_OFFSET : PROGRAM_OFFSET + len(built.data)] == built.data
    assert rom[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] == MARKER
    assert rom[FOOTER_OFFSET : FOOTER_OFFSET + 5] == b"\xEA\x00\x00\x00\xF0"
    assert int.from_bytes(rom[-2:], "little") == sum(rom[:-2]) & 0xFFFF
    assert built.data[built.labels["aam_zero"] : built.labels["after_aam_zero"]] == b"\xD4\x00"
    assert all(
        built.data[origin - PROGRAM_PC] == 0xD6 for origin in built.salc_origins
    )
    assert expected_results(built)["aam_zero_ip"][1] == built.labels["after_aam_zero"]


def main() -> int:
    structural_tests()
    rom = image()
    rows = valid_rows(rom)
    built = program()
    contracts = expected_results(built)

    with tempfile.TemporaryDirectory(prefix="swansong-cpu-quirks-test-") as name:
        root = Path(name)
        rom_path = root / "probe.ws"
        rom_path.write_bytes(rom)
        valid = root / "valid.csv"
        write_case(valid, rows, rom)
        if verify(rom_path, valid) != (63, 75):
            raise AssertionError("valid SALC completion deltas changed")

        for case, record, bit, expected in (
            ("aam-result", "aam_3c_result", 0x0001, "aam_3c_result value mismatch"),
            ("aam-zf", "aam_30_flags", 0x0040, "aam_30_flags value mismatch"),
            ("aam-pf", "aam_f1_baseff_flags", 0x0004, "aam_f1_baseff_flags value mismatch"),
            ("aam-sf", "aam_f1_baseff_flags", 0x0080, "aam_f1_baseff_flags value mismatch"),
            ("aad-cf", "aad_0880_flags", 0x0001, "aad_0880_flags value mismatch"),
            ("aad-of", "aad_0880_flags", 0x0800, "aad_0880_flags value mismatch"),
            ("aad-sf", "aad_0808_flags", 0x0080, "aad_0808_flags value mismatch"),
            ("aad-af", "aad_0101_base15_flags", 0x0010, "aad_0101_base15_flags value mismatch"),
            ("int-ax", "aam_zero_ax", 0x0001, "aam_zero_ax value mismatch"),
            ("int-ip", "aam_zero_ip", 0x0001, "aam_zero_ip value mismatch"),
            ("int-resume", "aam_zero_resumed", 0x0001, "aam_zero_resumed value mismatch"),
            ("salc-al-ah", "salc_cf0_result", 0x0101, "salc_cf0_result value mismatch"),
            ("salc-flags", "salc_cf0_flags", 0x0400, "salc_cf0_flags value mismatch"),
            ("salc-carry", "salc_cf1_result", 0x0001, "salc_cf1_result value mismatch"),
        ):
            address = contracts[record][0]
            index = result_index(rows, address)
            mutation_case(
                root,
                rom_path,
                rom,
                rows,
                case,
                lambda changed, index=index, bit=bit: changed[index].update(
                    value=int(changed[index]["value"]) ^ bit
                ),
                expected,
            )

        # Every generated result record is independently bound, in addition
        # to the semantic bit mutations above.
        for record, (address, _, mask) in contracts.items():
            index = result_index(rows, address)
            bit = mask & -mask
            mutation_case(
                root,
                rom_path,
                rom,
                rows,
                f"record-{record}",
                lambda changed, index=index, bit=bit: changed[index].update(
                    value=int(changed[index]["value"]) ^ bit
                ),
                f"{record} value mismatch",
            )

        origin_index = result_index(rows, contracts["complete"][0])
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "origin",
            lambda changed: changed[origin_index].update(
                origin_pc=int(changed[origin_index]["origin_pc"]) + 1
            ),
            "complete origin mismatch",
        )

        first_salc = built.salc_origins[0]

        def add_salc_access(changed: list[dict[str, object]]) -> None:
            changed.append(mem_row(50, 0x055A, 0, 999, first_salc))
            changed.sort(key=lambda row: int(row["cycle"]))

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "salc-data-access",
            add_salc_access,
            "attributed data-memory traffic",
        )

        def add_unattributed_salc_access(changed: list[dict[str, object]]) -> None:
            changed.append(unattributed_read(50, 0x055A))
            changed.sort(key=lambda row: int(row["cycle"]))

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "salc-unattributed-data-access",
            add_unattributed_salc_access,
            "SALC interval contains non-prefetch memory traffic",
        )

        def split_salc_completion(changed: list[dict[str, object]]) -> None:
            changed.append(cpu_row(50, PROGRAM_PC + 0x01F0))
            changed.sort(key=lambda row: int(row["cycle"]))

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "salc-completion",
            split_salc_completion,
            "has no adjacent completion",
        )

        def mismatch_prefetch(changed: list[dict[str, object]]) -> None:
            row = next(
                item
                for item in changed
                if item["event"] == "mem"
                and item["origin_status"] == "unattributed"
                and item["space"] == "cart_rom_linear"
            )
            row["mapped_offset"] = 0
            row["value"] = rom[0] | (rom[1] << 8)

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "salc-prefetch-mapping",
            mismatch_prefetch,
            "prefetch mapping mismatch",
        )

        def reuse_instruction_id(changed: list[dict[str, object]]) -> None:
            for row in changed:
                if row["event"] == "mem" and row["origin_status"] == "exact":
                    row["instruction_id"] = 1

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "instruction-id-origin",
            reuse_instruction_id,
            "maps to both",
        )

        short_capture = root / "short-capture.csv"
        write_case(short_capture, rows, rom, manifest_updates={"capture_cycles": 500})
        must_fail(rom_path, short_capture, "outside the certified capture_cycles")

        def add_result_window_write(changed: list[dict[str, object]]) -> None:
            changed.append(mem_row(1300, 0x022D, 0, 999, PROGRAM_PC))

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "extra-result-window",
            add_result_window_write,
            "unexpected write in the result window",
        )

        def change_terminal_pc(changed: list[dict[str, object]]) -> None:
            terminal = next(
                row
                for row in reversed(changed)
                if row["event"] == "cpu"
            )
            terminal["physical_pc"] = int(terminal["physical_pc"]) + 1
            terminal["ip"] = int(terminal["ip"]) + 1

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "terminal-pc",
            change_terminal_pc,
            "terminal CPU PC mismatch",
        )

        mutated_rom = bytearray(rom)
        mutated_rom[PROGRAM_OFFSET] ^= 1
        wrong_rom = root / "wrong.ws"
        wrong_rom.write_bytes(mutated_rom)
        wrong_trace = root / "wrong-rom.csv"
        write_case(wrong_trace, rows, bytes(mutated_rom))
        must_fail(wrong_rom, wrong_trace, "exact generated image")

        extra_manifest = root / "extra-manifest.csv"
        write_case(extra_manifest, rows, rom, manifest_updates={"extra": 1})
        must_fail(rom_path, extra_manifest, "field set mismatch")

        wrong_path = root / "wrong-path.csv"
        write_case(wrong_path, rows, rom, manifest_updates={"trace_file": "elsewhere.csv"})
        must_fail(rom_path, wrong_path, "trace_file mismatch")

        changed_trace = root / "changed-trace.csv"
        write_case(changed_trace, rows, rom)
        changed_trace.write_bytes(changed_trace.read_bytes() + b"\n")
        must_fail(rom_path, changed_trace, "trace_size_bytes mismatch")

    print(
        "PASS generated CPU quirk probe structure and mutations "
        "AAM,AAD,INT0,SALC,origin,no-data-access,ROM,manifest"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
