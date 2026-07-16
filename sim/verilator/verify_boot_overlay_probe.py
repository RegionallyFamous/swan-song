#!/usr/bin/env python3
"""Verify mono/color built-in Open IPL overlay provenance and bindings."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from verify_trace import FIELDS_V5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_open_ipl import make_open_ipl  # noqa: E402


OPEN_IPL_IDENTITY = "open-bootstrap-v3"
RAM_HANDOFF_JUMP = bytes((0xEA, 0x00, 0x04, 0x00, 0x00))


@dataclass(frozen=True)
class Model:
    color: bool
    word_width: bool
    protect_owner_area: bool
    open_ipl_size: int
    open_ipl_sha256: str
    rom_sha256: str
    base: int
    reset_offset: int


MODELS = {
    "mono-word8-owner-writable": Model(
        False, False, False,
        4096,
        "e1b7ee7ebec3f8a33c820ab10cf1b5bf0dca69398ea60af1e927f63bacd2e37b",
        "6e84d7ac0c4e452b8ae979367b12a5c801ac7cfe0003b6be6c7e697230fcafbb",
        0xFF000,
        0xFF0,
    ),
    "mono-word8-owner-protected": Model(
        False, False, True,
        4096,
        "d9cf49878ab45566e34b26bf4cadebdb512c0ed89f75be64c1e54020272bd018",
        "799b0a175dec34c3b8a522df2ec097d4e860ba0e3a478e65e68937bc4c517438",
        0xFF000,
        0xFF0,
    ),
    "mono-word16-owner-writable": Model(
        False, True, False,
        4096,
        "f09f71dd46c17c9ebd82a938e0bbec4dace64874e49e6d53ed6efe3a25277305",
        "0dcd59e6e61600e8b166ade744308a81c23ff72b1d85c89dde35894a488f1911",
        0xFF000,
        0xFF0,
    ),
    "mono-word16-owner-protected": Model(
        False, True, True,
        4096,
        "ccfaa2ec7e667bc4db679d42a63e1e7a5717573381cd63c84854777f2d08c7e1",
        "a1cdf59af325da51e7111b86f89fb5242e10d99141cc7a1c0aedd44fa960c783",
        0xFF000,
        0xFF0,
    ),
    "color-word8-owner-writable": Model(
        True, False, False,
        8192,
        "a7f4453af0d2b624d732111d572679b72cb72fc27498eef98f198e3dbe75d5b2",
        "107380ecccd1c3ecfa8abd222da5733df0dcd1bda35f39a345be7227945bbc0d",
        0xFE000,
        0x1FF0,
    ),
    "color-word8-owner-protected": Model(
        True, False, True,
        8192,
        "d2f5aef0e48bb51dca4f46114a207157f64ee6ac92058555b79117a8ebc474a3",
        "fa512a039edd32d6b41f96cff25d0a5a2857741e144074b6761f84482deea9ef",
        0xFE000,
        0x1FF0,
    ),
    "color-word16-owner-writable": Model(
        True, True, False,
        8192,
        "ef648b0dee18f75549718246f59b2b893388e2012f770ad9f9403f78e224712b",
        "8f00754bf5cdf4b07514610d9a915bedc4a8b13f905b4b5510361cf22681fc8e",
        0xFE000,
        0x1FF0,
    ),
    "color-word16-owner-protected": Model(
        True, True, True,
        8192,
        "164a1d11d3c78aca30f6237c8285fd0aaadae0168db8fcd6ba47f2a4cc452c5b",
        "55c2da573cd4ac6e1a13b04adeea462dbc96fdf317ee3654efc27930cda2fcc3",
        0xFE000,
        0x1FF0,
    ),
}


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


def expected_open_ipl(model: Model) -> bytes:
    image = make_open_ipl(
        color=model.color,
        word_width=model.word_width,
        protect_owner_area=model.protect_owner_area,
    )
    if len(image) != model.open_ipl_size or sha256(image) != model.open_ipl_sha256:
        raise ValueError(
            f"{OPEN_IPL_IDENTITY} generated Open IPL size/hash mismatch"
        )
    return image


def startup_end(open_ipl: bytes) -> int:
    start = len(open_ipl) - 256
    end = open_ipl.rfind(RAM_HANDOFF_JUMP, start, len(open_ipl) - 16)
    if end < start:
        raise ValueError(f"{OPEN_IPL_IDENTITY} RAM handoff jump is missing")
    return end + len(RAM_HANDOFF_JUMP)


def read_manifest(trace: Path, rom: bytes, open_ipl: bytes) -> None:
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
        "open_ipl_size": len(open_ipl),
        "open_ipl_fnv1a64": fnv1a64(open_ipl),
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


def verify(model_name: str, trace: Path, rom_path: Path) -> None:
    model = MODELS[model_name]
    rom = rom_path.read_bytes()
    open_ipl = expected_open_ipl(model)
    if len(rom) != 128 * 1024 or sha256(rom) != model.rom_sha256:
        raise ValueError("carrier ROM size/hash mismatch")

    read_manifest(trace, rom, open_ipl)

    top_addresses = tuple(range(0xFFFF0, 0x100000, 2))
    top_set = set(top_addresses)
    boot_top: list[tuple[int, tuple[object, ...]]] = []
    cart_top: list[tuple[int, tuple[object, ...]]] = []
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
                offset = sig[6]
                if not isinstance(offset, int) or not 0 <= offset < len(open_ipl) - 1:
                    raise ValueError(
                        f"line {line}: invalid {model_name} Open IPL offset {offset!r}"
                    )
                expected = expected_prefetch(
                    model.base + offset,
                    word(open_ipl, offset),
                    "boot_rom",
                    offset,
                )
                if sig != expected:
                    raise ValueError(
                        f"line {line}: unexpected {model_name} Open IPL fetch provenance"
                    )
                boot_events.append((cycle, sig))
            if address in top_set and space == "boot_rom":
                boot_top.append((cycle, sig))
            if address in top_set and space == "cart_rom_linear":
                cart_top.append((cycle, sig))
    expected_boot_top = [
        expected_prefetch(
            address,
            word(open_ipl, model.reset_offset + index * 2),
            "boot_rom",
            model.reset_offset + index * 2,
        )
        for index, address in enumerate(top_addresses)
    ]
    if [sig for _, sig in boot_top] != expected_boot_top:
        raise ValueError(f"unexpected {model_name} boot reset-vector sequence")

    if [sig for _, sig in boot_events[: len(expected_boot_top)]] != expected_boot_top:
        raise ValueError(f"unexpected complete {model_name} reset-vector sequence")
    startup = boot_events[len(expected_boot_top) :]
    startup_offset = len(open_ipl) - 256
    startup_offsets = [sig[6] for _, sig in startup]
    if (
        not startup_offsets
        or startup_offsets[0] != startup_offset
        or any(
            current - previous not in (0, 2)
            for previous, current in zip(startup_offsets, startup_offsets[1:])
        )
    ):
        raise ValueError(f"unexpected {model_name} Open IPL startup fetch sequence")
    if startup_offsets[-1] + 2 < startup_end(open_ipl):
        raise ValueError(f"incomplete {model_name} Open IPL startup fetch sequence")

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

    if not boot_top or not startup or not cart_top:
        raise ValueError(f"incomplete {model_name} boot-overlay sequence")
    if not (boot_top[-1][0] < startup[0][0] < cart_top[0][0]):
        raise ValueError(f"invalid {model_name} boot-overlay event order")
    if not boot_events or boot_events[-1][0] >= cart_top[0][0]:
        raise ValueError(f"{model_name} boot ROM remained visible after lockout")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=MODELS)
    parser.add_argument("trace", type=Path)
    parser.add_argument("rom", type=Path)
    args = parser.parse_args()
    try:
        verify(args.model, args.trace, args.rom)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    print(f"PASS {args.trace} exact {args.model} boot-overlay provenance")


if __name__ == "__main__":
    main()
