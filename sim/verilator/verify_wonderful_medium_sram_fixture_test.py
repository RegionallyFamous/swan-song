#!/usr/bin/env python3
"""Focused mutation tests for the Wonderful medium-SRAM fixture identity."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from verify_wonderful_medium_sram_fixture import (
    MESSAGE_OFFSET,
    ROM_NAME,
    verify_build_contract,
    verify_fixture,
    verify_source_contract,
    verify_startup_contract,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "testroms/swan-song/wonderful_medium_sram"


def must_fail(path: Path) -> None:
    try:
        verify_fixture(path)
    except ValueError:
        return
    raise AssertionError("mutated medium-SRAM fixture passed identity verification")


def must_reject_source(source: str) -> None:
    try:
        verify_source_contract(source)
    except ValueError:
        return
    raise AssertionError("invalid medium-SRAM source ordering passed contract verification")


def main() -> None:
    verify_fixture(FIXTURE)
    source_text = (FIXTURE / "src/main.c").read_text(encoding="utf-8")
    verify_source_contract(source_text)
    mode = "bool valid = ws_system_set_mode(WS_MODE_COLOR);"
    read = "valid = valid && initialized_word == 0x5AA5 && zero_word == 0;"
    must_reject_source(source_text.replace(f"\t{mode}\n\t{read}", f"\t{read}\n\t{mode}"))
    startup_text = (FIXTURE / "src/crt0_color.s").read_text(encoding="utf-8")
    verify_startup_contract(startup_text)
    must_reject_startup = startup_text.replace("\tor\tal, 0x80\n", "\tor\tal, 0x40\n", 1)
    try:
        verify_startup_contract(must_reject_startup)
    except ValueError:
        pass
    else:
        raise AssertionError("CRT without pre-stack Color enable passed source contract")
    stock_finish = startup_text.replace(
        "\t// Color mode was enabled before selecting SP=8000h; do not clear it here.\n",
        "\tin\tal, 0x60\n\tand\tal, 0x1F\n\tout\t0x60, al\n",
    )
    try:
        verify_startup_contract(stock_finish)
    except ValueError:
        pass
    else:
        raise AssertionError("CRT with a post-enable Color clear passed source contract")
    makefile_text = (FIXTURE / "Makefile").read_text(encoding="utf-8")
    verify_build_contract(makefile_text)
    try:
        verify_build_contract(makefile_text.replace("$(CRT0_OBJ)", "$(WF_CRT0)"))
    except ValueError:
        pass
    else:
        raise AssertionError("Makefile stock-CRT regression passed build contract")
    with tempfile.TemporaryDirectory(prefix="swansong-medium-sram-") as directory:
        copy = Path(directory) / "fixture"
        shutil.copytree(FIXTURE, copy)
        source = copy / "src/main.c"
        source.write_bytes(source.read_bytes().replace(b"0x5AA5", b"0x5AA4", 1))
        must_fail(copy)

        shutil.rmtree(copy)
        shutil.copytree(FIXTURE, copy)
        rom = copy / ROM_NAME
        data = bytearray(rom.read_bytes())
        data[MESSAGE_OFFSET] ^= 1
        rom.write_bytes(data)
        must_fail(copy)
    print("PASS Wonderful medium-SRAM fixture source/ROM mutation rejection")


if __name__ == "__main__":
    main()
