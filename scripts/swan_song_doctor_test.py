#!/usr/bin/env python3
"""Mutation-heavy tests for the player-facing Swan Song SD doctor."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import unittest
from unittest import mock

import swan_song_doctor as doctor
from pocket_per_game_preset import PresetOptions, generate_presets


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
GUIDE = ROOT / "SWAN_SONG_DOCTOR.md"


class SwanSongDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-song-doctor-test-")
        self.sd = Path(self.temporary.name) / "POCKET"
        self.sd.mkdir()
        (self.sd / "Assets/wonderswan/common").mkdir(parents=True)
        (self.sd / "Cores").mkdir()
        shutil.copytree(
            DIST / "Cores/RegionallyFamous.SwanSong",
            self.sd / "Cores/RegionallyFamous.SwanSong",
        )
        shutil.copytree(DIST / "Platforms", self.sd / "Platforms")
        (self.sd / "Cores/RegionallyFamous.SwanSong/wonderswan.rev").write_bytes(
            b"test-rbf-r"
        )
        (self.sd / "Cores/RegionallyFamous.SwanSong/chip32.bin").write_bytes(
            b"test-chip32"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def codes(self, report: doctor.DoctorReport, severity: str | None = None) -> set[str]:
        return {
            item.code
            for item in report.findings
            if severity is None or item.severity == severity
        }

    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = doctor.main(["--sd-root", str(self.sd), *arguments])
        return status, stdout.getvalue(), stderr.getvalue()

    def snapshot(self) -> dict[str, tuple[bytes, int, int]]:
        result: dict[str, tuple[bytes, int, int]] = {}
        for path in sorted(self.sd.rglob("*")):
            if path.is_file() and not path.is_symlink():
                metadata = path.stat()
                result[path.relative_to(self.sd).as_posix()] = (
                    path.read_bytes(),
                    metadata.st_ino,
                    metadata.st_mtime_ns,
                )
        return result

    def add_game(self, relative: str = "Game.wsc") -> Path:
        path = self.sd / "Assets/wonderswan/common" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ROM bytes must never be inspected".ljust(64 * 1024, b"!"))
        return path

    def add_legacy(self, *, with_preset: bool = False) -> None:
        saves = self.sd / "Saves/wonderswan/agg23.WonderSwan"
        saves.mkdir(parents=True)
        (saves / "mono.eeprom").write_bytes(b"M" * 128)
        (saves / "color.eeprom").write_bytes(b"K" * 2048)
        settings = self.sd / "Settings/agg23.WonderSwan/Interact"
        settings.mkdir(parents=True)
        (settings / "interact_persist.json").write_text(
            '{"setting": 1}\n', encoding="utf-8"
        )
        if with_preset:
            preset = (
                self.sd
                / "Presets/agg23.WonderSwan/Interact/wonderswan/common/Game.json"
            )
            preset.parent.mkdir(parents=True)
            preset.write_text('{"interact": {"magic": "APF_VER_1"}}\n')

    def test_healthy_audit_reads_no_game_contents(self) -> None:
        game = self.add_game()
        original_reader = doctor._read_regular_snapshot_at

        def guarded(directory: int, name: str, **kwargs: object):
            self.assertNotEqual(name, game.name)
            return original_reader(directory, name, **kwargs)

        with mock.patch.object(
            doctor, "_read_regular_snapshot_at", side_effect=guarded
        ):
            report = doctor.audit_sd(self.sd)
        self.assertEqual(report.errors, 0)
        self.assertIn("core-identity", self.codes(report))
        self.assertIn("display-payloads", self.codes(report, "OK"))

    def test_default_cli_is_byte_inode_and_mtime_read_only(self) -> None:
        self.add_game("Folder/Game.ws")
        before = self.snapshot()
        status, output, error = self.invoke()
        self.assertEqual(status, 0, error)
        self.assertIn("Swan Song Doctor — READ ONLY", output)
        self.assertIn("No game contents were read", output)
        self.assertEqual(error, "")
        self.assertEqual(self.snapshot(), before)

    def test_shared_cartridge_save_warns_without_reading_and_names_safe_helper(self) -> None:
        self.add_game("Nested/Game.wsc")
        shared = self.sd / "Saves/wonderswan/common/Nested/Game.sav"
        shared.parent.mkdir(parents=True)
        shared.write_bytes(b"save contents must not be read")
        original_reader = doctor._read_regular_snapshot_at

        def guarded(directory: int, name: str, **kwargs: object):
            self.assertNotEqual(name, shared.name)
            return original_reader(directory, name, **kwargs)

        before = self.snapshot()
        with mock.patch.object(
            doctor, "_read_regular_snapshot_at", side_effect=guarded
        ):
            report = doctor.audit_sd(self.sd)
        finding = next(
            item for item in report.findings if item.code == "shared-cartridge-saves"
        )
        self.assertEqual(finding.severity, "WARN")
        self.assertIn("migrate_cartridge_save_namespace.py", finding.action)
        self.assertIn("Do not copy", finding.action)
        self.assertEqual(self.snapshot(), before)

        destination = (
            self.sd
            / "Saves/wonderswan/RegionallyFamous.SwanSong/Nested/Game.sav"
        )
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"independent")
        report = doctor.audit_sd(self.sd)
        finding = next(
            item for item in report.findings if item.code == "shared-cartridge-saves"
        )
        self.assertEqual(finding.severity, "INFO")

    def test_external_bios_files_are_not_required_or_inspected(self) -> None:
        report_without = doctor.audit_sd(self.sd)
        (self.sd / "Assets/wonderswan/common/bw.rom").write_bytes(b"X")
        (self.sd / "Assets/wonderswan/common/color.rom").write_bytes(b"Y")
        report_with = doctor.audit_sd(self.sd)
        self.assertEqual(report_without, report_with)
        self.assertFalse(any(item.code.startswith("bios-") for item in report_with.findings))

    def test_missing_foreign_and_duplicate_core_definitions_fail(self) -> None:
        core = self.sd / "Cores/RegionallyFamous.SwanSong/core.json"
        original = core.read_text()
        core.unlink()
        self.assertIn("definition-missing", self.codes(doctor.audit_sd(self.sd), "ERROR"))
        core.write_text(original.replace("RegionallyFamous", "ForeignAuthor"))
        self.assertIn("definition-contract", self.codes(doctor.audit_sd(self.sd), "ERROR"))
        core.write_text('{"core":{"magic":"APF_VER_1","magic":"APF_VER_1"}}')
        self.assertIn("definition-invalid", self.codes(doctor.audit_sd(self.sd), "ERROR"))

    def test_missing_and_empty_referenced_payloads_fail(self) -> None:
        bitstream = self.sd / "Cores/RegionallyFamous.SwanSong/wonderswan.rev"
        bitstream.unlink()
        self.assertIn("core-payload-missing", self.codes(doctor.audit_sd(self.sd), "ERROR"))
        bitstream.write_bytes(b"")
        self.assertIn("core-payload-invalid", self.codes(doctor.audit_sd(self.sd), "ERROR"))

    def test_missing_and_empty_user_visible_payloads_fail(self) -> None:
        for relative in doctor.USER_VISIBLE_PAYLOADS:
            with self.subTest(relative=relative, condition="missing"):
                path = self.sd / Path(*relative.parts)
                original = path.read_bytes()
                path.unlink()
                report = doctor.audit_sd(self.sd)
                finding = next(
                    item
                    for item in report.findings
                    if item.code == "display-payload-missing"
                    and item.path == relative.as_posix()
                )
                self.assertEqual(finding.severity, "ERROR")
                path.write_bytes(original)
            with self.subTest(relative=relative, condition="empty"):
                path = self.sd / Path(*relative.parts)
                original = path.read_bytes()
                path.write_bytes(b"")
                report = doctor.audit_sd(self.sd)
                finding = next(
                    item
                    for item in report.findings
                    if item.code == "display-payload-invalid"
                    and item.path == relative.as_posix()
                )
                self.assertEqual(finding.severity, "ERROR")
                path.write_bytes(original)

    def test_platform_missing_is_actionable_error(self) -> None:
        (self.sd / "Platforms/wonderswan.json").unlink()
        report = doctor.audit_sd(self.sd)
        self.assertIn("platform-missing", self.codes(report, "ERROR"))
        self.assertTrue(any("openFPGA" in item.message for item in report.findings))

    def test_nested_games_pc2_and_misplaced_assets_are_reported(self) -> None:
        self.add_game("Nested/Game.WS")
        (self.sd / "Assets/wonderswan/common/Challenge.pc2").write_bytes(b"x")
        misplaced = self.sd / "Assets/wonderswan/wrong/Moved.wsc"
        misplaced.parent.mkdir(parents=True)
        misplaced.write_bytes(b"x" * (64 * 1024))
        report = doctor.audit_sd(self.sd)
        self.assertIn("games-found", self.codes(report))
        self.assertIn("pc2-unsupported", self.codes(report, "WARN"))
        self.assertIn("game-misplaced", self.codes(report, "WARN"))

    def test_games_require_whole_64k_banks_within_slot_bounds(self) -> None:
        game = self.sd / "Assets/wonderswan/common/Geometry.wsc"
        for size in (64 * 1024, 2 * 64 * 1024, 16 * 1024 * 1024):
            with self.subTest(size=size, valid=True):
                game.touch()
                os.truncate(game, size)
                report = doctor.audit_sd(self.sd)
                self.assertNotIn("game-size", self.codes(report, "ERROR"))
                self.assertEqual(len(report.inventory.games_by_preset), 1)
        invalid_sizes = (
            0,
            1,
            64 * 1024 - 1,
            64 * 1024 + 1,
            96 * 1024,
            16 * 1024 * 1024 + 64 * 1024,
        )
        for size in invalid_sizes:
            with self.subTest(size=size, valid=False):
                game.touch()
                os.truncate(game, size)
                report = doctor.audit_sd(self.sd)
                self.assertIn("game-size", self.codes(report, "ERROR"))
                self.assertEqual(report.inventory.games_by_preset, {})

    def test_same_stem_ws_and_wsc_blocks_ambiguous_presets(self) -> None:
        self.add_game("Twin.ws")
        self.add_game("Twin.wsc")
        report = doctor.audit_sd(self.sd)
        self.assertIn("preset-name-collision", self.codes(report, "ERROR"))
        with self.assertRaisesRegex(doctor.DoctorError, "ambiguous"):
            doctor.plan_presets(report)

    def test_root_and_managed_symlinks_fail_closed(self) -> None:
        linked = Path(self.temporary.name) / "linked"
        linked.symlink_to(self.sd, target_is_directory=True)
        with self.assertRaisesRegex(doctor.DoctorError, "nonsymlink"):
            doctor.audit_sd(linked)

        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        link = self.sd / "Assets/wonderswan/common/link"
        link.symlink_to(outside, target_is_directory=True)
        report = doctor.audit_sd(self.sd)
        self.assertTrue(report.unsafe)
        self.assertIn("symlink", self.codes(report, "ERROR"))

    def test_case_collision_and_special_file_are_unsafe(self) -> None:
        assets = self.sd / "Assets"
        temporary_name = self.sd / "Assets-case-change"
        assets.rename(temporary_name)
        temporary_name.rename(self.sd / "assets")
        report = doctor.audit_sd(self.sd)
        self.assertIn("case-collision", self.codes(report, "ERROR"))
        (self.sd / "assets").rename(temporary_name)
        temporary_name.rename(assets)
        fifo = self.sd / "Assets/wonderswan/common/not-a-game"
        os.mkfifo(fifo)
        report = doctor.audit_sd(self.sd)
        self.assertIn("special-file", self.codes(report, "ERROR"))

    def test_valid_per_game_mirrors_and_missing_mirrors_are_optional(self) -> None:
        self.add_game("Folder/Game.wsc")
        missing = doctor.audit_sd(self.sd)
        self.assertEqual(missing.errors, 0)
        self.assertIn("--fix-presets", next(
            item.action for item in missing.findings if item.code == "preset-summary"
        ))
        generate_presets(
            sd_root=self.sd,
            asset="Folder/Game.wsc",
            definitions=self.sd / "Cores/RegionallyFamous.SwanSong",
            options=PresetOptions(),
        )
        complete = doctor.audit_sd(self.sd)
        summary = next(item for item in complete.findings if item.code == "preset-summary")
        self.assertIn("1 Interact, 1 Input", summary.message)
        self.assertNotIn("preset-invalid", self.codes(complete))

    def test_one_sided_preset_is_reported_without_unsafe_inference(self) -> None:
        self.add_game("Game.wsc")
        generate_presets(
            sd_root=self.sd,
            asset="Game.wsc",
            definitions=self.sd / "Cores/RegionallyFamous.SwanSong",
            options=PresetOptions(controls="inherit"),
        )
        report = doctor.audit_sd(self.sd)
        summary = next(item for item in report.findings if item.code == "preset-summary")
        self.assertIn("1 Interact-only", summary.message)
        self.assertIn("preset-one-sided", self.codes(report, "INFO"))
        self.assertEqual(doctor.plan_presets(report).items, ())

    def test_stale_interact_preset_missing_control_layout_fails(self) -> None:
        self.add_game()
        generated = generate_presets(
            sd_root=self.sd,
            asset="Game.wsc",
            definitions=self.sd / "Cores/RegionallyFamous.SwanSong",
        )
        document = json.loads(generated.interact_path.read_text())
        document["interact"]["variables"] = [
            item for item in document["interact"]["variables"] if item["id"] != 46
        ]
        generated.interact_path.write_text(json.dumps(document))
        self.assertIn("preset-invalid", self.codes(doctor.audit_sd(self.sd), "ERROR"))

    def test_orphan_and_wrong_root_presets_are_conservative_findings(self) -> None:
        orphan = (
            self.sd
            / "Presets/RegionallyFamous.SwanSong/Input/wonderswan/common/Future.json"
        )
        orphan.parent.mkdir(parents=True)
        source_input = self.sd / "Cores/RegionallyFamous.SwanSong/input.json"
        shutil.copy2(source_input, orphan)
        wrong = self.sd / "Presets/RegionallyFamous.SwanSong/Input/other/Game.json"
        wrong.parent.mkdir(parents=True)
        shutil.copy2(source_input, wrong)
        report = doctor.audit_sd(self.sd)
        self.assertIn("preset-orphan", self.codes(report, "INFO"))
        self.assertIn("preset-path", self.codes(report, "WARN"))

    def test_preset_fix_is_double_opt_in_and_preserves_settings(self) -> None:
        self.add_game("Folder/Game.wsc")
        settings = self.sd / "Settings/RegionallyFamous.SwanSong/keep.json"
        settings.parent.mkdir(parents=True)
        settings.write_bytes(b"host-owned")
        before = self.snapshot()
        status, output, error = self.invoke("--fix-presets")
        self.assertEqual(status, 0, error)
        self.assertIn("FIX PLAN ONLY: 2 new preset file(s)", output)
        self.assertEqual(self.snapshot(), before)

        status, output, error = self.invoke("--fix-presets", "--apply")
        self.assertEqual(status, 0, error)
        self.assertIn("SELECTED FIXES APPLIED", output)
        self.assertEqual(settings.read_bytes(), b"host-owned")
        self.assertTrue(
            (
                self.sd
                / "Presets/RegionallyFamous.SwanSong/Interact/"
                "wonderswan/common/Folder/Game.json"
            ).is_file()
        )

    def test_preset_apply_rejects_replaced_root_inode(self) -> None:
        self.add_game("Game.wsc")
        plan = doctor.plan_presets(doctor.audit_sd(self.sd))
        detached = Path(self.temporary.name) / "planned-root"
        self.sd.rename(detached)
        shutil.copytree(detached, self.sd)

        with self.assertRaisesRegex(doctor.DoctorError, "directory used for the preset plan"):
            doctor.apply_presets(plan)
        self.assertFalse(
            (
                self.sd
                / "Presets/RegionallyFamous.SwanSong/Interact/"
                "wonderswan/common/Game.json"
            ).exists()
        )
        self.assertFalse(
            (
                detached
                / "Presets/RegionallyFamous.SwanSong/Interact/"
                "wonderswan/common/Game.json"
            ).exists()
        )

    def test_definition_parent_swap_never_reads_outside_root(self) -> None:
        cores = self.sd / "Cores"
        detached = Path(self.temporary.name) / "detached-cores"
        outside = Path(self.temporary.name) / "outside-cores"
        shutil.copytree(cores, outside)
        marker = b'{"outside":"must not be read"}'
        (outside / "RegionallyFamous.SwanSong/audio.json").write_bytes(marker)
        original_json_reader = doctor._read_json_file
        original_snapshot_reader = doctor._read_regular_snapshot_at
        swapped = False
        outside_read = False

        def swap_before_definition_read(
            root_descriptor: int, relative: PurePosixPath
        ) -> dict[str, object]:
            nonlocal swapped
            if not swapped and relative.name == "audio.json":
                cores.rename(detached)
                cores.symlink_to(outside, target_is_directory=True)
                swapped = True
            return original_json_reader(root_descriptor, relative)

        def observe_snapshot(
            directory: int, name: str, *, maximum: int | None = None
        ) -> tuple[bytes, tuple[int, int]] | None:
            nonlocal outside_read
            snapshot = original_snapshot_reader(directory, name, maximum=maximum)
            if snapshot is not None and snapshot[0] == marker:
                outside_read = True
            return snapshot

        with mock.patch.object(
            doctor, "_read_json_file", swap_before_definition_read
        ), mock.patch.object(
            doctor, "_read_regular_snapshot_at", observe_snapshot
        ):
            report = doctor.audit_sd(self.sd)
        self.assertTrue(swapped)
        self.assertFalse(outside_read)
        self.assertTrue(report.unsafe)

    def test_apply_without_named_fix_is_rejected(self) -> None:
        before = self.snapshot()
        status, _output, error = self.invoke("--apply")
        self.assertEqual(status, 2)
        self.assertIn("requires an explicit fix flag", error)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_detection_and_plan_are_read_only(self) -> None:
        self.add_legacy()
        before = self.snapshot()
        report = doctor.audit_sd(self.sd)
        self.assertIn("legacy-console-saves", self.codes(report, "WARN"))
        self.assertIn("legacy-settings", self.codes(report, "WARN"))
        status, output, error = self.invoke("--migrate-legacy")
        self.assertEqual(status, 0, error)
        self.assertIn("FIX PLAN ONLY", output)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_apply_copies_without_moving_sources(self) -> None:
        self.add_legacy()
        source = self.sd / "Saves/wonderswan/agg23.WonderSwan/mono.eeprom"
        source_identity = (source.read_bytes(), source.stat().st_ino, source.stat().st_mtime_ns)
        status, output, error = self.invoke("--migrate-legacy", "--apply")
        self.assertEqual(status, 0, error)
        self.assertIn("SELECTED FIXES APPLIED", output)
        self.assertEqual(
            (source.read_bytes(), source.stat().st_ino, source.stat().st_mtime_ns),
            source_identity,
        )
        self.assertEqual(
            (self.sd / "Saves/wonderswan/RegionallyFamous.SwanSong/mono.eeprom").read_bytes(),
            b"M" * 128,
        )

    def test_different_legacy_destination_blocks_all_save_copies(self) -> None:
        self.add_legacy()
        destination = self.sd / "Saves/wonderswan/RegionallyFamous.SwanSong/mono.eeprom"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"D" * 128)
        status, _output, error = self.invoke("--migrate-legacy", "--apply")
        self.assertEqual(status, 2)
        self.assertIn("refusing to overwrite", error)
        self.assertEqual(destination.read_bytes(), b"D" * 128)
        self.assertFalse(
            (self.sd / "Saves/wonderswan/RegionallyFamous.SwanSong/color.eeprom").exists()
        )

    def test_overlapping_selected_fixes_fail_before_any_write(self) -> None:
        self.add_game()
        self.add_legacy(with_preset=True)
        before = self.snapshot()
        status, _output, error = self.invoke(
            "--migrate-legacy", "--fix-presets", "--apply"
        )
        self.assertEqual(status, 2)
        self.assertIn("target the same files", error)
        self.assertEqual(self.snapshot(), before)

    def test_unsafe_finding_blocks_every_selected_fix(self) -> None:
        self.add_game()
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_text("{}")
        link = self.sd / "Presets"
        link.symlink_to(outside)
        status, _output, error = self.invoke("--fix-presets", "--apply")
        self.assertEqual(status, 2)
        self.assertIn("unsafe path", error)
        self.assertFalse((self.sd / "Settings").exists())

    def test_json_output_is_stable_and_machine_readable(self) -> None:
        status, output, error = self.invoke("--json")
        self.assertEqual(status, 0, error)
        body = json.loads(output)["doctor"]
        self.assertEqual(body["magic"], "SWAN_SONG_DOCTOR_V1")
        self.assertEqual(body["mode"], "read-only")
        self.assertEqual(body["write_policy"], "no-content-or-namespace-writes")
        self.assertFalse(body["unsafe"])
        self.assertEqual(
            [item["code"] for item in body["findings"]],
            sorted(
                [item["code"] for item in body["findings"]],
                key=lambda code: next(
                    index
                    for index, item in enumerate(body["findings"])
                    if item["code"] == code
                ),
            ),
        )

    def test_guide_cites_official_docs_and_explains_content_safety(self) -> None:
        guide = GUIDE.read_text()
        for url in (
            "https://www.analogue.co/developer/docs/directories-and-sd-folder-structure",
            "https://www.analogue.co/developer/docs/core-definition-files/data-json",
            "https://www.analogue.co/developer/docs/core-definition-files/interact-json",
            "https://www.analogue.co/developer/docs/core-definition-files/input-json",
            "https://www.analogue.co/developer/docs/packaging-a-core",
        ):
            self.assertIn(url, guide)
        self.assertIn("does not require external BIOS files", guide)
        self.assertIn("Game contents are never", guide)
        self.assertIn("opened or hashed in any mode", guide)
        self.assertIn("may update access-time metadata", guide)
        self.assertIn("different destination is never\noverwritten", guide)


if __name__ == "__main__":
    unittest.main()
