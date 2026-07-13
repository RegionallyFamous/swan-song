#!/usr/bin/env python3
"""Mutation-strong tests for the legacy type-01 Pocket save migrator."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import io
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

import migrate_type01_save as migrator


def checksummed_rom(
    *, size: int = migrator.MIN_ROM_SIZE, ram_type: int = migrator.TYPE01
) -> bytes:
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


def restamp_checksum(rom: bytearray) -> None:
    rom[-2:] = (sum(rom[:-2]) & 0xFFFF).to_bytes(2, "little")


def snapshot(path: pathlib.Path) -> tuple[bytes, int, int, int, int]:
    metadata = path.stat()
    return (
        path.read_bytes(),
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mtime_ns,
        stat.S_IMODE(metadata.st_mode),
    )


class MigrateType01SaveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="swan-song-type01-migrate-test-"
        )
        self.root = pathlib.Path(self.temporary.name)
        self.rom = self.root / "game.ws"
        self.save = self.root / "legacy.sav"
        self.rom.write_bytes(checksummed_rom())
        self.sram = bytes((index * 17 + index // 31) & 0xFF for index in range(8192))
        # Deliberately has no assumed RT/TR sentinel or byte-order structure.
        self.rtc = bytes(
            (0x00, 0xFF, 0x52, 0x54, 0x80, 0x01, 0x7F, 0xA5, 0x5A, 0x10, 0xFE, 0x33)
        )
        self.save.write_bytes(self.sram + self.rtc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def output(self, name: str = "migrated.sav") -> pathlib.Path:
        return self.root / name

    def temporary_outputs(self) -> list[pathlib.Path]:
        return list(self.root.glob(f"{migrator.TEMP_PREFIX}*.tmp"))

    def test_exact_layout_hashes_determinism_and_cli_report(self) -> None:
        rom_before = snapshot(self.rom)
        save_before = snapshot(self.save)
        expected = self.sram + bytes(24576) + self.rtc

        first = self.output("first.sav")
        second = self.output("second.sav")
        report = migrator.migrate_type01_save(self.rom, self.save, first)
        migrator.migrate_type01_save(self.rom, self.save, second)

        self.assertEqual(len(expected), migrator.MIGRATED_SAVE_SIZE)
        self.assertEqual(first.read_bytes(), expected)
        self.assertEqual(second.read_bytes(), expected)
        self.assertEqual(first.read_bytes()[:8192], self.sram)
        self.assertEqual(first.read_bytes()[8192:32768], bytes(24576))
        self.assertEqual(first.read_bytes()[32768:32780], self.rtc)
        self.assertEqual(snapshot(self.rom), rom_before)
        self.assertEqual(snapshot(self.save), save_before)
        self.assertEqual(
            report.rom_sha256, hashlib.sha256(self.rom.read_bytes()).hexdigest()
        )
        self.assertEqual(
            report.legacy_save_sha256,
            hashlib.sha256(self.save.read_bytes()).hexdigest(),
        )
        self.assertEqual(report.rtc_sha256, hashlib.sha256(self.rtc).hexdigest())
        self.assertEqual(report.output_sha256, hashlib.sha256(expected).hexdigest())
        self.assertEqual(self.temporary_outputs(), [])

        cli_output = self.output("cli.sav")
        stdout = io.StringIO()
        with mock.patch.object(
            sys,
            "argv",
            ["migrate_type01_save.py", str(self.rom), str(self.save), str(cli_output)],
        ), contextlib.redirect_stdout(stdout):
            migrator.main()
        rendered = stdout.getvalue()
        self.assertIn(f"ROM SHA-256: {report.rom_sha256}", rendered)
        self.assertIn("preserve SRAM [0,8192)", rendered)
        self.assertIn("zero-fill SRAM [8192,32768)", rendered)
        self.assertIn("relocate RTC [8192,8204) -> [32768,32780)", rendered)
        self.assertIn(
            "opaque 12-byte copy; byte order and sentinel unchecked", rendered
        )
        self.assertIn(f"Output SHA-256: {report.output_sha256}", rendered)
        self.assertEqual(cli_output.read_bytes(), expected)

    def test_rejects_wrong_rom_size_type_and_checksum(self) -> None:
        mutations: list[tuple[str, bytes, str]] = []
        mutations.append(("empty", b"", "too small"))
        mutations.append(
            (
                "below-minimum",
                checksummed_rom(size=migrator.MIN_ROM_SIZE - 1),
                "too small",
            )
        )
        for ram_type in (0x00, 0x02, 0x03, 0x10, 0xFF):
            mutations.append(
                (
                    f"type-{ram_type:02x}",
                    checksummed_rom(ram_type=ram_type),
                    "must be exactly 0x01",
                )
            )

        bad_payload = bytearray(checksummed_rom())
        bad_payload[1234] ^= 0x01
        mutations.append(("payload-checksum", bytes(bad_payload), "checksum mismatch"))
        bad_checksum = bytearray(checksummed_rom())
        bad_checksum[-1] ^= 0x80
        mutations.append(("stored-checksum", bytes(bad_checksum), "checksum mismatch"))

        original_save = snapshot(self.save)
        for name, rom_data, message in mutations:
            with self.subTest(name=name):
                path = self.root / f"{name}.ws"
                output = self.root / f"{name}.sav"
                path.write_bytes(rom_data)
                rom_before = snapshot(path)
                with self.assertRaisesRegex(ValueError, message):
                    migrator.migrate_type01_save(path, self.save, output)
                self.assertFalse(os.path.lexists(output))
                self.assertEqual(snapshot(path), rom_before)
                self.assertEqual(snapshot(self.save), original_save)
                self.assertEqual(self.temporary_outputs(), [])

        # Only the documented type byte and checksum are migration gates. A
        # valid nonessential footer mutation must not accidentally become a
        # game-ID, jump-target, mapper, filename-extension, or metadata lock.
        unusual = bytearray(checksummed_rom())
        unusual[-16] = 0x90
        unusual[-10] = 0xE7
        unusual[-3] = 0x7F
        restamp_checksum(unusual)
        unusual_path = self.root / "unusual-footer.bin"
        unusual_path.write_bytes(unusual)
        output = self.output("unusual-footer.sav")
        migrator.migrate_type01_save(unusual_path, self.save, output)
        self.assertEqual(output.read_bytes(), self.sram + bytes(24576) + self.rtc)

    def test_rejects_every_known_wrong_save_shape_and_boundaries(self) -> None:
        invalid_lengths = (
            0,
            1,
            8191,
            8192,
            8193,
            8203,
            8205,
            32768,
            32779,
            32780,
            32781,
            65536,
        )
        rom_before = snapshot(self.rom)
        for length in invalid_lengths:
            with self.subTest(length=length):
                path = self.root / f"save-{length}.sav"
                path.write_bytes(
                    bytes((index * 11 + 3) & 0xFF for index in range(length))
                )
                save_before = snapshot(path)
                output = self.root / f"output-{length}.sav"
                with self.assertRaisesRegex(ValueError, "must be exactly 8204"):
                    migrator.migrate_type01_save(self.rom, path, output)
                self.assertFalse(os.path.lexists(output))
                self.assertEqual(snapshot(path), save_before)
                self.assertEqual(snapshot(self.rom), rom_before)
                self.assertEqual(self.temporary_outputs(), [])

    def test_rejects_existing_output_aliases_and_links(self) -> None:
        rom_before = snapshot(self.rom)
        save_before = snapshot(self.save)

        existing = self.output("existing.sav")
        existing.write_bytes(b"do not replace")
        cases: list[tuple[str, pathlib.Path, str, bytes | None]] = [
            ("same-save-path", self.save, "aliases input", None),
            ("same-rom-path", self.rom, "aliases input", None),
            ("existing-file", existing, "already exists", b"do not replace"),
        ]

        existing_directory = self.root / "existing-directory"
        existing_directory.mkdir()
        cases.append(("existing-directory", existing_directory, "already exists", None))

        save_hardlink = self.output("save-hardlink.sav")
        os.link(self.save, save_hardlink)
        rom_hardlink = self.output("rom-hardlink.ws")
        os.link(self.rom, rom_hardlink)
        cases.extend(
            (
                ("save-hardlink", save_hardlink, "inode aliases input", None),
                ("rom-hardlink", rom_hardlink, "inode aliases input", None),
            )
        )

        save_symlink = self.output("save-symlink.sav")
        save_symlink.symlink_to(self.save)
        rom_symlink = self.output("rom-symlink.ws")
        rom_symlink.symlink_to(self.rom)
        unrelated_target = self.output("unrelated-target")
        unrelated_target.write_bytes(b"unrelated")
        unrelated_symlink = self.output("unrelated-symlink.sav")
        unrelated_symlink.symlink_to(unrelated_target)
        dangling_symlink = self.output("dangling-symlink.sav")
        dangling_symlink.symlink_to(self.root / "missing-target")
        cases.extend(
            (
                ("save-symlink", save_symlink, "inode aliases input", None),
                ("rom-symlink", rom_symlink, "inode aliases input", None),
                ("unrelated-symlink", unrelated_symlink, "already exists", None),
                ("dangling-symlink", dangling_symlink, "already exists", None),
            )
        )

        lexical = self.root / "subdir" / ".." / self.save.name
        (self.root / "subdir").mkdir()
        cases.append(("lexical-alias", lexical, "aliases input", None))

        for name, output, message, expected_bytes in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, message):
                    migrator.migrate_type01_save(self.rom, self.save, output)
                if expected_bytes is not None:
                    self.assertEqual(output.read_bytes(), expected_bytes)
                self.assertEqual(snapshot(self.rom), rom_before)
                self.assertEqual(snapshot(self.save), save_before)
                self.assertEqual(self.temporary_outputs(), [])

        self.assertEqual(unrelated_target.read_bytes(), b"unrelated")
        self.assertTrue(dangling_symlink.is_symlink())

    def test_accepts_read_only_input_symlinks_without_modifying_targets(self) -> None:
        rom_link = self.root / "rom-link.ws"
        save_link = self.root / "save-link.sav"
        rom_link.symlink_to(self.rom)
        save_link.symlink_to(self.save)
        rom_before = snapshot(self.rom)
        save_before = snapshot(self.save)
        output = self.output("from-links.sav")
        migrator.migrate_type01_save(rom_link, save_link, output)
        self.assertEqual(output.read_bytes(), self.sram + bytes(24576) + self.rtc)
        self.assertEqual(snapshot(self.rom), rom_before)
        self.assertEqual(snapshot(self.save), save_before)

    def test_atomic_failures_and_destination_race_leave_no_partial_output(self) -> None:
        rom_before = snapshot(self.rom)
        save_before = snapshot(self.save)

        write_failure = self.output("fsync-failure.sav")
        with mock.patch.object(
            migrator.os,
            "fsync",
            side_effect=OSError(errno.EIO, "injected fsync failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected fsync failure"):
                migrator.migrate_type01_save(self.rom, self.save, write_failure)
        self.assertFalse(os.path.lexists(write_failure))
        self.assertEqual(self.temporary_outputs(), [])

        publish_failure = self.output("publish-failure.sav")
        with mock.patch.object(
            migrator,
            "_rename_noreplace",
            side_effect=OSError(errno.EIO, "injected publish failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected publish failure"):
                migrator.migrate_type01_save(self.rom, self.save, publish_failure)
        self.assertFalse(os.path.lexists(publish_failure))
        self.assertEqual(self.temporary_outputs(), [])

        raced_output = self.output("raced.sav")

        def race_destination(_temporary: pathlib.Path, output: pathlib.Path) -> None:
            output.write_bytes(b"racer owns this path")
            raise FileExistsError(errno.EEXIST, "injected destination race")

        with mock.patch.object(
            migrator, "_rename_noreplace", side_effect=race_destination
        ):
            with self.assertRaisesRegex(ValueError, "appeared during migration"):
                migrator.migrate_type01_save(self.rom, self.save, raced_output)
        self.assertEqual(raced_output.read_bytes(), b"racer owns this path")
        self.assertEqual(self.temporary_outputs(), [])
        self.assertEqual(snapshot(self.rom), rom_before)
        self.assertEqual(snapshot(self.save), save_before)

    def test_missing_nonregular_inputs_and_output_parent_fail_closed(self) -> None:
        missing = self.root / "missing.ws"
        with self.assertRaisesRegex(ValueError, "cannot open ROM"):
            migrator.migrate_type01_save(missing, self.save, self.output("missing.sav"))

        directory = self.root / "directory-input"
        directory.mkdir()
        with self.assertRaisesRegex(ValueError, "ROM is not a regular file"):
            migrator.migrate_type01_save(
                directory, self.save, self.output("directory.sav")
            )

        parent_is_file = self.root / "not-a-directory"
        parent_is_file.write_bytes(b"file")
        with self.assertRaisesRegex(ValueError, "output parent is not a directory"):
            migrator.migrate_type01_save(
                self.rom, self.save, parent_is_file / "output.sav"
            )

        missing_parent = self.root / "missing-parent" / "output.sav"
        with self.assertRaisesRegex(ValueError, "cannot access output directory"):
            migrator.migrate_type01_save(self.rom, self.save, missing_parent)
        self.assertEqual(self.temporary_outputs(), [])


if __name__ == "__main__":
    unittest.main()
