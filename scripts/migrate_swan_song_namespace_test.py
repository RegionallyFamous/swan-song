#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import migrate_swan_song_namespace as migration


SCRIPT = Path(__file__).with_name("migrate_swan_song_namespace.py")


class NamespaceMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "sd"
        self.root.mkdir()
        saves = self.root / "Saves/wonderswan/agg23.WonderSwan"
        saves.mkdir(parents=True)
        (saves / "mono.eeprom").write_bytes(bytes(range(128)))
        (saves / "color.eeprom").write_bytes(bytes(range(256)) * 8)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def add_json(self, relative: str, document: object | None = None) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document if document is not None else {"magic": "APF_VER_1"}),
            encoding="utf-8",
        )
        return path

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), "--sd-root", str(self.root), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_default_cli_is_read_only_and_reports_deterministic_plan(self) -> None:
        self.add_json(
            "Settings/agg23.WonderSwan/Interact/wonderswan/common/Game.json"
        )
        first = self.run_cli()
        second = self.run_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("VALIDATED ONLY", first.stdout)
        self.assertIn("3 to copy, 0 identical", first.stdout)
        self.assertIn("agg23.WonderSwan -> RegionallyFamous.SwanSong", first.stdout)
        self.assertFalse(
            (self.root / "Saves/wonderswan/RegionallyFamous.SwanSong").exists()
        )
        self.assertFalse((self.root / "Settings/RegionallyFamous.SwanSong").exists())

    def test_apply_copies_only_eeprom_and_recursive_json_without_touching_source(self) -> None:
        mono_source = self.root / "Saves/wonderswan/agg23.WonderSwan/mono.eeprom"
        color_source = self.root / "Saves/wonderswan/agg23.WonderSwan/color.eeprom"
        mono_before = mono_source.read_bytes()
        color_before = color_source.read_bytes()
        settings = self.add_json(
            "Settings/agg23.WonderSwan/Interact/wonderswan/common/Game.json",
            {"interact": {"magic": "APF_VER_1", "default": 2}},
        )
        preset = self.add_json(
            "Presets/agg23.WonderSwan/Input/wonderswan/common/Nested/Game.json",
            {"input": {"magic": "APF_VER_1"}},
        )
        ignored = self.root / "Settings/agg23.WonderSwan/notes.txt"
        ignored.write_text("not copied", encoding="utf-8")
        common_save = self.root / "Saves/wonderswan/common/Game.sav"
        common_save.parent.mkdir(parents=True)
        common_save.write_bytes(b"cartridge save")
        memories = self.root / "Memories/Beta/agg23.WonderSwan/state.bin"
        memories.parent.mkdir(parents=True)
        memories.write_bytes(b"memory state")
        wordpress = self.root / "wordpress/sentinel.txt"
        wordpress.parent.mkdir()
        wordpress.write_text("untouched", encoding="utf-8")

        result = self.run_cli("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("APPLIED", result.stdout)
        destination = self.root / "Saves/wonderswan/RegionallyFamous.SwanSong"
        self.assertEqual((destination / "mono.eeprom").read_bytes(), mono_before)
        self.assertEqual((destination / "color.eeprom").read_bytes(), color_before)
        self.assertEqual(
            (
                self.root
                / "Settings/RegionallyFamous.SwanSong/Interact/wonderswan/common/Game.json"
            ).read_bytes(),
            settings.read_bytes(),
        )
        self.assertEqual(
            (
                self.root
                / "Presets/RegionallyFamous.SwanSong/Input/wonderswan/common/Nested/Game.json"
            ).read_bytes(),
            preset.read_bytes(),
        )
        self.assertFalse(
            (self.root / "Settings/RegionallyFamous.SwanSong/notes.txt").exists()
        )
        self.assertEqual(common_save.read_bytes(), b"cartridge save")
        self.assertEqual(memories.read_bytes(), b"memory state")
        self.assertEqual(wordpress.read_text(encoding="utf-8"), "untouched")
        self.assertEqual(mono_source.read_bytes(), mono_before)
        self.assertEqual(color_source.read_bytes(), color_before)

    def test_identical_destinations_are_idempotent_and_never_rewritten(self) -> None:
        first = self.run_cli("--apply")
        self.assertEqual(first.returncode, 0, first.stderr)
        destination = self.root / "Saves/wonderswan/RegionallyFamous.SwanSong/mono.eeprom"
        identity = (destination.stat().st_ino, destination.stat().st_mtime_ns)
        second = self.run_cli("--apply")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("0 copied, 2 identical", second.stdout)
        self.assertEqual(identity, (destination.stat().st_ino, destination.stat().st_mtime_ns))

    def test_differing_destination_fails_before_any_copy(self) -> None:
        destination = self.root / "Saves/wonderswan/RegionallyFamous.SwanSong"
        destination.mkdir(parents=True)
        (destination / "color.eeprom").write_bytes(b"different")
        result = self.run_cli("--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertFalse((destination / "mono.eeprom").exists())
        self.assertEqual((destination / "color.eeprom").read_bytes(), b"different")

    def test_both_exact_eeprom_sources_are_required(self) -> None:
        saves = self.root / "Saves/wonderswan/agg23.WonderSwan"
        (saves / "mono.eeprom").write_bytes(b"short")
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("exactly 128 bytes", result.stderr)
        (saves / "mono.eeprom").write_bytes(bytes(128))
        (saves / "color.eeprom").unlink()
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("missing source color.eeprom", result.stderr)

    def test_rejects_source_eeprom_and_json_symlinks(self) -> None:
        saves = self.root / "Saves/wonderswan/agg23.WonderSwan"
        real = saves / "real.eeprom"
        real.write_bytes(bytes(128))
        (saves / "mono.eeprom").unlink()
        (saves / "mono.eeprom").symlink_to(real)
        with self.assertRaisesRegex(migration.MigrationError, "symlink"):
            migration.plan_migration(self.root)

        (saves / "mono.eeprom").unlink()
        (saves / "mono.eeprom").write_bytes(bytes(128))
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        linked = self.root / "Settings/agg23.WonderSwan/linked.json"
        linked.parent.mkdir(parents=True)
        linked.symlink_to(outside)
        with self.assertRaisesRegex(migration.MigrationError, "symlink"):
            migration.plan_migration(self.root)

    def test_rejects_malformed_duplicate_nonobject_and_oversized_json(self) -> None:
        path = self.root / "Settings/agg23.WonderSwan/value.json"
        path.parent.mkdir(parents=True)
        cases = (
            (b"{", "invalid JSON"),
            (b'{"a": 1, "a": 2}', "duplicate JSON field"),
            (b"[1, 2]", "top-level object"),
            (b'{"a": NaN}', "non-standard JSON constant"),
        )
        for payload, message in cases:
            with self.subTest(payload=payload):
                path.write_bytes(payload)
                with self.assertRaisesRegex(migration.MigrationError, message):
                    migration.plan_migration(self.root)
        path.write_bytes(b"{" + b" " * migration.MAX_JSON_FILE_BYTES + b"}")
        with self.assertRaisesRegex(migration.MigrationError, "exceeds"):
            migration.plan_migration(self.root)

    def test_ignores_macos_filesystem_metadata_in_json_trees(self) -> None:
        expected = self.add_json("Settings/agg23.WonderSwan/display.json")
        source = expected.parent
        (source / "._display.json").write_bytes(b"\x00\x05\x16\x07AppleDouble")
        (source / ".DS_Store").write_bytes(b"not JSON")
        metadata_tree = source / "._metadata/nested"
        metadata_tree.mkdir(parents=True)
        (metadata_tree / "malformed.json").write_bytes(b"{")

        plan = migration.plan_migration(self.root)

        settings = [managed for managed in plan.files if managed.kind == "Settings JSON"]
        self.assertEqual(len(settings), 1)
        self.assertEqual(
            settings[0].source,
            migration._relative("Settings", migration.SOURCE_CORE_ID, "display.json"),
        )
        self.assertEqual(settings[0].payload, expected.read_bytes())

    def test_malformed_nonmetadata_json_remains_fail_closed(self) -> None:
        malformed = self.root / "Settings/agg23.WonderSwan/.ordinary.json"
        malformed.parent.mkdir(parents=True)
        malformed.write_bytes(b"{")

        with self.assertRaisesRegex(migration.MigrationError, "invalid JSON"):
            migration.plan_migration(self.root)

    def test_json_tree_depth_and_entry_count_are_bounded(self) -> None:
        directory = self.root / "Presets/agg23.WonderSwan"
        deep = directory
        for index in range(3):
            deep /= f"d{index}"
        deep.mkdir(parents=True)
        (deep / "valid.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(migration, "MAX_JSON_DEPTH", 1):
            with self.assertRaisesRegex(migration.MigrationError, "maximum depth"):
                migration.plan_migration(self.root)

        for index in range(3):
            (directory / f"ignored-{index}.txt").write_text("x", encoding="utf-8")
        with mock.patch.object(migration, "MAX_TREE_ENTRIES", 2):
            with self.assertRaisesRegex(migration.MigrationError, "exceeds 2 entries"):
                migration.plan_migration(self.root)

    def test_json_file_and_byte_limits_cover_both_namespaces(self) -> None:
        self.add_json("Settings/agg23.WonderSwan/settings.json", {"value": "12"})
        self.add_json("Presets/agg23.WonderSwan/preset.json", {"value": "34"})
        with mock.patch.object(migration, "MAX_JSON_FILES", 1):
            with self.assertRaisesRegex(migration.MigrationError, "exceeds 1 files"):
                migration.plan_migration(self.root)
        with mock.patch.object(migration, "MAX_JSON_TOTAL_BYTES", 20):
            with self.assertRaisesRegex(migration.MigrationError, "exceeds 20 total bytes"):
                migration.plan_migration(self.root)

    def test_destination_symlink_or_case_collision_fails_closed(self) -> None:
        self.add_json("Settings/agg23.WonderSwan/settings.json")
        outside = self.root / "outside"
        outside.mkdir()
        settings = self.root / "Settings"
        settings.mkdir(exist_ok=True)
        (settings / "RegionallyFamous.SwanSong").symlink_to(
            outside, target_is_directory=True
        )
        with self.assertRaisesRegex(migration.MigrationError, "symlink"):
            migration.plan_migration(self.root)
        self.assertEqual(list(outside.iterdir()), [])

        (settings / "RegionallyFamous.SwanSong").unlink()
        (settings / "regionallyfamous.swansong").mkdir()
        with self.assertRaisesRegex(migration.MigrationError, "case-colliding"):
            migration.plan_migration(self.root)

    def test_source_names_cannot_create_case_colliding_destinations(self) -> None:
        files = [
            migration.MigrationFile(
                source=migration._relative("Settings", migration.SOURCE_CORE_ID, name),
                destination=migration._relative(
                    "Settings", migration.DESTINATION_CORE_ID, name
                ),
                payload=b"{}",
                kind="Settings JSON",
            )
            for name in ("A.json", "a.json")
        ]
        with mock.patch.object(migration, "_collect_json_files", return_value=files):
            with self.assertRaisesRegex(
                migration.MigrationError, "case-colliding destination"
            ):
                migration.plan_migration(self.root)

    def test_root_symlink_is_rejected(self) -> None:
        linked = Path(self.temporary.name) / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(migration.MigrationError, "nonsymlink"):
            migration.plan_migration(linked)

    def test_atomic_write_cleans_temporary_file_and_never_clobbers(self) -> None:
        target_directory = self.root / "atomic"
        target_directory.mkdir()
        destination = target_directory / "file.json"
        with mock.patch.object(
            migration, "_install_atomic_no_replace", side_effect=OSError("synthetic")
        ):
            with self.assertRaisesRegex(OSError, "synthetic"):
                migration._atomic_write_new(destination, b"{}")
        self.assertFalse(destination.exists())
        self.assertEqual(list(target_directory.iterdir()), [])

        destination.write_bytes(b"existing")
        with self.assertRaisesRegex(migration.MigrationError, "no-clobber"):
            migration._atomic_write_new(destination, b"replacement")
        self.assertEqual(destination.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
