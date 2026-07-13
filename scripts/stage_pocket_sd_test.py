#!/usr/bin/env python3
"""Focused safety and behavior tests for stage_pocket_sd.py."""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import shutil
import tempfile
import unittest
import zipfile

from package_core import create_package
from stage_pocket_sd import (
    ASSET_DIRECTORY,
    CORE_DIRECTORY,
    StagingError,
    apply_staging,
    main,
    plan_staging,
)


ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSEMBLY = ROOT / "src/support/chip32.asm"
ENCODED_IMAGE = ROOT / "src/support/chip32.bin.hex"


class StagePocketSDTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-song-sd-stage-test-")
        self.root = pathlib.Path(self.temporary.name)
        self.package = self.root / "development.zip"
        self.rbf = self.root / "ap_core.rbf"
        self.rbf.write_bytes(b"synthetic-development-bitstream")
        create_package(
            dist=ROOT / "dist",
            rbf=self.rbf,
            output=self.package,
            chip32_assembly=ASSEMBLY,
            chip32_encoded_image=ENCODED_IMAGE,
            release_policy=ROOT / "release-policy.json",
        )
        self.provenance = self.package.with_name(
            self.package.name + ".provenance.json"
        )
        self.bw = self.root / "owned-bw.bin"
        self.color = self.root / "owned-color.bin"
        self.bw.write_bytes(bytes(range(256)) * 16)
        self.color.write_bytes(bytes(reversed(range(256))) * 32)
        self.stage = self.root / "stage"
        self.stage.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def plan(self, **overrides):
        arguments = {
            "staging_dir": self.stage,
            "package": self.package,
            "provenance": self.provenance,
            "bw_bios": self.bw,
            "color_bios": self.color,
        }
        arguments.update(overrides)
        return plan_staging(**arguments)

    def copy_archive_with_entry(
        self,
        output: pathlib.Path,
        name: str,
        payload: bytes,
        *,
        mode: int = 0o100644,
    ) -> None:
        with zipfile.ZipFile(self.package) as source, zipfile.ZipFile(
            output, "w", zipfile.ZIP_STORED
        ) as destination:
            for info in source.infolist():
                destination.writestr(info, source.read(info.filename))
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            destination.writestr(info, payload)

    def test_dry_run_then_apply_preserves_unrelated_files(self) -> None:
        unrelated = self.stage / "keep-me.txt"
        unrelated.write_text("unrelated\n", encoding="utf-8")
        before = sorted(path.relative_to(self.stage) for path in self.stage.rglob("*"))
        plan = self.plan()
        self.assertEqual(
            before,
            sorted(path.relative_to(self.stage) for path in self.stage.rglob("*")),
        )
        self.assertGreater(len(plan.new_files), 2)
        self.assertEqual(plan.replaced_files, ())
        self.assertEqual(plan.unchanged_files, ())

        apply_staging(plan)
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "unrelated\n")
        self.assertEqual(
            (self.stage / pathlib.Path(*ASSET_DIRECTORY.parts) / "bw.rom").read_bytes(),
            self.bw.read_bytes(),
        )
        self.assertEqual(
            (
                self.stage / pathlib.Path(*ASSET_DIRECTORY.parts) / "color.rom"
            ).read_bytes(),
            self.color.read_bytes(),
        )
        self.assertTrue(
            (self.stage / pathlib.Path(*CORE_DIRECTORY.parts) / "core.json").is_file()
        )
        second = self.plan()
        self.assertEqual(second.new_files, ())
        self.assertEqual(second.replaced_files, ())
        self.assertEqual(len(second.unchanged_files), len(second.files))

    def test_apply_replaces_only_managed_files_atomically(self) -> None:
        plan = self.plan()
        apply_staging(plan)
        managed = self.stage / pathlib.Path(*CORE_DIRECTORY.parts) / "info.txt"
        managed.write_text("old managed contents\n", encoding="utf-8")
        unrelated = self.stage / "Cores/Another.Core/keep.bin"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_bytes(b"keep")
        replacement_plan = self.plan()
        self.assertIn(
            pathlib.PurePosixPath("Cores/agg23.WonderSwan/info.txt"),
            replacement_plan.replaced_files,
        )
        apply_staging(replacement_plan)
        self.assertNotEqual(managed.read_bytes(), b"old managed contents\n")
        self.assertEqual(unrelated.read_bytes(), b"keep")
        self.assertEqual(list(self.stage.rglob("*.tmp")), [])

    def test_bios_sizes_are_exact_and_input_symlinks_are_rejected(self) -> None:
        short = self.root / "short.bin"
        short.write_bytes(b"x" * 4095)
        with self.assertRaisesRegex(StagingError, "exactly 4096 bytes"):
            self.plan(bw_bios=short)
        long = self.root / "long.bin"
        long.write_bytes(b"x" * 8193)
        with self.assertRaisesRegex(StagingError, "exactly 8192 bytes"):
            self.plan(color_bios=long)
        linked = self.root / "linked-bw.bin"
        linked.symlink_to(self.bw)
        with self.assertRaisesRegex(StagingError, "must not be a symlink"):
            self.plan(bw_bios=linked)

    def test_package_and_provenance_symlinks_are_rejected(self) -> None:
        linked_package = self.root / "linked.zip"
        linked_package.symlink_to(self.package)
        with self.assertRaisesRegex(StagingError, "must not be a symlink"):
            self.plan(package=linked_package)
        linked_provenance = self.root / "linked.json"
        linked_provenance.symlink_to(self.provenance)
        with self.assertRaisesRegex(StagingError, "must not be a symlink"):
            self.plan(provenance=linked_provenance)

    def test_archive_traversal_symlinks_and_case_collisions_are_rejected(self) -> None:
        traversal = self.root / "traversal.zip"
        self.copy_archive_with_entry(traversal, "../escape", b"bad")
        with self.assertRaisesRegex(StagingError, "unsafe package path"):
            self.plan(package=traversal)

        symlink = self.root / "symlink.zip"
        self.copy_archive_with_entry(
            symlink,
            "Assets/wonderswan/common/link",
            b"../../outside",
            mode=0o120777,
        )
        with self.assertRaisesRegex(StagingError, "symlink or special file"):
            self.plan(package=symlink)

        collision = self.root / "collision.zip"
        self.copy_archive_with_entry(
            collision, "Platforms/WonderSwan.json", b"{}"
        )
        with self.assertRaisesRegex(StagingError, "case-colliding"):
            self.plan(package=collision)

    def test_provenance_hash_inventory_and_development_status_are_required(self) -> None:
        document = json.loads(self.provenance.read_text(encoding="utf-8"))
        body = document["package_provenance"]

        bad_hash = self.root / "bad-hash.json"
        body["archive"]["sha256"] = "0" * 64
        bad_hash.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(StagingError, "SHA-256"):
            self.plan(provenance=bad_hash)

        document = json.loads(self.provenance.read_text(encoding="utf-8"))
        document["package_provenance"]["release"] = True
        release = self.root / "release.json"
        release.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(StagingError, "development packages only"):
            self.plan(provenance=release)

        document = json.loads(self.provenance.read_text(encoding="utf-8"))
        document["package_provenance"]["entries"].pop(
            "Platforms/wonderswan.json"
        )
        inventory = self.root / "inventory.json"
        inventory.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(StagingError, "inventory"):
            self.plan(provenance=inventory)

    def test_stale_checkout_definitions_and_foreign_identity_are_rejected(self) -> None:
        stale_dist = self.root / "stale-dist"
        shutil.copytree(ROOT / "dist", stale_dist)
        platform_path = stale_dist / "Platforms/wonderswan.json"
        platform = json.loads(platform_path.read_text(encoding="utf-8"))
        platform["platform"]["name"] = "Old WonderSwan Identity"
        platform_path.write_text(json.dumps(platform), encoding="utf-8")
        stale_package = self.root / "stale.zip"
        create_package(
            dist=stale_dist,
            rbf=self.rbf,
            output=stale_package,
            chip32_assembly=ASSEMBLY,
            chip32_encoded_image=ENCODED_IMAGE,
            release_policy=ROOT / "release-policy.json",
        )
        with self.assertRaisesRegex(StagingError, "do not match the current checkout"):
            self.plan(
                package=stale_package,
                provenance=stale_package.with_name(
                    stale_package.name + ".provenance.json"
                ),
            )

        foreign_dist = self.root / "foreign-dist"
        shutil.copytree(ROOT / "dist", foreign_dist)
        core_path = foreign_dist / "Cores/agg23.WonderSwan/core.json"
        core = json.loads(core_path.read_text(encoding="utf-8"))
        core["core"]["metadata"]["url"] = "https://example.invalid/foreign"
        core_path.write_text(json.dumps(core), encoding="utf-8")
        foreign_package = self.root / "foreign.zip"
        create_package(
            dist=foreign_dist,
            rbf=self.rbf,
            output=foreign_package,
            chip32_assembly=ASSEMBLY,
            chip32_encoded_image=ENCODED_IMAGE,
            release_policy=ROOT / "release-policy.json",
        )
        with self.assertRaisesRegex(StagingError, "repository identity"):
            self.plan(
                package=foreign_package,
                provenance=foreign_package.with_name(
                    foreign_package.name + ".provenance.json"
                ),
            )

    def test_staging_symlink_and_case_collisions_fail_before_writing(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        linked_stage = self.root / "linked-stage"
        linked_stage.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(StagingError, "must not be a symlink"):
            self.plan(staging_dir=linked_stage)

        (self.stage / "Assets").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(StagingError, "must not be a symlink"):
            self.plan()
        self.assertEqual(list(outside.iterdir()), [])
        (self.stage / "Assets").unlink()

        (self.stage / "cores").mkdir()
        with self.assertRaisesRegex(StagingError, "case-colliding"):
            self.plan()

    def test_fake_macos_volume_requires_separate_write_acknowledgement(self) -> None:
        volumes = self.root / "Volumes"
        volume_stage = volumes / "POCKET"
        volume_stage.mkdir(parents=True)
        plan = self.plan(staging_dir=volume_stage, volumes_root=volumes)
        self.assertTrue(plan.is_volume)
        with self.assertRaisesRegex(StagingError, "--allow-volume"):
            apply_staging(plan)
        self.assertEqual(list(volume_stage.iterdir()), [])
        apply_staging(plan, allow_volume=True)
        self.assertTrue((volume_stage / "Cores/agg23.WonderSwan/core.json").is_file())

    def test_cli_defaults_to_read_only_and_prints_next_steps(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(
                [
                    "--staging-dir",
                    str(self.stage),
                    "--package",
                    str(self.package),
                    "--bw-bios",
                    str(self.bw),
                    "--color-bios",
                    str(self.color),
                ]
            )
        self.assertEqual(result, 0, stderr.getvalue())
        self.assertIn("VALIDATED ONLY", stdout.getvalue())
        self.assertIn("no files written", stdout.getvalue())
        self.assertIn("rerun with --apply", stdout.getvalue())
        self.assertEqual(list(self.stage.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
