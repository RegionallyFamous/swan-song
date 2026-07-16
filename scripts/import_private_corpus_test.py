#!/usr/bin/env python3
"""Synthetic, offline tests for the private ZIP-to-corpus importer."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
import zipfile

import import_private_corpus as importer
import run_private_corpus as corpus


def synthetic_rom(*, color: bool, marker: int = 0x41, valid_checksum: bool = True) -> bytes:
    image = bytearray(((index * 37 + marker) & 0xFF) for index in range(64 * 1024))
    footer = len(image) - 16
    image[footer + 0] = 0xEA
    image[footer + 5] = 0x00
    image[footer + 7] = int(color)
    image[footer + 10] = 0x00
    image[footer + 11] = 0x00
    image[footer + 12] = 0x04
    image[footer + 13] = 0x00
    image[-2:] = (sum(image[:-2]) & 0xFFFF).to_bytes(2, "little")
    if not valid_checksum:
        image[0x100] ^= 1
    return bytes(image)


class PrivateCorpusImporterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-import-test-")
        self.base = Path(self.temporary.name)
        self.source = self.base / "Owner Collection"
        self.source.mkdir()
        self.lab_root = self.base / "Private Lab"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def archive(
        self,
        name: str,
        members: list[tuple[str | zipfile.ZipInfo, bytes]],
        *,
        compression: int = zipfile.ZIP_DEFLATED,
    ) -> Path:
        path = self.source / name
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for member, data in members:
                archive.writestr(member, data)
        return path

    def invoke(self, *arguments: str) -> tuple[int, dict | None, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = importer.main([*arguments])
        output = stdout.getvalue()
        return status, json.loads(output) if output else None, output, stderr.getvalue()

    def base_arguments(self) -> list[str]:
        return [str(self.source), "--lab-root", str(self.lab_root)]

    def test_dry_run_is_default_apply_is_opaque_and_runner_compatible(self) -> None:
        secret = "Very Secret Color Game"
        rom = synthetic_rom(color=True)
        self.archive(f"{secret}.zip", [(f"{secret}.wsc", rom)])

        status, dry, output, stderr = self.invoke(*self.base_arguments())
        self.assertEqual((status, stderr), (0, ""))
        assert dry is not None
        self.assertEqual(dry["mode"], "dry_run")
        self.assertEqual(dry["counts"]["planned_new_files"], 1)
        lab, _warnings = corpus.initialize_lab(self.lab_root)
        self.assertEqual(list(lab.roms.iterdir()), [])
        self.assertNotIn(secret, output)
        self.assertNotIn(str(self.source), output)
        self.assertNotIn(hashlib.sha256(rom).hexdigest(), output)

        status, applied, output, stderr = self.invoke(*self.base_arguments(), "--apply")
        self.assertEqual((status, stderr), (0, ""))
        assert applied is not None
        self.assertEqual(applied["counts"]["imported"], 1)
        imported = list(lab.roms.iterdir())
        self.assertEqual(len(imported), 1)
        self.assertRegex(imported[0].name, r"^rom-[0-9a-f]{64}\.wsc$")
        self.assertEqual(imported[0].read_bytes(), rom)
        self.assertEqual(stat.S_IMODE(imported[0].stat().st_mode), 0o600)
        key, _warning = corpus.load_or_create_key(lab.key)
        inventory = corpus._walk_rom_tree(lab.roms, key, 0)
        self.assertEqual(len(inventory.cases), 1)
        self.assertEqual(inventory.cases[0].case_id, applied["cases"][0]["case_id"])

    def test_deduplicates_exact_roms_and_selection_does_not_leak_terms(self) -> None:
        selected_title = "Known Problem Alpha"
        excluded_title = "Ordinary Beta"
        rom = synthetic_rom(color=False, marker=0x22)
        self.archive(f"{selected_title}.zip", [(f"{selected_title}.ws", rom)])
        self.archive("Duplicate Copy.zip", [("Duplicate.ws", rom)])
        self.archive(
            f"{excluded_title}.zip",
            [(f"{excluded_title}.ws", synthetic_rom(color=False, marker=0x33))],
        )

        status, document, output, _stderr = self.invoke(
            *self.base_arguments(), "--select", "Known Problem", "--limit", "1"
        )
        self.assertEqual(status, 0)
        assert document is not None
        self.assertEqual(document["counts"]["archives_selected"], 1)
        self.assertEqual(document["selection"]["include_terms"], 1)
        self.assertNotIn(selected_title, output)
        self.assertNotIn("Known Problem", output)
        self.assertNotIn(excluded_title, output)

        status, document, _output, _stderr = self.invoke(*self.base_arguments())
        self.assertEqual(status, 0)
        assert document is not None
        self.assertEqual(document["counts"]["valid_unique_roms"], 2)
        self.assertEqual(document["counts"]["duplicate_roms"], 1)

    def test_rejects_traversal_symlink_encryption_multi_rom_and_bad_images(self) -> None:
        valid = synthetic_rom(color=False)
        self.archive("Traversal.zip", [("../Escape.ws", valid)])
        link = zipfile.ZipInfo("Linked.ws")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.archive("Symlink.zip", [(link, b"target")], compression=zipfile.ZIP_STORED)
        self.archive("Multiple.zip", [("One.ws", valid), ("Two.ws", valid)])
        self.archive(
            "Bad Footer.zip", [("Broken.ws", bytes(64 * 1024))], compression=zipfile.ZIP_STORED
        )
        self.archive(
            "Bad Checksum.zip",
            [("Checksum.ws", synthetic_rom(color=False, valid_checksum=False))],
        )
        encrypted = self.archive("Encrypted.zip", [("Encrypted.ws", valid)])
        encrypted_body = bytearray(encrypted.read_bytes())
        local = encrypted_body.find(b"PK\x03\x04")
        central = encrypted_body.find(b"PK\x01\x02")
        self.assertGreaterEqual(min(local, central), 0)
        local_flags = struct.unpack_from("<H", encrypted_body, local + 6)[0] | 1
        central_flags = struct.unpack_from("<H", encrypted_body, central + 8)[0] | 1
        struct.pack_into("<H", encrypted_body, local + 6, local_flags)
        struct.pack_into("<H", encrypted_body, central + 8, central_flags)
        encrypted.write_bytes(encrypted_body)

        status, document, output, _stderr = self.invoke(*self.base_arguments(), "--apply")
        self.assertEqual(status, 1)
        assert document is not None
        reasons = {case["reason"] for case in document["cases"]}
        self.assertEqual(
            reasons,
            {
                "archive_member_traversal",
                "archive_member_symlink",
                "archive_multi_rom",
                "rom_footer_entry_invalid",
                "rom_footer_checksum_invalid",
                "archive_encrypted",
            },
        )
        lab, _warnings = corpus.initialize_lab(self.lab_root)
        self.assertEqual(list(lab.roms.iterdir()), [])
        for secret in (
            "Traversal",
            "Symlink",
            "Multiple",
            "Bad Footer",
            "Bad Checksum",
            "Encrypted",
            str(self.source),
        ):
            self.assertNotIn(secret, output)

    def test_rejects_zip_bomb_and_filesystem_symlink(self) -> None:
        # The bounded reader rejects both unsafe expansion and source aliases.
        self.archive(
            "Expansion Bomb.zip",
            [("Huge.wsc", bytes(2 * 1024 * 1024))],
            compression=zipfile.ZIP_DEFLATED,
        )
        outside = self.base / "outside.zip"
        with zipfile.ZipFile(outside, "w") as archive:
            archive.writestr("Outside.ws", synthetic_rom(color=False))
        os.symlink(outside, self.source / "Alias.zip")

        status, document, output, _stderr = self.invoke(*self.base_arguments(), "--apply")
        self.assertEqual(status, 1)
        assert document is not None
        reasons = {case["reason"] for case in document["cases"]}
        self.assertIn("archive_expansion_ratio_unsafe", reasons)
        self.assertIn("source_symlink_forbidden", reasons)
        self.assertNotIn("Expansion Bomb", output)
        self.assertNotIn("Alias.zip", output)

    def test_import_surface_is_rom_only(self) -> None:
        help_text = importer.parser().format_help()
        self.assertNotIn("--bios-mono", help_text)
        self.assertNotIn("--bios-color", help_text)


if __name__ == "__main__":
    unittest.main()
