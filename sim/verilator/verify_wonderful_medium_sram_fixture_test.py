#!/usr/bin/env python3
"""Focused mutation tests for the Wonderful medium-SRAM fixture identity."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from verify_wonderful_medium_sram_fixture import ROM_NAME, verify_fixture


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "testroms/swan-song/wonderful_medium_sram"


def must_fail(path: Path) -> None:
    try:
        verify_fixture(path)
    except ValueError:
        return
    raise AssertionError("mutated medium-SRAM fixture passed identity verification")


def main() -> None:
    verify_fixture(FIXTURE)
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
        data[0x1EE05] ^= 1
        rom.write_bytes(data)
        must_fail(copy)
    print("PASS Wonderful medium-SRAM fixture source/ROM mutation rejection")


if __name__ == "__main__":
    main()
