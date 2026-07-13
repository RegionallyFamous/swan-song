#!/usr/bin/env python3
"""Verify Wonderful medium-model CRT/SRAM behavior through final pixels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from verify_trace import FIELDS_V5


ROM_NAME = "medium_sram_probe.wsc"
ROM_SIZE = 128 * 1024
ROM_SHA256 = "b7f6a4e1e3a73eb4fa615a73f5e9a4cbb8c46a6b5157ade4e1d814c30da034aa"
ROM_FNV1A64 = "f222b8fcc1bef2e7"
FRAME_SHA256 = (
    "b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511",
    "3d4dc04e7d09202bd36b2401600bdb00c4489b89888bd7e4c52520a3e7e0c10b",
)
FILE_SHA256 = {
    "Makefile": "8610b2e241bcea4cf30ef1d38ec546ef2ee15336c45cba07138e860669c33af5",
    "wfconfig.toml": "b4d5bfab3ad942636af54e41a7ff403363de0c0b46cfe6b6221441a662950e78",
    "src/main.c": "171f22aff22e8f2aa8fae780665004ff4e720593e4bc4f1e23fbf748268915a9",
    "LICENSE.target-wswan-examples": (
        "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"
    ),
    "LICENSE.target-wswan-syslibs": (
        "8ee810c7d10a705880f7720051bff071cc801ce7feb4f462b1af43e4f0140661"
    ),
}
MESSAGE = b"MEDIUM-SRAM OK\0"
FAIL_MESSAGE = b"MEDIUM-SRAM FAIL\0"
MESSAGE_OFFSET = 0x1EE05
FAIL_MESSAGE_OFFSET = 0x1EE14

# cycle, address, value, access, byte-enable, offset, instruction ID, origin PC
SRAM_EVENTS = (
    (1848, 0x10012, 0x0000, "write", 1, 0x12, 38, 0xFFF63),
    (1866, 0x10013, 0x0000, "write", 1, 0x13, 38, 0xFFF63),
    (2331, 0x10016, 0x00A5, "write", 1, 0x16, 50, 0xFFF58),
    (2334, 0x10017, 0x005A, "write", 1, 0x17, 50, 0xFFF58),
    (3918, 0x10016, 0x5AA5, "read", 0, 0x16, 88, 0xFF14E),
    (4026, 0x10012, 0x0000, "read", 0, 0x12, 91, 0xFF184),
    (4104, 0x10016, 0xA55A, "write", 3, 0x16, 94, 0xFF18C),
    (4140, 0x10012, 0xC33C, "write", 3, 0x12, 95, 0xFF193),
    (4182, 0x10016, 0xA55A, "read", 0, 0x16, 96, 0xFF19A),
    (4266, 0x10012, 0xC33C, "read", 0, 0x12, 99, 0xFF1A3),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_offset(data: bytes, value: bytes) -> int:
    offsets = [index for index in range(len(data)) if data.startswith(value, index)]
    if len(offsets) != 1:
        raise ValueError(f"expected one {value!r}, found offsets {offsets}")
    return offsets[0]


def verify_fixture(directory: Path) -> bytes:
    for relative, wanted in FILE_SHA256.items():
        actual = sha256((directory / relative).read_bytes())
        if actual != wanted:
            raise ValueError(f"fixture source {relative} sha256 {actual} != {wanted}")

    data = (directory / ROM_NAME).read_bytes()
    digest = sha256(data)
    if len(data) != ROM_SIZE or digest != ROM_SHA256:
        raise ValueError(f"unexpected ROM size/hash: {len(data)} {digest}")
    if data[-16:-11] != bytes.fromhex("ea0000f3ff"):
        raise ValueError("ROM reset vector is not the pinned far jump")
    if data[-9] != 1 or data[-5] != 2:
        raise ValueError("ROM is not Color + SRAM type 02")
    if int.from_bytes(data[-2:], "little") != sum(data[:-2]) & 0xFFFF:
        raise ValueError("ROM footer checksum is invalid")
    if unique_offset(data, MESSAGE) != MESSAGE_OFFSET:
        raise ValueError("success message moved")
    if unique_offset(data, FAIL_MESSAGE) != FAIL_MESSAGE_OFFSET:
        raise ValueError("failure message moved")
    if unique_offset(data, bytes.fromhex("b800108ec0")) != 0x1FF31:
        raise ValueError("CRT no longer selects SRAM segment 1000h")
    if unique_offset(data, bytes.fromhex("ea0b0014ff")) != 0x1FF86:
        raise ValueError("CRT no longer far-jumps to pinned main entry")
    return data


def integer(row: dict[str, str], field: str) -> int:
    try:
        return int(row[field], 10)
    except ValueError as error:
        raise ValueError(f"invalid {field}: {row[field]!r}") from error


def verify_manifest(trace: Path) -> None:
    manifest_path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest: {error}") from error
    expected = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "capture_start": "reset_release",
        "capture_completed": True,
        "completed_frames": 2,
        "rom_size": ROM_SIZE,
        "rom_fnv1a64": ROM_FNV1A64,
        "bios_size": 8192,
        "bios_fnv1a64": "bde71f09ac34c168",
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": {
            "cpu": True,
            "bank": False,
            "vram": False,
            "mem": True,
            "bg_cell": True,
        },
        "memory_filters_active": True,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": True,
    }
    for field, wanted in expected.items():
        if manifest.get(field) != wanted:
            raise ValueError(f"manifest {field}: {manifest.get(field)!r} != {wanted!r}")
    if manifest.get("trace_size_bytes") != trace.stat().st_size:
        raise ValueError("manifest trace size mismatch")


def read_trace(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError("medium-SRAM fixture requires exact v5 trace fields")
        return list(reader)


def verify_sram(rows: list[dict[str, str]]) -> None:
    events = [row for row in rows if row["event"] == "mem"]
    if len(events) != len(SRAM_EVENTS):
        raise ValueError(f"expected {len(SRAM_EVENTS)} SRAM rows, got {len(events)}")
    populated = {
        "cycle", "event", "address", "value", "initiator", "access",
        "byte_enable", "space", "mapped_offset", "instruction_id",
        "origin_pc", "origin_status",
    }
    for index, (row, wanted) in enumerate(zip(events, SRAM_EVENTS), start=1):
        unexpected = [field for field in FIELDS_V5 if field not in populated and row[field]]
        if unexpected:
            raise ValueError(f"SRAM row {index} has unexpected fields {unexpected}")
        actual = (
            integer(row, "cycle"), integer(row, "address"), integer(row, "value"),
            row["access"], integer(row, "byte_enable"), integer(row, "mapped_offset"),
            integer(row, "instruction_id"), integer(row, "origin_pc"),
        )
        if actual != wanted:
            raise ValueError(f"SRAM row {index}: {actual!r} != {wanted!r}")
        if (row["initiator"], row["space"], row["origin_status"]) != (
            "cpu", "cart_sram", "exact"
        ):
            raise ValueError(f"SRAM row {index} lost CPU/cart-SRAM/exact provenance")


def verify_cpu(rows: list[dict[str, str]]) -> None:
    pcs = [integer(row, "physical_pc") for row in rows if row["event"] == "cpu"]
    required = (0xFFF30, 0xFFF86, 0xFF14B, 0xFF184, 0xFF1AC, 0xFF1BE, 0xFF1C3, 0xFF180)
    cursor = -1
    for pc in required:
        try:
            cursor = pcs.index(pc, cursor + 1)
        except ValueError as error:
            raise ValueError(f"CPU did not reach ordered PC {pc:05x}") from error
    for failure_pc in (0xFF157, 0xFF165, 0xFF177):
        if failure_pc in pcs:
            raise ValueError(f"CPU entered failure path at {failure_pc:05x}")
    if len(pcs) != 129 or pcs[-1] != 0xFF180:
        raise ValueError("unexpected filtered CPU path or terminal HLT")


def verify_cells(rows: list[dict[str, str]]) -> None:
    expected = tuple(byte + 0x180 for byte in MESSAGE[:-1])
    counts: Counter[int] = Counter()
    values: dict[int, set[int]] = defaultdict(set)
    for row in rows:
        if row["event"] != "bg_cell":
            continue
        x = integer(row, "map_x")
        y = integer(row, "map_y")
        value = integer(row, "map_value")
        if y == 0 and 0 <= x <= 15 and value:
            counts[x] += 1
            values[x].add(value)
    if counts != Counter({x: 8 for x in range(len(expected))}):
        raise ValueError(f"unexpected success-text cell counts: {counts}")
    if values != {x: {value} for x, value in enumerate(expected)}:
        raise ValueError(f"unexpected success-text cell values: {values}")


def verify_frames(paths: tuple[Path, Path]) -> None:
    for index, (path, wanted) in enumerate(zip(paths, FRAME_SHA256)):
        data = path.read_bytes()
        digest = sha256(data)
        if len(data) != 224 * 144 * 3 or digest != wanted:
            raise ValueError(f"frame {index} size/hash mismatch: {len(data)} {digest}")


def verify(directory: Path, trace: Path, frames: tuple[Path, Path]) -> None:
    verify_fixture(directory)
    verify_manifest(trace)
    rows = read_trace(trace)
    counts = Counter(row["event"] for row in rows)
    if counts != Counter(cpu=129, mem=10, bg_cell=4153):
        raise ValueError(f"unexpected trace event counts: {counts}")
    verify_sram(rows)
    verify_cpu(rows)
    verify_cells(rows)
    verify_frames(frames)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("frame0", type=Path)
    parser.add_argument("frame1", type=Path)
    args = parser.parse_args()
    try:
        verify(args.fixture, args.trace, (args.frame0, args.frame1))
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"Wonderful medium-SRAM fixture: {error}") from error
    print(
        "PASS Wonderful medium-sram CRT=.data+.bss far-main+ROM-data "
        "SRAM=5aa5/0000->a55a/c33c text='MEDIUM-SRAM OK' HLT frame=bound"
    )


if __name__ == "__main__":
    main()
