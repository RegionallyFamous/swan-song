#!/usr/bin/env python3
"""Verify the original 896 KiB compact probe through translated-core video."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import generate_non_power_two_probe as probe


ROM_SHA256 = "b4a2c985906ac04c6622080bb1f1f3ac4b3895784c5594f4ba97cd45e6935979"
FRAME_SHA256 = (
    "42cbd40de83feff488f8c63cfbb0bf0a160f7c96416bcb74328b9982e1d04bdb",
    "7f672cb770893d021bb6c684efccb9b118894f657e65dd4e8b966a2d90fefa5d",
)
FRAME_BYTES = 224 * 144 * 3


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(rom_path: Path, frames: Path) -> None:
    rom = rom_path.read_bytes()
    probe.validate(rom)
    if len(rom) != probe.RAW_SIZE or digest(rom) != ROM_SHA256:
        raise ValueError("896 KiB compact probe size/hash mismatch")
    if rom[-11] != 0xA0:
        raise ValueError("legal upper maintenance flags were not preserved")
    marker = rom.find(probe.MARKER)
    if marker != probe.MARKER_OFFSET or rom.find(probe.MARKER, marker + 1) != -1:
        raise ValueError("compact probe authored marker identity mismatch")

    for index, expected in enumerate(FRAME_SHA256):
        payload = (frames / f"frame-{index}.rgb").read_bytes()
        if len(payload) != FRAME_BYTES or digest(payload) != expected:
            raise ValueError(f"compact probe frame {index} identity mismatch")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("rom", type=Path)
    parser.add_argument("frames", type=Path)
    args = parser.parse_args()
    verify(args.rom, args.frames)
    print("PASS translated core booted the right-aligned 896 KiB compact ROM")


if __name__ == "__main__":
    main()
