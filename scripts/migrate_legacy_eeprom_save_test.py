#!/usr/bin/env python3
"""Focused tests for padded type-10/type-50 Pocket save migration."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import migrate_legacy_eeprom_save as migrator


def checksummed_rom(ram_type: int, size: int = migrator.MIN_ROM_SIZE) -> bytes:
    if size < 16:
        return bytes(size)
    rom = bytearray((index * 29 + 7) & 0xFF for index in range(size))
    footer = bytearray(16)
    footer[:5] = bytes((0xEA, 0x34, 0x12, 0x78, 0x56))
    footer[5:11] = bytes((0x00, 0x01, 0x00, 0x42, 0x03, 0x00))
    footer[11] = ram_type
    footer[12:14] = bytes((0x04, 0x00))
    rom[-16:] = footer
    rom[-2:] = (sum(rom[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(rom)


class MigrateLegacyEepromSaveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="swan-song-padded-eeprom-migrate-test-"
        )
        self.root = pathlib.Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_inputs(
        self, ram_type: int
    ) -> tuple[pathlib.Path, pathlib.Path, bytes, bytes, bytes]:
        payload_size = migrator.EXACT_EEPROM_SIZES[ram_type]
        rom = self.root / f"game-{ram_type:02x}.ws"
        save = self.root / f"legacy-{ram_type:02x}.sav"
        payload = bytes(
            (index * 17 + index // 13 + ram_type) & 0xFF
            for index in range(payload_size)
        )
        padding = bytes(
            (index * 31 + 0x52) & 0xFF
            for index in range(migrator.LEGACY_EEPROM_SIZE - payload_size)
        )
        rtc = b"RT" + bytes((0x00, 0xFF, 0x80, 0x01, 0x7F, 0xA5, 0x5A, 0x10, 0xFE, 0x33))
        rom.write_bytes(checksummed_rom(ram_type))
        save.write_bytes(payload + padding + rtc)
        return rom, save, payload, padding, rtc

    def test_exact_type10_and_type50_layouts_are_deterministic(self) -> None:
        for ram_type, expected_size in (
            (migrator.TYPE10, 140),
            (migrator.TYPE50, 1036),
        ):
            with self.subTest(ram_type=f"0x{ram_type:02x}"):
                rom, save, payload, padding, rtc = self.make_inputs(ram_type)
                rom_before = rom.read_bytes()
                save_before = save.read_bytes()
                first = self.root / f"first-{ram_type:02x}.sav"
                second = self.root / f"second-{ram_type:02x}.sav"

                report = migrator.migrate_legacy_eeprom_save(rom, save, first)
                migrator.migrate_legacy_eeprom_save(rom, save, second)

                expected = payload + rtc
                self.assertEqual(len(expected), expected_size)
                self.assertEqual(first.read_bytes(), expected)
                self.assertEqual(second.read_bytes(), expected)
                self.assertNotIn(padding, first.read_bytes())
                self.assertEqual(rom.read_bytes(), rom_before)
                self.assertEqual(save.read_bytes(), save_before)
                self.assertEqual(report.ram_type, ram_type)
                self.assertEqual(report.payload_size, len(payload))
                self.assertEqual(report.output_size, expected_size)
                self.assertEqual(
                    report.discarded_padding_sha256,
                    hashlib.sha256(padding).hexdigest(),
                )
                self.assertEqual(report.rtc_sha256, hashlib.sha256(rtc).hexdigest())
                self.assertEqual(
                    report.output_sha256, hashlib.sha256(expected).hexdigest()
                )

    def test_cli_report_describes_the_irreversible_padding_drop(self) -> None:
        rom, save, payload, _padding, rtc = self.make_inputs(migrator.TYPE10)
        output = self.root / "cli.sav"
        stdout = io.StringIO()
        with mock.patch.object(
            sys,
            "argv",
            [
                "migrate_legacy_eeprom_save.py",
                str(rom),
                str(save),
                str(output),
            ],
        ), contextlib.redirect_stdout(stdout):
            migrator.main()
        rendered = stdout.getvalue()
        self.assertIn("EEPROM type: 0x10", rendered)
        self.assertIn("preserve EEPROM [0,128)", rendered)
        self.assertIn("discard padding [128,2048)", rendered)
        self.assertIn("relocate RTC [2048,2060) -> [128,140)", rendered)
        self.assertIn("opaque 12-byte copy; byte order and sentinel unchecked", rendered)
        self.assertEqual(output.read_bytes(), payload + rtc)

    def test_rejects_wrong_rom_type_size_checksum_and_save_lengths(self) -> None:
        rom, save, _payload, _padding, _rtc = self.make_inputs(migrator.TYPE10)
        invalid_roms = (
            ("short", checksummed_rom(migrator.TYPE10, migrator.MIN_ROM_SIZE - 1), "too small"),
            ("type01", checksummed_rom(0x01), "type 0x10 or 0x50"),
            ("type20", checksummed_rom(0x20), "type 0x10 or 0x50"),
        )
        for name, data, message in invalid_roms:
            with self.subTest(rom=name):
                candidate = self.root / f"{name}.ws"
                candidate.write_bytes(data)
                output = self.root / f"{name}-out.sav"
                with self.assertRaisesRegex(ValueError, message):
                    migrator.migrate_legacy_eeprom_save(candidate, save, output)
                self.assertFalse(os.path.lexists(output))

        corrupt = bytearray(rom.read_bytes())
        corrupt[1234] ^= 0x01
        bad_checksum = self.root / "bad-checksum.ws"
        bad_checksum.write_bytes(corrupt)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            migrator.migrate_legacy_eeprom_save(
                bad_checksum, save, self.root / "bad-checksum.sav"
            )

        for length in (0, 128, 140, 1024, 1036, 2048, 2059, 2061, 32780):
            with self.subTest(save_length=length):
                candidate = self.root / f"legacy-{length}.sav"
                candidate.write_bytes(bytes(length))
                output = self.root / f"legacy-{length}-out.sav"
                with self.assertRaisesRegex(ValueError, "exactly 2060"):
                    migrator.migrate_legacy_eeprom_save(rom, candidate, output)
                self.assertFalse(os.path.lexists(output))

    def test_never_overwrites_or_aliases_an_input(self) -> None:
        rom, save, payload, _padding, rtc = self.make_inputs(migrator.TYPE50)
        rom_before = rom.read_bytes()
        save_before = save.read_bytes()

        with self.assertRaisesRegex(ValueError, "aliases input"):
            migrator.migrate_legacy_eeprom_save(rom, save, save)
        with self.assertRaisesRegex(ValueError, "aliases input"):
            migrator.migrate_legacy_eeprom_save(rom, save, rom)

        existing = self.root / "existing.sav"
        existing.write_bytes(b"do not replace")
        with self.assertRaisesRegex(ValueError, "already exists"):
            migrator.migrate_legacy_eeprom_save(rom, save, existing)
        self.assertEqual(existing.read_bytes(), b"do not replace")
        self.assertEqual(rom.read_bytes(), rom_before)
        self.assertEqual(save.read_bytes(), save_before)

        output = self.root / "valid.sav"
        migrator.migrate_legacy_eeprom_save(rom, save, output)
        self.assertEqual(output.read_bytes(), payload + rtc)


if __name__ == "__main__":
    unittest.main()
