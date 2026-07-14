#!/usr/bin/env python3
"""Adversarial tests for ROM-aware cartridge-save namespace migration."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import migrate_cartridge_save_namespace as migration


def make_rom(save_type: int, *, rtc: bool = False) -> bytes:
    body = bytearray(b"\x00" * (64 * 1024))
    footer = memoryview(body)[-16:]
    footer[0] = 0xEA
    footer[7] = 1
    footer[10] = 0
    footer[11] = save_type
    footer[12] = 0x04
    footer[13] = int(rtc)
    body[-2:] = (sum(memoryview(body)[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(body)


class CartridgeSaveNamespaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-song-cart-save-")
        self.root = Path(self.temporary.name) / "POCKET"
        (self.root / "Assets/wonderswan/common").mkdir(parents=True)
        (self.root / "Saves/wonderswan/common").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def add_case(
        self,
        relative: str,
        save_type: int,
        save: bytes | None,
        *,
        rtc: bool = False,
    ) -> tuple[Path, Path]:
        rom = self.root / "Assets/wonderswan/common" / relative
        inherited = (
            self.root
            / "Saves/wonderswan/common"
            / Path(relative).with_suffix(".sav")
        )
        rom.parent.mkdir(parents=True, exist_ok=True)
        inherited.parent.mkdir(parents=True, exist_ok=True)
        rom.write_bytes(make_rom(save_type, rtc=rtc))
        if save is not None:
            inherited.write_bytes(save)
        return rom, inherited

    def snapshot(self, *paths: Path) -> tuple[tuple[bytes, int, int], ...]:
        result = []
        for path in paths:
            metadata = path.stat()
            result.append((path.read_bytes(), metadata.st_ino, metadata.st_mtime_ns))
        return tuple(result)

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = migration.main(["--sd-root", str(self.root), *arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_nested_dry_run_then_apply_is_no_clobber_and_source_immutable(self) -> None:
        rom, source = self.add_case(
            "Folder/Deep/Game.wsc", 0x03, bytes(range(256)) * 512
        )
        before = self.snapshot(rom, source)
        status, output, error = self.invoke("--select", "Folder/Deep/Game.wsc")
        self.assertEqual(status, 0, error)
        self.assertIn("VALIDATED ONLY", output)
        self.assertIn("Saves/wonderswan/RegionallyFamous.SwanSong/Folder/Deep/Game.sav", output)
        destination = (
            self.root
            / "Saves/wonderswan/RegionallyFamous.SwanSong/Folder/Deep/Game.sav"
        )
        self.assertFalse(destination.exists())
        self.assertEqual(self.snapshot(rom, source), before)

        status, output, error = self.invoke(
            "--select", "Folder/Deep/Game.wsc", "--apply"
        )
        self.assertEqual(status, 0, error)
        self.assertIn("APPLIED", output)
        self.assertEqual(destination.read_bytes(), source.read_bytes())
        self.assertEqual(self.snapshot(rom, source), before)

        destination_before = self.snapshot(destination)
        status, output, error = self.invoke(
            "--select", "Folder/Deep/Game.wsc", "--apply"
        )
        self.assertEqual(status, 0, error)
        self.assertIn("1 identical", output)
        self.assertEqual(self.snapshot(destination), destination_before)
        self.assertEqual(self.snapshot(rom, source), before)

    def test_type01_legacy_expands_and_rtc_is_conditional(self) -> None:
        rtc = b"RT" + bytes(range(10))
        legacy = b"A" * 8192 + rtc
        self.add_case("NoRtc.ws", 0x01, legacy, rtc=False)
        self.add_case("Rtc.ws", 0x01, legacy, rtc=True)
        plan = migration.plan_migration(self.root, all_roms=True)
        by_name = {item.destination.name: item.payload for item in plan.files}
        self.assertEqual(by_name["NoRtc.sav"], b"A" * 8192 + bytes(24576))
        self.assertEqual(by_name["Rtc.sav"], b"A" * 8192 + bytes(24576) + rtc)

    def test_type10_and_type50_legacy_depad_with_conditional_rtc(self) -> None:
        rtc = b"RT" + b"z" * 10
        legacy = bytes(range(256)) * 8 + rtc
        self.add_case("Type10.ws", 0x10, legacy, rtc=False)
        self.add_case("Type50.wsc", 0x50, legacy, rtc=True)
        plan = migration.plan_migration(self.root, all_roms=True)
        by_name = {item.destination.name: item.payload for item in plan.files}
        self.assertEqual(by_name["Type10.sav"], legacy[:128])
        self.assertEqual(by_name["Type50.sav"], legacy[:1024] + rtc)

    def test_nonrtc_type20_and_sram_drop_only_rt_marked_agg_trailer(self) -> None:
        trailer = b"RT" + b"x" * 10
        self.add_case("Type20.ws", 0x20, b"E" * 2048 + trailer)
        self.add_case("Type02.ws", 0x02, b"S" * 32768 + trailer)
        plan = migration.plan_migration(self.root, all_roms=True)
        by_name = {item.destination.name: item.payload for item in plan.files}
        self.assertEqual(by_name["Type20.sav"], b"E" * 2048)
        self.assertEqual(by_name["Type02.sav"], b"S" * 32768)

        (self.root / "Saves/wonderswan/common/Type20.sav").write_bytes(
            b"E" * 2048 + b"NO" + b"x" * 10
        )
        with self.assertRaisesRegex(migration.MigrationError, "must begin with RT"):
            migration.plan_migration(self.root, selected=("Type20.ws",))

    def test_canonical_rtc_save_is_exact_and_opaque(self) -> None:
        canonical = b"E" * 2048 + b"NO" + b"opaque!!!!"
        self.assertEqual(len(canonical), 2060)
        self.add_case("Rtc20.ws", 0x20, canonical, rtc=True)
        plan = migration.plan_migration(self.root, selected=("Rtc20.ws",))
        self.assertEqual(plan.files[0].payload, canonical)
        self.assertEqual(plan.files[0].conversion, "canonical")

    def test_no_save_and_missing_save_are_reported_without_writes(self) -> None:
        _, stray = self.add_case("None.ws", 0x00, b"stray")
        self.add_case("Missing.wsc", 0x03, None)
        before = self.snapshot(stray)
        plan = migration.plan_migration(self.root, all_roms=True)
        self.assertEqual(len(plan.files), 0)
        self.assertEqual(len(plan.no_save), 1)
        self.assertEqual(len(plan.missing), 1)
        result = migration.apply_migration(plan, all_roms=True)
        self.assertEqual(result.copied, ())
        self.assertEqual(self.snapshot(stray), before)

    def test_wrong_extensions_are_ignored_and_rejected_when_selected(self) -> None:
        wrong = self.root / "Assets/wonderswan/common/Notes.txt"
        wrong.write_bytes(b"not a ROM")
        (self.root / "Saves/wonderswan/common/Notes.txt").write_bytes(b"do not touch")
        plan = migration.plan_migration(self.root, all_roms=True)
        self.assertEqual(plan.files, ())
        with self.assertRaisesRegex(migration.MigrationError, "must end in"):
            migration.plan_migration(self.root, selected=("Notes.txt",))

    def test_differing_destination_blocks_complete_plan(self) -> None:
        self.add_case("Game.ws", 0x10, b"A" * 128)
        destination = self.root / "Saves/wonderswan/RegionallyFamous.SwanSong/Game.sav"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"different")
        with self.assertRaisesRegex(migration.MigrationError, "refusing to overwrite"):
            migration.plan_migration(self.root, all_roms=True)
        self.assertEqual(destination.read_bytes(), b"different")

    def test_source_and_destination_symlinks_fail_closed(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "Game.ws").write_bytes(make_rom(0x10))
        linked = self.root / "Assets/wonderswan/common/Linked"
        linked.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(migration.MigrationError, "symlink"):
            migration.plan_migration(self.root, all_roms=True)
        linked.unlink()

        self.add_case("Game.ws", 0x10, b"A" * 128)
        destination_parent = self.root / "Saves/wonderswan/RegionallyFamous.SwanSong"
        destination_parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(migration.MigrationError, "symlink"):
            migration.plan_migration(self.root, all_roms=True)

    def test_shared_save_symlink_is_never_followed(self) -> None:
        _rom, source = self.add_case("Game.ws", 0x10, None)
        outside = Path(self.temporary.name) / "outside.sav"
        outside.write_bytes(b"A" * 128)
        source.symlink_to(outside)
        with self.assertRaisesRegex(migration.MigrationError, "symlink"):
            migration.plan_migration(self.root, selected=("Game.ws",))
        self.assertEqual(outside.read_bytes(), b"A" * 128)

    def test_broken_shared_save_symlink_is_not_misreported_as_missing(self) -> None:
        _rom, source = self.add_case("Game.ws", 0x10, None)
        source.symlink_to(Path(self.temporary.name) / "does-not-exist.sav")
        with self.assertRaisesRegex(migration.MigrationError, "symlink"):
            migration.plan_migration(self.root, selected=("Game.ws",))

    def test_late_second_destination_conflict_rolls_back_only_first_new_inode(self) -> None:
        _rom_a, source_a = self.add_case("A.ws", 0x10, b"A" * 128)
        _rom_b, source_b = self.add_case("B.ws", 0x10, b"B" * 128)
        source_before = self.snapshot(source_a, source_b)
        plan = migration.plan_migration(self.root, all_roms=True)
        destination_a = (
            self.root / "Saves/wonderswan/RegionallyFamous.SwanSong/A.sav"
        )
        destination_b = (
            self.root / "Saves/wonderswan/RegionallyFamous.SwanSong/B.sav"
        )
        original_writer = migration._atomic_write_new_at
        calls = 0

        def conflict_on_second(
            parent_descriptor: int, name: str, payload: bytes
        ) -> tuple[int, int]:
            nonlocal calls
            calls += 1
            if calls == 2:
                descriptor = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644,
                    dir_fd=parent_descriptor,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(b"late independent destination")
            return original_writer(parent_descriptor, name, payload)

        with mock.patch.object(
            migration, "_atomic_write_new_at", side_effect=conflict_on_second
        ):
            with self.assertRaisesRegex(migration.MigrationError, "no-clobber"):
                migration.apply_migration(plan, all_roms=True)

        self.assertFalse(destination_a.exists())
        self.assertEqual(destination_b.read_bytes(), b"late independent destination")
        self.assertEqual(self.snapshot(source_a, source_b), source_before)

    def test_parent_symlink_swap_cannot_redirect_apply_outside_sd_root(self) -> None:
        rom, source = self.add_case("Game.ws", 0x10, b"A" * 128)
        before = self.snapshot(rom, source)
        plan = migration.plan_migration(self.root, selected=("Game.ws",))
        destination_parent = (
            self.root / "Saves/wonderswan/RegionallyFamous.SwanSong"
        )
        outside = Path(self.temporary.name) / "outside"
        detached = Path(self.temporary.name) / "detached-original-parent"
        outside.mkdir()
        original_writer = migration._atomic_write_new_at

        def swap_parent_then_write(
            parent_descriptor: int, name: str, payload: bytes
        ) -> tuple[int, int]:
            destination_parent.rename(detached)
            destination_parent.symlink_to(outside, target_is_directory=True)
            return original_writer(parent_descriptor, name, payload)

        with mock.patch.object(
            migration, "_atomic_write_new_at", side_effect=swap_parent_then_write
        ):
            with self.assertRaisesRegex(
                migration.MigrationError, "unsafe|identity|symlink"
            ):
                migration.apply_migration(plan, selected=("Game.ws",))

        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(list(detached.iterdir()), [])
        self.assertTrue(destination_parent.is_symlink())
        self.assertEqual(self.snapshot(rom, source), before)

    def test_rollback_never_deletes_an_inode_that_replaced_its_created_file(self) -> None:
        self.add_case("A.ws", 0x10, b"A" * 128)
        self.add_case("B.ws", 0x10, b"B" * 128)
        plan = migration.plan_migration(self.root, all_roms=True)
        destination_parent = (
            self.root / "Saves/wonderswan/RegionallyFamous.SwanSong"
        )
        destination_a = destination_parent / "A.sav"
        destination_b = destination_parent / "B.sav"
        independent = b"independent replacement"
        original_writer = migration._atomic_write_new_at
        calls = 0

        def replace_first_then_conflict_second(
            parent_descriptor: int, name: str, payload: bytes
        ) -> tuple[int, int]:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.unlink("A.sav", dir_fd=parent_descriptor)
                a_descriptor = os.open(
                    "A.sav",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644,
                    dir_fd=parent_descriptor,
                )
                with os.fdopen(a_descriptor, "wb") as stream:
                    stream.write(independent)
                b_descriptor = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644,
                    dir_fd=parent_descriptor,
                )
                with os.fdopen(b_descriptor, "wb") as stream:
                    stream.write(b"late conflict")
            return original_writer(parent_descriptor, name, payload)

        with mock.patch.object(
            migration,
            "_atomic_write_new_at",
            side_effect=replace_first_then_conflict_second,
        ):
            with self.assertRaisesRegex(
                migration.MigrationError, "rollback left.*A.sav"
            ):
                migration.apply_migration(plan, all_roms=True)

        self.assertEqual(destination_a.read_bytes(), independent)
        self.assertEqual(destination_b.read_bytes(), b"late conflict")
        self.assertEqual(
            sorted(path.name for path in destination_parent.iterdir()),
            ["A.sav", "B.sav"],
        )

    def test_malformed_rom_and_unrecognized_save_sizes_fail(self) -> None:
        rom, source = self.add_case("Bad.ws", 0x03, b"x")
        broken = bytearray(rom.read_bytes())
        broken[42] ^= 1
        rom.write_bytes(broken)
        with self.assertRaisesRegex(migration.MigrationError, "checksum mismatch"):
            migration.plan_migration(self.root, all_roms=True)
        rom.write_bytes(make_rom(0x03))
        with self.assertRaisesRegex(migration.MigrationError, "unrecognized save layout"):
            migration.plan_migration(self.root, all_roms=True)
        self.assertEqual(source.read_bytes(), b"x")

    def test_same_stem_roms_and_case_collisions_are_rejected(self) -> None:
        self.add_case("Twin.ws", 0x10, b"A" * 128)
        self.add_case("Twin.wsc", 0x10, b"A" * 128)
        with self.assertRaisesRegex(migration.MigrationError, "same cartridge-save destination"):
            migration.plan_migration(self.root, all_roms=True)

        (self.root / "Assets/wonderswan/common/Twin.wsc").unlink()
        (self.root / "Assets/wonderswan/common/twin.WSC").write_bytes(make_rom(0x10))
        with self.assertRaisesRegex(migration.MigrationError, "case-colliding"):
            migration.plan_migration(self.root, all_roms=True)

    def test_source_change_between_plan_and_apply_is_detected(self) -> None:
        _, source = self.add_case("Game.ws", 0x10, b"A" * 128)
        plan = migration.plan_migration(self.root, all_roms=True)
        source.write_bytes(b"B" * 128)
        with self.assertRaisesRegex(migration.MigrationError, "source changed"):
            migration.apply_migration(plan, all_roms=True)

    def test_cli_requires_explicit_selection_and_apply_alone_never_implies_all(self) -> None:
        self.add_case("Game.ws", 0x10, b"A" * 128)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            migration.main(["--sd-root", str(self.root), "--apply"])
        destination = self.root / "Saves/wonderswan/RegionallyFamous.SwanSong/Game.sav"
        self.assertFalse(destination.exists())

    def test_path_traversal_and_absolute_selection_are_rejected(self) -> None:
        for value in ("../Game.ws", "/Game.ws", "Folder\\Game.ws"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(migration.MigrationError, "unsafe selected"):
                    migration.plan_migration(self.root, selected=(value,))


if __name__ == "__main__":
    unittest.main()
