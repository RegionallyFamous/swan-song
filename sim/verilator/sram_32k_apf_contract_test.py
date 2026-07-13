#!/usr/bin/env python3
"""Lock 32 KiB type-01 sizing across RTL, save states, and Pocket APF."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_BYTES = {
    0x01: 32 * 1024,
    0x02: 32 * 1024,
    0x03: 128 * 1024,
    0x04: 256 * 1024,
    0x05: 512 * 1024,
}


def parse_memory_masks(source: str) -> dict[int, int]:
    return {
        int(ram_type, 16): int(mask, 16)
        for mask, ram_type in re.findall(
            r'x"([0-9A-Fa-f]{6})"\s+when\s+ramtype\s*=\s*x"([0-9A-Fa-f]{2})"',
            source,
        )
    }


def parse_savestate_sizes(source: str) -> dict[int, int]:
    return {
        int(ram_type, 16): int(size, 10)
        for ram_type, size in re.findall(
            r'when\s+x"([0-9A-Fa-f]{2})"\s*=>\s*savetypes\(2\)\s*<=\s*(\d+)',
            source,
        )
    }


def parse_pocket_byte_sizes(source: str) -> dict[int, int]:
    return {
        int(ram_type, 16): int(byte_size, 16)
        for ram_type, byte_size in re.findall(
            r"if\s*\(ramtype\s*==\s*8'h([0-9A-Fa-f]{2})\)\s*"
            r"save_size_bytes\s*=\s*20'h([0-9A-Fa-f]{1,5})",
            source,
        )
    }


def verify_contract(
    memorymux: str,
    savestates: str,
    wonderswan: str,
    core_top: str,
    data_definition: dict[str, object],
) -> None:
    masks = parse_memory_masks(memorymux)
    save_payloads = parse_savestate_sizes(savestates)
    pocket_sizes = parse_pocket_byte_sizes(wonderswan)
    for ram_type, byte_size in EXPECTED_BYTES.items():
        wanted_mask = byte_size - 1
        if masks.get(ram_type) != wanted_mask:
            raise ValueError(
                f"ramtype {ram_type:02x} mapper mask "
                f"{masks.get(ram_type)!r} != {wanted_mask}"
            )
        if save_payloads.get(ram_type) != byte_size:
            raise ValueError(
                f"ramtype {ram_type:02x} save-state payload "
                f"{save_payloads.get(ram_type)!r} != {byte_size}"
            )
        if pocket_sizes.get(ram_type) != byte_size:
            raise ValueError(
                f"ramtype {ram_type:02x} Pocket bytes "
                f"{pocket_sizes.get(ram_type)!r} != {byte_size}"
            )

    # The fourth JSON data slot is the runtime-sized nonvolatile Save slot.
    # core_top writes the exact base payload plus the conditional 12-byte RTC
    # trailer to that exact table entry.
    try:
        data = data_definition["data"]  # type: ignore[index]
        if data["magic"] != "APF_VER_1":  # type: ignore[index]
            raise ValueError("APF data magic mismatch")
        slots = data["data_slots"]  # type: ignore[index]
        save = slots[3]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("APF Save slot is missing") from error
    expected_save = {
        "name": "Save",
        "id": 11,
        "required": False,
        "parameters": "0x84",
        "nonvolatile": True,
        "extensions": ["sav"],
        "size_maximum": 524300,
        "address": "0x20000000",
    }
    if save != expected_save:
        raise ValueError(f"APF Save slot mismatch: {save!r}")
    if not re.search(r"datatable_addr\s*<=\s*2\s*\*\s*3\s*\+\s*1\s*;", core_top):
        raise ValueError("APF runtime size does not target Save slot index 3")
    if not re.search(
        r"datatable_data\s*<=\s*save_size_bytes\s*\+\s*"
        r"\(has_rtc\s*\?\s*12\s*:\s*0\)\s*;",
        core_top,
    ):
        raise ValueError("APF runtime Save-slot size formula mismatch")


def must_fail(arguments: list[object], expected: str) -> None:
    try:
        verify_contract(*arguments)  # type: ignore[arg-type]
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid APF SRAM contract passed: {expected}")


def main() -> None:
    memorymux = (ROOT / "src/fpga/core/rtl/memorymux.vhd").read_text(encoding="utf-8")
    savestates = (ROOT / "src/fpga/core/rtl/savestates.vhd").read_text(encoding="utf-8")
    wonderswan = (ROOT / "src/fpga/core/wonderswan.sv").read_text(encoding="utf-8")
    core_top = (ROOT / "src/fpga/core/core_top.v").read_text(encoding="utf-8")
    data_definition = json.loads(
        (ROOT / "dist/Cores/agg23.WonderSwan/data.json").read_text(encoding="utf-8")
    )
    valid: list[object] = [
        memorymux, savestates, wonderswan, core_top, data_definition
    ]
    verify_contract(*valid)  # type: ignore[arg-type]

    old_mask = memorymux.replace(
        'x"007FFF" when ramtype = x"01"',
        'x"001FFF" when ramtype = x"01"',
        1,
    )
    must_fail([old_mask, *valid[1:]], "ramtype 01 mapper mask")

    old_state_size = savestates.replace(
        'when x"01"  => savetypes(2) <=  32768',
        'when x"01"  => savetypes(2) <=   8192',
        1,
    )
    must_fail([memorymux, old_state_size, *valid[2:]], "save-state payload")

    old_pocket_size = wonderswan.replace(
        "if (ramtype == 8'h01) save_size_bytes = 20'h08000",
        "if (ramtype == 8'h01) save_size_bytes = 20'h02000",
        1,
    )
    must_fail(
        [memorymux, savestates, old_pocket_size, core_top, data_definition],
        "Pocket bytes",
    )

    wrong_slot = deepcopy(data_definition)
    wrong_slot["data"]["data_slots"][3]["parameters"] = "0x80"
    must_fail([*valid[:4], wrong_slot], "APF Save slot mismatch")

    wrong_formula = core_top.replace("save_size_bytes +", "save_size_bytes * 2 +", 1)
    must_fail(
        [memorymux, savestates, wonderswan, wrong_formula, data_definition],
        "size formula mismatch",
    )

    print(
        "PASS SRAM size contract type01=32768 type02=32768 "
        "Pocket=exact-bytes APF=dynamic+conditional-RTC"
    )


if __name__ == "__main__":
    main()
