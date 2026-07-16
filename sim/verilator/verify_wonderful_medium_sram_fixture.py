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
ROM_SHA256 = "ae3ea85cc6b5c3b32e1fac23d37dd4fce8ccb38ec2fcd80d4b80b868e59dc4b7"
ROM_FNV1A64 = "2f63161f20bfa9fb"
FRAME_SHA256 = (
    "3b5d5bb2e0837d1687e7d5fbfcdff8c3b7ce8c27a12923b9fb98b53728cc89b1",
    "3d4dc04e7d09202bd36b2401600bdb00c4489b89888bd7e4c52520a3e7e0c10b",
)
FILE_SHA256 = {
    "Makefile": "5026b50f2c9683147711e7be724f1b466eeb46d222f9ca6b541841c78fa3cb20",
    "wfconfig.toml": "b4d5bfab3ad942636af54e41a7ff403363de0c0b46cfe6b6221441a662950e78",
    "src/crt0_color.s": "7a9111e8195d651c97b9b160b089fa2bcd093deac1819cf2dc5a547ad1d1af6d",
    "src/main.c": "6d12112f0ccdfaf50c049896f93f99dc08c9796f5492f885a6188d2fa1a672f2",
    "LICENSE.target-wswan-examples": (
        "a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499"
    ),
    "LICENSE.target-wswan-syslibs": (
        "8ee810c7d10a705880f7720051bff071cc801ce7feb4f462b1af43e4f0140661"
    ),
}
MESSAGE = b"MEDIUM-SRAM OK\0"
FAIL_MESSAGE = b"MEDIUM-SRAM FAIL\0"
MESSAGE_OFFSET = 0x1EDC3
FAIL_MESSAGE_OFFSET = 0x1EDD2

