#!/usr/bin/env python3
"""Mutation tests for the generated 896 KiB compact-ROM contract."""

from __future__ import annotations

import hashlib

import generate_non_power_two_probe as probe


def expect_rejected(rom: bytes, message: str) -> None:
    try:
        probe.validate(rom)
    except ValueError as error:
        assert message in str(error), (message, error)
    else:
        raise AssertionError(f"mutation unexpectedly accepted: {message}")


def restamp(rom: bytearray) -> bytes:
    probe.restamp_checksum(rom)
    return bytes(rom)


def main() -> None:
    rom = probe.image()
    probe.validate(rom)
    assert len(rom) == probe.RAW_SIZE == 917_504
    assert probe.PREFIX_SIZE == 128 * 1024
    assert rom[probe.MARKER_OFFSET : probe.MARKER_OFFSET + len(probe.MARKER)] == probe.MARKER
    assert rom[-16] == 0xEA
    assert rom[-11] == 0xA0
    assert rom[-6:-2] == bytes((0x03, 0x00, 0x04, 0x00))

    expect_rejected(rom[:-2], "64 KiB-aligned")

    bad_entry = bytearray(rom)
    bad_entry[-16] = 0x90
    expect_rejected(restamp(bad_entry), "begin with 0xEA")

    bad_maintenance = bytearray(rom)
    bad_maintenance[-11] |= 0x01
    expect_rejected(restamp(bad_maintenance), "maintenance low bits")

    bad_size = bytearray(rom)
    bad_size[-6] = 0x04
    expect_rejected(restamp(bad_size), "size does not match")

    bad_save = bytearray(rom)
    bad_save[-5] = 0x7F
    expect_rejected(restamp(bad_save), "save type")

    bad_bus = bytearray(rom)
    bad_bus[-4] &= ~0x04
    expect_rejected(restamp(bad_bus), "16-bit ROM bus")

    bad_mapper = bytearray(rom)
    bad_mapper[-3] = 0x02
    expect_rejected(restamp(bad_mapper), "mapper")

    bad_checksum = bytearray(rom)
    bad_checksum[0] ^= 0x01
    expect_rejected(bytes(bad_checksum), "checksum mismatch")

    # The fixture is generated, not checked in. Bind this test to its complete
    # authored byte identity so accidental content drift is reviewed.
    digest = hashlib.sha256(rom).hexdigest()
    assert digest == "b4a2c985906ac04c6622080bb1f1f3ac4b3895784c5594f4ba97cd45e6935979", digest
    print("PASS generated 896 KiB compact-ROM fixture and negative mutations")


if __name__ == "__main__":
    main()
