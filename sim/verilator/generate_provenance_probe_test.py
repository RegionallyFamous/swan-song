#!/usr/bin/env python3
"""Contract tests for the open Color GDMA provenance probe generator."""

from __future__ import annotations

import tempfile
from pathlib import Path

from generate_provenance_probe import FOOTER_SIZE, PROGRAM, ROM_SIZE, generate


COLOR_ENABLE = bytes((0xB0, 0x80, 0xE6, 0x60))
DMA_SOURCE_LOW = bytes((0xB0, 0x00, 0xE6, 0x40))


def main() -> None:
    assert PROGRAM.startswith(bytes((0xFA,)) + COLOR_ENABLE)
    assert PROGRAM.find(COLOR_ENABLE) < PROGRAM.find(DMA_SOURCE_LOW)
    assert PROGRAM.count(COLOR_ENABLE) == 1

    with tempfile.TemporaryDirectory(prefix="swansong-provenance-generator-") as directory:
        root = Path(directory)
        carrier = root / "carrier.ws"
        output = root / "probe.wsc"
        footer = bytearray((0x00,)) * FOOTER_SIZE
        footer[0:5] = bytes((0xEA, 0x00, 0x00, 0x00, 0xF0))
        carrier.write_bytes(footer)

        generate(carrier, output)
        image = output.read_bytes()
        assert len(image) == ROM_SIZE
        assert image[: len(PROGRAM)] == PROGRAM
        assert image[0x0100:0x0104] == bytes((0x34, 0x12, 0x78, 0x56))
        assert image[-FOOTER_SIZE + 7] == 1

    print("PASS provenance probe self-enables Color mode before GDMA")


if __name__ == "__main__":
    main()
