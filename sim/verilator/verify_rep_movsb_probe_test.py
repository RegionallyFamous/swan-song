#!/usr/bin/env python3
"""Structural, positive, and mutation tests for the REP MOVSB probe."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Callable

from generate_rep_movsb_probe import (
    COMPLETION_ADDRESS,
    COMPLETION_VALUE,
    FOOTER_OFFSET,
    MARKER_OFFSET,
    MARKER_SIZE,
    PROGRAM_OFFSET,
    PROGRAM_PC,
    ROM_SIZE,
    TRANSFERS,
    generate,
    image,
    marker,
    marker_records,
    parse_marker,
    payload,
    program,
)
from verify_rep_movsb_probe import (
    BIOS_FNV1A64,
    BIOS_SIZE,
    EXPECTED_EVENTS,
    fnv1a64,
    verify,
)
from verify_trace import FIELDS_V5


IMAGE_SHA256 = "8b46b5614d1bf8190d58534bcb168d3b14a3d8d8c0e853239051b96e7998511f"
PAYLOAD_SHA256 = (
    "28ac175988250fd910e25712e0ac467a42ebe4c62e9e1f5568b3104d63022584",
    "3126fb5178b630a36a6487b38d88210de2da870a24bb7e542aea80f6ab7ed23e",
)


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
    access: str,
    address: int,
    value: int,
    byte_enable: int,
    space: str,
    mapped_offset: int,
    instruction_id: int | str,
    origin_pc: int | str,
    origin_status: str,
) -> dict[str, object]:
    result = blank_row(cycle, "mem")
    result.update(
        address=address,
        value=value,
        initiator="cpu",
        access=access,
        byte_enable=byte_enable,
        space=space,
        mapped_offset=mapped_offset,
        instruction_id=instruction_id,
        origin_pc=origin_pc,
        origin_status=origin_status,
    )
    return result


def prefetch_row(cycle: int, origin: int) -> dict[str, object]:
    return mem_row(
        cycle,
        "read",
        origin,
        0xA4F3,
        0,
        "cart_rom_linear",
        PROGRAM_OFFSET + (origin - PROGRAM_PC),
        "",
        "",
        "unattributed",
    )


def valid_rows() -> list[dict[str, object]]:
    built = program()
    rows: list[dict[str, object]] = []
    cycle = 10
    for index, (transfer, origin, instruction_id) in enumerate(
        zip(TRANSFERS, built.rep_origins, (101, 202))
    ):
        rows.append(prefetch_row(cycle, origin))
        cycle += 10
        source = payload(index)
        for offset, source_byte in enumerate(source):
            # High read bits are intentionally noncanonical; the memory bus
            # contract places the MOVSB operand in the low byte.
            raw_read = source_byte | (((source_byte ^ 0xA5) & 0xFF) << 8)
            rows.append(
                mem_row(
                    cycle,
                    "read",
                    transfer.source_address + offset,
                    raw_read,
                    0,
                    "cart_rom_linear",
                    transfer.source_offset + offset,
                    instruction_id,
                    origin,
                    "exact",
                )
            )
            rows.append(
                mem_row(
                    cycle + 2,
                    "write",
                    transfer.destination + offset,
                    source_byte,
                    1,
                    "iram",
                    transfer.destination + offset,
                    instruction_id,
                    origin,
                    "exact",
                )
            )
            cycle += 4
        cycle += 10

    rows.append(
        mem_row(
            cycle,
            "write",
            COMPLETION_ADDRESS,
            COMPLETION_VALUE,
            3,
            "iram",
            COMPLETION_ADDRESS,
            303,
            built.completion_origin,
            "exact",
        )
    )
    rows.append(cpu_row(cycle + 10, built.halt_pc))
    return rows


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
        "bios_size": BIOS_SIZE,
        "bios_fnv1a64": BIOS_FNV1A64,
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


def find_row(rows: list[dict[str, object]], **wanted: object) -> int:
    matches = [
        index
        for index, row in enumerate(rows)
        if all(row[field] == value for field, value in wanted.items())
    ]
    if len(matches) != 1:
        raise AssertionError(f"row selection is not unique: {wanted!r} -> {matches!r}")
    return matches[0]


def must_fail(rom: Path, trace: Path, expected: str) -> None:
    try:
        verify(rom, trace)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid REP MOVSB probe passed: {trace.name}")


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


def with_checksum(data: bytearray) -> bytes:
    data[-2:] = (sum(data[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(data)


def structural_tests(root: Path) -> None:
    rom = image()
    built = program()
    assert image() == rom
    assert len(rom) == ROM_SIZE
    assert hashlib.sha256(rom).hexdigest() == IMAGE_SHA256
    assert rom[PROGRAM_OFFSET : PROGRAM_OFFSET + len(built.data)] == built.data
    first_rep = built.rep_origins[0] - PROGRAM_PC
    second_rep = built.rep_origins[1] - PROGRAM_PC
    assert built.data[first_rep : first_rep + 2] == b"\xF3\xA4"
    assert built.data[second_rep : second_rep + 2] == b"\xF3\xA4"
    assert all(origin % 2 == 0 for origin in built.rep_origins)
    assert len(set(built.rep_origins)) == len(TRANSFERS)
    assert all(transfer.length == 2048 for transfer in TRANSFERS)
    assert TRANSFERS[0].source_offset + 2048 <= TRANSFERS[1].source_offset
    assert TRANSFERS[0].destination + 2048 <= TRANSFERS[1].destination
    assert tuple(
        hashlib.sha256(payload(index)).hexdigest() for index in range(2)
    ) == PAYLOAD_SHA256
    encoded = rom[MARKER_OFFSET : MARKER_OFFSET + MARKER_SIZE]
    assert encoded == marker()
    assert parse_marker(encoded) == marker_records()
    assert rom[FOOTER_OFFSET : FOOTER_OFFSET + 5] == b"\xEA\x00\x00\x00\xF0"
    assert len(rom[FOOTER_OFFSET:]) == 16
    assert int.from_bytes(rom[-2:], "little") == sum(rom[:-2]) & 0xFFFF

    first = generate(root / "first")
    second = generate(root / "second")
    assert first.read_bytes() == second.read_bytes() == rom


def main() -> int:
    rom = image()
    rows = valid_rows()
    built = program()

    with tempfile.TemporaryDirectory(prefix="swansong-rep-movsb-probe-test-") as name:
        root = Path(name)
        structural_tests(root)
        rom_path = root / "probe.ws"
        rom_path.write_bytes(rom)
        valid = root / "valid.csv"
        write_case(valid, rows, rom)
        if verify(rom_path, valid) != (101, 202):
            raise AssertionError("valid REP MOVSB instruction IDs changed")

        first = TRANSFERS[0]
        second = TRANSFERS[1]
        first_prefetch = find_row(
            rows, event="mem", address=built.rep_origins[0], origin_status="unattributed"
        )
        first_read = find_row(
            rows, event="mem", access="read", address=first.source_address
        )
        first_write = find_row(
            rows, event="mem", access="write", address=first.destination
        )
        second_read = find_row(
            rows, event="mem", access="read", address=second.source_address
        )
        completion = find_row(
            rows, event="mem", access="write", address=COMPLETION_ADDRESS
        )

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "prefetch",
            lambda changed: changed[first_prefetch].update(value=0xA5F3),
            "prefetch value mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "alternation",
            lambda changed: changed[first_read].update(access="write", byte_enable=1),
            "alternation mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "source-address",
            lambda changed: changed[first_read].update(
                address=int(changed[first_read]["address"]) + 1
            ),
            "read address mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "source-offset",
            lambda changed: changed[first_read].update(
                mapped_offset=int(changed[first_read]["mapped_offset"]) + 1
            ),
            "read mapped_offset mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "first-source-byte",
            lambda changed: changed[first_read].update(
                value=int(changed[first_read]["value"]) ^ 1
            ),
            "low_window ROM byte mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "second-source-byte",
            lambda changed: changed[second_read].update(
                value=int(changed[second_read]["value"]) ^ 1
            ),
            "high_window ROM byte mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "destination",
            lambda changed: changed[first_write].update(
                address=int(changed[first_write]["address"]) + 1,
                mapped_offset=int(changed[first_write]["mapped_offset"]) + 1,
            ),
            "write address mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "write-value",
            lambda changed: changed[first_write].update(
                value=int(changed[first_write]["value"]) ^ 1
            ),
            "IRAM write value mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "write-lane",
            lambda changed: changed[first_write].update(byte_enable=3),
            "write byte_enable mismatch",
        )
        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "split-id",
            lambda changed: changed[first_write].update(instruction_id=102),
            "instruction-chain count mismatch",
        )

        def interleave(changed: list[dict[str, object]]) -> None:
            read_cycle = int(changed[first_read]["cycle"])
            changed.insert(
                first_write,
                mem_row(
                    read_cycle + 1,
                    "read",
                    0xF0100,
                    0,
                    0,
                    "cart_rom_linear",
                    0x10100,
                    "",
                    "",
                    "unattributed",
                ),
            )

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "interleaved",
            interleave,
            "interleaved memory traffic",
        )

        def clobber_destination(changed: list[dict[str, object]]) -> None:
            cycle = int(changed[completion]["cycle"]) - 2
            changed.insert(
                completion,
                mem_row(
                    cycle,
                    "write",
                    first.destination - 1,
                    0xEE,
                    3,
                    "iram",
                    first.destination - 1,
                    404,
                    PROGRAM_PC + 0x0100,
                    "exact",
                ),
            )

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "destination-clobber",
            clobber_destination,
            "destination has an unexpected write",
        )

        def extra_copy(changed: list[dict[str, object]]) -> None:
            cycle = int(changed[completion]["cycle"]) - 4
            changed[completion:completion] = [
                mem_row(
                    cycle,
                    "read",
                    0xF7000,
                    0x55,
                    0,
                    "cart_rom_linear",
                    0x17000,
                    404,
                    PROGRAM_PC + 0x0100,
                    "exact",
                ),
                mem_row(
                    cycle + 2,
                    "write",
                    0x1800,
                    0x55,
                    1,
                    "iram",
                    0x1800,
                    404,
                    PROGRAM_PC + 0x0100,
                    "exact",
                ),
            ]

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "extra-copy",
            extra_copy,
            "unexpected exact CPU ROM-to-IRAM",
        )

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "completion-value",
            lambda changed: changed[completion].update(value=COMPLETION_VALUE ^ 1),
            "completion value mismatch",
        )

        def wrong_terminal(changed: list[dict[str, object]]) -> None:
            changed[-1]["physical_pc"] = built.halt_pc + 1
            changed[-1]["ip"] = built.halt_pc + 1 - PROGRAM_PC

        mutation_case(
            root,
            rom_path,
            rom,
            rows,
            "terminal",
            wrong_terminal,
            "terminal CPU PC mismatch",
        )

        manifest_case = root / "manifest.csv"
        write_case(
            manifest_case,
            rows,
            rom,
            manifest_updates={"complete_memory_history": False},
        )
        must_fail(rom_path, manifest_case, "complete_memory_history mismatch")

        changed_trace = root / "trace-binding.csv"
        write_case(changed_trace, rows, rom)
        changed_trace.write_bytes(changed_trace.read_bytes() + b"\n")
        must_fail(rom_path, changed_trace, "trace_size_bytes mismatch")

        bad_checksum = bytearray(rom)
        bad_checksum[-1] ^= 1
        wrong_checksum = root / "checksum.ws"
        wrong_checksum.write_bytes(bad_checksum)
        must_fail(wrong_checksum, valid, "footer checksum mismatch")

        for case, offset, expected in (
            ("program-rom", PROGRAM_OFFSET, "program bytes mismatch"),
            ("payload-rom", first.source_offset, "low_window payload mismatch"),
            ("marker-rom", MARKER_OFFSET, "marker header mismatch"),
            ("footer-rom", FOOTER_OFFSET + 8, "16-byte footer mismatch"),
        ):
            changed_rom = bytearray(rom)
            changed_rom[offset] ^= 1
            wrong_rom = root / f"{case}.ws"
            wrong_rom.write_bytes(with_checksum(changed_rom))
            must_fail(wrong_rom, valid, expected)

        marker_record = bytearray(rom)
        marker_record[MARKER_OFFSET + MARKER_SIZE - 1] ^= 1
        wrong_record = root / "marker-record.ws"
        wrong_record.write_bytes(with_checksum(marker_record))
        must_fail(wrong_record, valid, "marker transfer records mismatch")

        erased_byte = bytearray(rom)
        erased_byte[0x11000] = 0xFE
        wrong_erased = root / "erased-byte.ws"
        wrong_erased.write_bytes(with_checksum(erased_byte))
        must_fail(wrong_erased, valid, "exact generated image")

    print(
        "PASS generated REP MOVSB probe structure and mutations "
        "2x2048,marker,footer,trace,origins,addresses,values,final-IRAM"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
