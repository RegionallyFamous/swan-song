#!/usr/bin/env python3
"""Contract tests for the open Color GDMA provenance probe generator."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from generate_provenance_probe import (
    FOOTER_SIZE,
    PROGRAM,
    ROM_SIZE,
    footer,
    generate,
    image,
)


COLOR_ENABLE = bytes((0xB0, 0x80, 0xE6, 0x60))
DMA_SOURCE_LOW = bytes((0xB0, 0x00, 0xE6, 0x40))
SCRIPT = Path(__file__).with_name("generate_provenance_probe.py")


def generate_with_ignored_input(unused: Path, output: Path) -> bytes:
    subprocess.run(
        (sys.executable, str(SCRIPT), str(unused), str(output)),
        check=True,
        capture_output=True,
        text=True,
    )
    return output.read_bytes()


def assert_footer_valid(rom: bytes) -> None:
    metadata = rom[-FOOTER_SIZE:-2]
    assert metadata == bytes.fromhex("ea000000f0000001440100000400")
    assert int.from_bytes(rom[-2:], "little") == sum(rom[:-2]) & 0xFFFF


def main() -> None:
    assert PROGRAM.startswith(bytes((0xFA,)) + COLOR_ENABLE)
    assert PROGRAM.find(COLOR_ENABLE) < PROGRAM.find(DMA_SOURCE_LOW)
    assert PROGRAM.count(COLOR_ENABLE) == 1

    with tempfile.TemporaryDirectory(prefix="swansong-provenance-generator-") as directory:
        root = Path(directory)
        output = root / "probe.wsc"
        generate(output)
        rom = output.read_bytes()
        assert len(rom) == ROM_SIZE
        assert rom[: len(PROGRAM)] == PROGRAM
        assert rom[0x0100:0x0104] == bytes((0x34, 0x12, 0x78, 0x56))
        assert rom[-FOOTER_SIZE + 7] == 1
        assert_footer_valid(rom)

        assert footer()[-2:] == b"\x00\x00"
        assert rom == image()

        # The historical two-path command form remains usable by regression,
        # but the first path is neither required to exist nor consulted.
        missing = root / "does-not-exist.ws"
        absent_input = generate_with_ignored_input(missing, root / "absent.wsc")
        decoy = root / "unrelated.bin"
        decoy.write_bytes(b"first arbitrary contents")
        first_contents = generate_with_ignored_input(decoy, root / "first.wsc")
        decoy.write_bytes(b"different bytes and therefore a different hash")
        second_contents = generate_with_ignored_input(decoy, root / "second.wsc")
        assert absent_input == first_contents == second_contents == rom

    print("PASS self-contained checksummed provenance probe enables Color before GDMA")


if __name__ == "__main__":
    main()