# cycle, address, value, access, byte-enable, offset, instruction ID, origin PC
SRAM_EVENTS = (
    (4344, 0x10012, 0x0000, "write", 1, 0x12, 105, 0xFFF64),
    (4362, 0x10013, 0x0000, "write", 1, 0x13, 105, 0xFFF64),
    (4779, 0x10014, 0x00A5, "write", 1, 0x14, 117, 0xFFF59),
    (4782, 0x10015, 0x005A, "write", 1, 0x15, 117, 0xFFF59),
    (6954, 0x10014, 0x5AA5, "read", 0, 0x14, 171, 0xFF13E),
    (7062, 0x10012, 0x0000, "read", 0, 0x12, 174, 0xFF174),
    (7140, 0x10014, 0xA55A, "write", 3, 0x14, 177, 0xFF17C),
    (7176, 0x10012, 0xC33C, "write", 3, 0x12, 178, 0xFF183),
    (7218, 0x10014, 0xA55A, "read", 0, 0x14, 179, 0xFF18A),
    (7302, 0x10012, 0xC33C, "read", 0, 0x12, 182, 0xFF193),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_offset(data: bytes, value: bytes) -> int:
    offsets = [index for index in range(len(data)) if data.startswith(value, index)]
    if len(offsets) != 1:
        raise ValueError(f"expected one {value!r}, found offsets {offsets}")
    return offsets[0]


def verify_source_contract(source: str) -> None:
    """Require Color mode before the fixture observes or displays test state."""
    main_marker = "void main(void) {"
    try:
        body = source[source.index(main_marker) + len(main_marker):]
    except ValueError as error:
        raise ValueError("fixture source lost main entry") from error

    mode = "bool valid = ws_system_set_mode(WS_MODE_COLOR);"
    if not body.lstrip().startswith(mode):
        raise ValueError("main must enable Color mode as its first source-level statement")
    mode_offset = body.index(mode)
    ordered_after_mode = (
        "valid = valid && initialized_word == 0x5AA5 && zero_word == 0;",
        "initialized_word = 0xA55A;",
        "zero_word = 0xC33C;",
        "wsx_console_init_default(&wse_screen1);",
        "ws_display_set_control(WS_DISPLAY_CTRL_SCR1_ENABLE);",
    )
    cursor = mode_offset
    for statement in ordered_after_mode:
        offset = body.find(statement, cursor + 1)
        if offset < 0:
            raise ValueError(f"fixture source lost ordered statement {statement!r}")
        cursor = offset


def verify_startup_contract(source: str) -> None:
    """Bind the physical-Color guard and pre-stack upper-IRAM enable."""
    try:
        prefix = source[source.index("_start:"):source.index("_start_parse_data_block:")]
        finish = source[
            source.index("_start_finish_data_block:"):source.index("_start_run_array:")
        ]
    except ValueError as error:
        raise ValueError("fixture CRT lost pinned startup labels") from error

    ordered = (
        "in\tal, 0xA0",
        "test\tal, 0x02",
        "jnz\t_start_enable_color",
        "_start_requires_color:",
        "hlt",
        "_start_enable_color:",
        "in\tal, 0x60",
        "and\tal, 0x1F",
        "or\tal, 0x80",
        "out\t0x60, al",
        'mov\tsp, offset "__wf_heap_top"',
    )
    cursor = -1
    for statement in ordered:
        offset = prefix.find(statement, cursor + 1)
        if offset < 0:
            raise ValueError(f"fixture CRT lost ordered startup statement {statement!r}")
        cursor = offset
    if "push" in prefix:
        raise ValueError("fixture CRT touches the stack before enabling upper Color IRAM")
    if "0x60" in finish or "out\t0x60" in finish:
        raise ValueError("fixture CRT changes Color mode after selecting its high stack")
    if "push\tes" not in finish or finish.index("push\tes") > finish.index("call _start_run_array"):
        raise ValueError("fixture CRT lost its pinned first stack operation")


def verify_build_contract(makefile: str) -> None:
    required = (
        "CRT0_LOCAL\t:= src/crt0_color.s",
        "CRT0_OBJ\t:= $(BUILDDIR)/$(CRT0_LOCAL).o",
        "$(ELF_STAGE1): $(OBJS) $(CRT0_OBJ)",
        "$(CC) -r -o $(ELF_STAGE1) $(CRT0_OBJ) $(OBJS) $(LDFLAGS)",
    )
    for statement in required:
        if statement not in makefile:
            raise ValueError(f"fixture Makefile lost local CRT binding {statement!r}")
    if "$(WF_CRT0)" in makefile:
        raise ValueError("fixture Makefile reverted to the incompatible stock CRT")


def verify_fixture(directory: Path) -> bytes:
    for relative, wanted in FILE_SHA256.items():
        actual = sha256((directory / relative).read_bytes())
        if actual != wanted:
            raise ValueError(f"fixture source {relative} sha256 {actual} != {wanted}")
    verify_source_contract((directory / "src/main.c").read_text(encoding="utf-8"))
    verify_startup_contract((directory / "src/crt0_color.s").read_text(encoding="utf-8"))
    verify_build_contract((directory / "Makefile").read_text(encoding="utf-8"))

    data = (directory / ROM_NAME).read_bytes()
    digest = sha256(data)
    if len(data) != ROM_SIZE or digest != ROM_SHA256:
        raise ValueError(f"unexpected ROM size/hash: {len(data)} {digest}")
    if data[-16:-11] != bytes.fromhex("ea0000f2ff"):
        raise ValueError("ROM reset vector is not the pinned far jump")
    if data[-9] != 1 or data[-5] != 2:
        raise ValueError("ROM is not Color + SRAM type 02")
    if int.from_bytes(data[-2:], "little") != sum(data[:-2]) & 0xFFFF:
        raise ValueError("ROM footer checksum is invalid")
    if unique_offset(data, MESSAGE) != MESSAGE_OFFSET:
        raise ValueError("success message moved")
    if unique_offset(data, FAIL_MESSAGE) != FAIL_MESSAGE_OFFSET:
        raise ValueError("failure message moved")
    guard_offset = unique_offset(data, bytes.fromhex("e4a0a8027503f4ebfd"))
    enable_offset = unique_offset(data, bytes.fromhex("e460241f0c80e660"))
    stack_offset = 0x1FF3F
    push_offset = 0x1FF71
    if data[stack_offset:stack_offset + 3] != bytes.fromhex("bc0080"):
        raise ValueError("CRT no longer selects SP=8000h after enabling Color IRAM")
    if data[push_offset:push_offset + 2] != bytes.fromhex("061f"):
        raise ValueError("CRT first push/pop moved")
    if (guard_offset, enable_offset, stack_offset, push_offset) != (
        0x1FF21, 0x1FF2A, 0x1FF3F, 0x1FF71
    ):
        raise ValueError("CRT Color guard/enable/high-stack/first-push sequence moved")
    if not guard_offset < enable_offset < stack_offset < push_offset:
        raise ValueError("CRT touches its high stack before enabling upper Color IRAM")
    if bytes.fromhex("e460") in data[enable_offset + 8:push_offset]:
        raise ValueError("CRT clears Color mode before its first stack operation")
    if unique_offset(data, bytes.fromhex("b800108ec0")) != 0x1FF32:
        raise ValueError("CRT no longer selects SRAM segment 1000h")
    if unique_offset(data, bytes.fromhex("ea000013ff")) != 0x1FF81:
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
        "open_ipl_size": 8192,
        "open_ipl_fnv1a64": "de968891eff736c1",
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
    required = (
        0xFFF20, 0xFFF21, 0xFFF2A, 0xFFF3F, 0xFFF71, 0xFFF81,
        0xFF130, 0xFF174, 0xFF19C, 0xFF1AE, 0xFF1B3, 0xFF170,
    )
    cursor = -1
    for pc in required:
        try:
            cursor = pcs.index(pc, cursor + 1)
        except ValueError as error:
            raise ValueError(f"CPU did not reach ordered PC {pc:05x}") from error
    for failure_pc in (0xFF147, 0xFF155, 0xFF167):
        if failure_pc in pcs:
            raise ValueError(f"CPU entered failure path at {failure_pc:05x}")
    if len(pcs) != 180 or pcs[-1] != 0xFF170:
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
    if counts != Counter(cpu=180, mem=10, bg_cell=4123):
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
