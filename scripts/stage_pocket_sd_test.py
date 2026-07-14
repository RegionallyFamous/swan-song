#!/usr/bin/env python3
"""Focused safety and behavior tests for stage_pocket_sd.py."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

import stage_pocket_sd as staging
from package_core import (
    AUDIT_REQUIRED_TRUE_GATES,
    RELEASE_EVIDENCE_V2,
    RELEASE_QUARTUS_VERSION,
    create_package,
    validate_release_policy,
)
from package_validator import validate_distribution
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
EXPECTED_PLAN_FILE_COUNT = 23


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

    @staticmethod
    def tree_snapshot(root: pathlib.Path) -> tuple[set[str], dict[str, bytes]]:
        directories = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_dir() and not path.is_symlink()
        }
        files = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        return directories, files

    def release_fixture(
        self,
    ) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, str, str, str, str]:
        release_dist = self.root / "release-dist"
        shutil.copytree(ROOT / "dist", release_dist)
        manifest_path = (
            release_dist
            / "Cores/RegionallyFamous.SwanSong/LICENSE-MANIFEST.json"
        )
        manifest_document = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = manifest_document["license_manifest"]
        for component in manifest["components"]:
            if component["review_status"] == "review_required":
                component["review_status"] = "documented"
                component["blocker"] = None
                if component["license_expression"] == "NOASSERTION":
                    component["license_expression"] = "LicenseRef-Test-Reviewed"
        for requirement in manifest["requirements"]:
            requirement["review_status"] = "documented"
            requirement["blocker"] = None
        manifest["release_gate"] = {
            "licensing_review_complete": True,
            "unresolved_ids": [],
        }
        manifest_path.write_text(
            json.dumps(manifest_document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        definition = validate_distribution(release_dist)
        package = self.root / definition.recommended_archive_name
        create_package(
            dist=release_dist,
            rbf=self.rbf,
            output=package,
            chip32_assembly=ASSEMBLY,
            chip32_encoded_image=ENCODED_IMAGE,
            release_policy=ROOT / "release-policy.json",
        )
        provenance = package.with_name(package.name + ".provenance.json")
        policy_document = json.loads((ROOT / "release-policy.json").read_text(encoding="utf-8"))
        policy_document["release_policy"]["authorization"][
            "distribution_and_licensing_authorized"
        ] = True
        authorized_policy = self.root / "authorized-release-policy.json"
        authorized_policy.write_text(
            json.dumps(policy_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verified_policy = validate_release_policy(authorized_policy, definition)
        commit = "a" * 40
        digest = "b" * 64
        document = json.loads(provenance.read_text(encoding="utf-8"))
        body = document["package_provenance"]
        body["release"] = True
        body["build_evidence"] = {
            "magic": RELEASE_EVIDENCE_V2,
            "manifest_filename": "release-evidence.json",
            "manifest_size": 1,
            "manifest_sha256": digest,
            "source_commit": commit,
            "source_date_epoch": 1,
            "quartus_version": RELEASE_QUARTUS_VERSION,
            "build_id": {
                "filename": "build_id.mif",
                "size": 1,
                "sha256": digest,
            },
            "reports": {
                kind: {
                    "filename": f"output_files/ap_core.{kind}.rpt",
                    "size": 1,
                    "sha256": digest,
                }
                for kind in ("flow", "fit", "sta")
            },
            "quartus_audit": {
                "filename": "quartus-audit-candidate.json",
                "size": 1,
                "sha256": digest,
                "magic": "SWAN_SONG_QUARTUS_AUDIT_V1",
                "audit_pass": True,
                "source_commit": commit,
                "source_date_epoch": 1,
                "artifact_count": 1,
                "required_candidate_gates": {
                    gate: True for gate in sorted(AUDIT_REQUIRED_TRUE_GATES)
                },
            },
            "gates": {gate: True for gate in sorted(staging.RELEASE_GATE_NAMES)},
        }
        tracked: dict[str, dict[str, object]] = {}
        directories: list[str] = []
        for path in sorted(release_dist.rglob("*")):
            relative = "dist/" + path.relative_to(release_dist).as_posix()
            if path.is_dir():
                directories.append(relative)
                continue
            payload = path.read_bytes()
            tracked[relative] = {
                "git_blob": hashlib.sha1(
                    b"blob " + str(len(payload)).encode() + b"\0" + payload
                ).hexdigest(),
                "mode": "100644",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        for relative, path in (
            ("src/support/chip32.asm", ASSEMBLY),
            ("src/support/chip32.bin.hex", ENCODED_IMAGE),
        ):
            payload = path.read_bytes()
            tracked[relative] = {
                "git_blob": hashlib.sha1(
                    b"blob " + str(len(payload)).encode() + b"\0" + payload
                ).hexdigest(),
                "mode": "100644",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        body["source_inputs"] = {
            "magic": staging.RELEASE_SOURCE_INPUTS_V1,
            "repository": staging.EXPECTED_REPOSITORY,
            "source_commit": commit,
            "source_tree": "c" * 40,
            "dist_directory": "dist",
            "dist_directories": directories,
            "chip32_assembly": "src/support/chip32.asm",
            "chip32_encoded_image": "src/support/chip32.bin.hex",
            "tracked_files": tracked,
            "raw_rbf": body["raw_rbf"],
        }
        body["release_policy"] = verified_policy
        provenance.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        package_digest = hashlib.sha256(package.read_bytes()).hexdigest()
        provenance_digest = hashlib.sha256(provenance.read_bytes()).hexdigest()
        return (
            package,
            provenance,
            authorized_policy,
            definition.version,
            commit,
            package_digest,
            provenance_digest,
        )

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
            pathlib.PurePosixPath("Cores/RegionallyFamous.SwanSong/info.txt"),
            replacement_plan.replaced_files,
        )
        apply_staging(replacement_plan)
        self.assertNotEqual(managed.read_bytes(), b"old managed contents\n")
        self.assertEqual(unrelated.read_bytes(), b"keep")
        self.assertEqual(list(self.stage.rglob("*.tmp")), [])

    def test_apply_rolls_back_after_every_atomic_write_boundary(self) -> None:
        original_atomic_write = staging._atomic_write_at
        for fail_at in range(1, EXPECTED_PLAN_FILE_COUNT + 1):
            with self.subTest(fail_at=fail_at):
                stage = self.root / f"transaction-{fail_at}"
                managed_parent = stage / "Cores/RegionallyFamous.SwanSong"
                managed_parent.mkdir(parents=True)
                (managed_parent / "audio.json").write_bytes(b"older managed audio")
                unrelated = stage / "Cores/Another.Core/keep.bin"
                unrelated.parent.mkdir(parents=True)
                unrelated.write_bytes(b"unrelated")
                initial_plan = self.plan(staging_dir=stage)
                for managed_file in initial_plan.files:
                    (stage / pathlib.Path(*managed_file.relative.parts)).parent.mkdir(
                        parents=True, exist_ok=True
                    )
                before = self.tree_snapshot(stage)
                plan = self.plan(staging_dir=stage)
                self.assertEqual(len(plan.files), EXPECTED_PLAN_FILE_COUNT)
                calls = 0

                def fail_after_replace(
                    directory: int,
                    name: str,
                    payload: bytes,
                    *,
                    mode: int = 0o644,
                    expected_identity=staging._UNCONDITIONAL_REPLACE,
                    on_replace=None,
                ) -> tuple[int, int]:
                    nonlocal calls
                    identity = original_atomic_write(
                        directory,
                        name,
                        payload,
                        mode=mode,
                        expected_identity=expected_identity,
                        on_replace=on_replace,
                    )
                    calls += 1
                    if calls == fail_at:
                        raise OSError(f"injected failure after write {fail_at}")
                    return identity

                with mock.patch.object(
                    staging, "_atomic_write_at", fail_after_replace
                ):
                    with self.assertRaisesRegex(OSError, "injected failure"):
                        apply_staging(plan)
                self.assertEqual(self.tree_snapshot(stage), before)
                self.assertEqual(list(stage.rglob("*.tmp")), [])

    def test_late_parent_swap_fails_and_rolls_back_detached_tree(self) -> None:
        plan = self.plan()
        detached = self.root / "late-detached-cores"
        replacement = self.stage / "Cores"
        original_atomic_write = staging._atomic_write_at
        swapped = False

        def swap_after_snapshot(
            directory: int,
            name: str,
            payload: bytes,
            *,
            mode: int = 0o644,
            expected_identity=staging._UNCONDITIONAL_REPLACE,
            on_replace=None,
        ) -> tuple[int, int]:
            nonlocal swapped
            if not swapped:
                replacement.rename(detached)
                replacement.mkdir()
                swapped = True
            return original_atomic_write(
                directory,
                name,
                payload,
                mode=mode,
                expected_identity=expected_identity,
                on_replace=on_replace,
            )

        with mock.patch.object(
            staging, "_atomic_write_at", swap_after_snapshot
        ):
            with self.assertRaisesRegex(StagingError, "detached|identity changed"):
                apply_staging(plan)
        self.assertTrue(swapped)
        self.assertTrue(replacement.is_dir())
        self.assertEqual(list(replacement.iterdir()), [])
        self.assertTrue(detached.is_dir())
        self.assertEqual(
            [path for path in detached.rglob("*") if path.is_file()], []
        )
        self.assertTrue((detached / "RegionallyFamous.SwanSong").is_dir())

    def test_rollback_never_removes_identical_concurrent_replacement_inode(self) -> None:
        managed_parent = self.stage / "Cores/RegionallyFamous.SwanSong"
        managed_parent.mkdir(parents=True)
        managed = managed_parent / "audio.json"
        managed.write_bytes(b"older managed audio")
        plan = self.plan()
        target_payload = next(
            item.payload
            for item in plan.files
            if item.relative.as_posix()
            == "Cores/RegionallyFamous.SwanSong/audio.json"
        )
        original_atomic_write = staging._atomic_write_at
        replacement_identity: tuple[int, int] | None = None
        replaced = False

        def replace_with_identical_inode(
            directory: int,
            name: str,
            payload: bytes,
            *,
            mode: int = 0o644,
            expected_identity=staging._UNCONDITIONAL_REPLACE,
            on_replace=None,
        ) -> tuple[int, int]:
            nonlocal replacement_identity, replaced
            identity = original_atomic_write(
                directory,
                name,
                payload,
                mode=mode,
                expected_identity=expected_identity,
                on_replace=on_replace,
            )
            if not replaced and name == "audio.json":
                replacement_identity = original_atomic_write(
                    directory,
                    name,
                    payload,
                    expected_identity=staging._UNCONDITIONAL_REPLACE,
                )
                replaced = True
                raise OSError("concurrent identical replacement")
            return identity

        with mock.patch.object(
            staging, "_atomic_write_at", replace_with_identical_inode
        ):
            with self.assertRaisesRegex(StagingError, "rollback report"):
                apply_staging(plan)
        self.assertTrue(replaced)
        self.assertEqual(managed.read_bytes(), target_payload)
        metadata = managed.stat()
        self.assertEqual(
            (metadata.st_dev, metadata.st_ino), replacement_identity
        )

    def test_conditional_publish_preserves_concurrent_create_after_absent_snapshot(self) -> None:
        plan = self.plan()
        for managed_file in plan.files:
            (self.stage / pathlib.Path(*managed_file.relative.parts)).parent.mkdir(
                parents=True, exist_ok=True
            )
        target = self.stage / "Cores/RegionallyFamous.SwanSong/audio.json"
        original_rename = staging._rename_noreplace
        actor_identity: tuple[int, int] | None = None
        injected = False

        def create_before_publish(
            source_directory: int,
            source_name: str,
            destination_directory: int,
            destination_name: str,
        ) -> None:
            nonlocal actor_identity, injected
            if destination_name == "audio.json" and source_name.endswith(".tmp") and not injected:
                target.write_bytes(b"concurrent creator")
                metadata = target.stat()
                actor_identity = (metadata.st_dev, metadata.st_ino)
                injected = True
            original_rename(
                source_directory,
                source_name,
                destination_directory,
                destination_name,
            )

        with mock.patch.object(staging, "_rename_noreplace", create_before_publish):
            with self.assertRaisesRegex(StagingError, "FileExistsError|rollback conflict"):
                apply_staging(plan)
        self.assertTrue(injected)
        self.assertEqual(target.read_bytes(), b"concurrent creator")
        metadata = target.stat()
        self.assertEqual((metadata.st_dev, metadata.st_ino), actor_identity)

    def test_conditional_publish_preserves_replacement_after_existing_snapshot(self) -> None:
        target = self.stage / "Cores/RegionallyFamous.SwanSong/audio.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"original before plan")
        plan = self.plan()
        original_quarantine = staging._rename_to_unique
        actor_identity: tuple[int, int] | None = None
        injected = False

        def replace_before_claim(directory: int, name: str, purpose: str) -> str:
            nonlocal actor_identity, injected
            if name == "audio.json" and purpose == "original" and not injected:
                actor = target.with_name("actor.tmp")
                actor.write_bytes(b"concurrent replacement")
                os.replace(actor, target)
                metadata = target.stat()
                actor_identity = (metadata.st_dev, metadata.st_ino)
                injected = True
            return original_quarantine(directory, name, purpose)

        with mock.patch.object(staging, "_rename_to_unique", replace_before_claim):
            with self.assertRaisesRegex(StagingError, "changed after snapshot"):
                apply_staging(plan)
        self.assertTrue(injected)
        self.assertEqual(target.read_bytes(), b"concurrent replacement")
        metadata = target.stat()
        self.assertEqual((metadata.st_dev, metadata.st_ino), actor_identity)

    def test_rollback_retains_created_directories_and_concurrent_replacement(self) -> None:
        plan = self.plan()
        original_directory = self.root / "prepared-images-directory"
        actor_directory = self.stage / "Platforms/_images"
        actor_identity: tuple[int, int] | None = None
        injected = False

        def fail_after_directory_replacement(
            directory: int,
            name: str,
            payload: bytes,
            *,
            mode: int = 0o644,
            expected_identity=staging._UNCONDITIONAL_REPLACE,
            on_replace=None,
        ) -> tuple[int, int]:
            nonlocal actor_identity, injected
            if not injected:
                actor_directory.rename(original_directory)
                actor_directory.mkdir()
                metadata = actor_directory.stat()
                actor_identity = (metadata.st_dev, metadata.st_ino)
                injected = True
            raise OSError("failure before first publication")

        with mock.patch.object(
            staging, "_atomic_write_at", fail_after_directory_replacement
        ):
            with self.assertRaisesRegex(
                StagingError, "retained created directory after rollback"
            ):
                apply_staging(plan)
        self.assertTrue(original_directory.is_dir())
        self.assertTrue(actor_directory.is_dir())
        metadata = actor_directory.stat()
        self.assertEqual((metadata.st_dev, metadata.st_ino), actor_identity)

    def test_postcheck_detects_changed_unchanged_file_and_preserves_actor_inode(self) -> None:
        apply_staging(self.plan())
        changed = self.stage / "Cores/RegionallyFamous.SwanSong/audio.json"
        changed.write_bytes(b"force one managed replacement")
        unchanged = self.stage / "Cores/RegionallyFamous.SwanSong/core.json"
        unchanged_payload = unchanged.read_bytes()
        plan = self.plan()
        original_atomic_write = staging._atomic_write_at
        actor_identity: tuple[int, int] | None = None
        injected = False

        def replace_unchanged_after_publish(
            directory: int,
            name: str,
            payload: bytes,
            *,
            mode: int = 0o644,
            expected_identity=staging._UNCONDITIONAL_REPLACE,
            on_replace=None,
        ) -> tuple[int, int]:
            nonlocal actor_identity, injected
            identity = original_atomic_write(
                directory,
                name,
                payload,
                mode=mode,
                expected_identity=expected_identity,
                on_replace=on_replace,
            )
            if name == "audio.json" and not injected:
                directory_fd = os.open(unchanged.parent, staging._directory_flags())
                try:
                    actor_identity = original_atomic_write(
                        directory_fd,
                        unchanged.name,
                        unchanged_payload,
                        expected_identity=staging._UNCONDITIONAL_REPLACE,
                    )
                finally:
                    os.close(directory_fd)
                injected = True
            return identity

        with mock.patch.object(
            staging, "_atomic_write_at", replace_unchanged_after_publish
        ):
            with self.assertRaisesRegex(StagingError, "unchanged managed destination"):
                apply_staging(plan)
        self.assertTrue(injected)
        self.assertEqual(changed.read_bytes(), b"force one managed replacement")
        self.assertEqual(unchanged.read_bytes(), unchanged_payload)
        metadata = unchanged.stat()
        self.assertEqual((metadata.st_dev, metadata.st_ino), actor_identity)

    def test_rollback_restores_original_inode_mode_and_contents(self) -> None:
        target = self.stage / "Cores/RegionallyFamous.SwanSong/audio.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"private original")
        target.chmod(0o600)
        original_metadata = target.stat()
        original_identity = (original_metadata.st_dev, original_metadata.st_ino)
        plan = self.plan()
        for managed_file in plan.files:
            (self.stage / pathlib.Path(*managed_file.relative.parts)).parent.mkdir(
                parents=True, exist_ok=True
            )
        original_atomic_write = staging._atomic_write_at
        failed = False

        def fail_after_publication(
            directory: int,
            name: str,
            payload: bytes,
            *,
            mode: int = 0o644,
            expected_identity=staging._UNCONDITIONAL_REPLACE,
            on_replace=None,
        ) -> tuple[int, int]:
            nonlocal failed
            identity = original_atomic_write(
                directory,
                name,
                payload,
                mode=mode,
                expected_identity=expected_identity,
                on_replace=on_replace,
            )
            if name == "audio.json" and not failed:
                failed = True
                raise OSError("failure after publication")
            return identity

        with mock.patch.object(staging, "_atomic_write_at", fail_after_publication):
            with self.assertRaises(OSError):
                apply_staging(plan)
        metadata = target.stat()
        self.assertEqual(target.read_bytes(), b"private original")
        self.assertEqual((metadata.st_dev, metadata.st_ino), original_identity)
        self.assertEqual(metadata.st_mode & 0o777, 0o600)

    def test_directory_entry_sync_and_native_no_clobber_requirement(self) -> None:
        plan = self.plan()
        original_sync = staging._fsync_directory
        synced: list[int] = []

        def record_sync(directory: int) -> bool:
            synced.append(directory)
            return original_sync(directory)

        with mock.patch.object(staging, "_fsync_directory", record_sync):
            apply_staging(plan)
        self.assertGreaterEqual(len(synced), len(plan.files) + 5)

        class NoNativeRename:
            pass

        with mock.patch.object(staging.ctypes, "CDLL", return_value=NoNativeRename()):
            with self.assertRaisesRegex(StagingError, "native atomic no-clobber"):
                staging._rename_noreplace(-1, "source", -1, "destination")

    def test_directory_sync_failure_after_quarantine_still_restores_original(self) -> None:
        target = self.stage / "Cores/RegionallyFamous.SwanSong/audio.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"original before directory sync failure")
        original_metadata = target.stat()
        original_identity = (original_metadata.st_dev, original_metadata.st_ino)
        plan = self.plan()
        for managed_file in plan.files:
            (self.stage / pathlib.Path(*managed_file.relative.parts)).parent.mkdir(
                parents=True, exist_ok=True
            )
        original_sync = staging._fsync_directory
        injected = False

        def fail_after_original_quarantine(directory: int) -> bool:
            nonlocal injected
            if not injected and any(
                name.startswith(".swan-song-original-") for name in os.listdir(directory)
            ):
                injected = True
                raise OSError("injected directory sync failure")
            return original_sync(directory)

        with mock.patch.object(
            staging, "_fsync_directory", fail_after_original_quarantine
        ):
            with self.assertRaisesRegex(OSError, "directory sync failure"):
                apply_staging(plan)
        self.assertTrue(injected)
        self.assertEqual(
            target.read_bytes(), b"original before directory sync failure"
        )
        metadata = target.stat()
        self.assertEqual((metadata.st_dev, metadata.st_ino), original_identity)

    def test_root_swap_during_plan_is_rejected_by_opened_identity(self) -> None:
        outside = self.root / "plan-swap-outside"
        outside.mkdir()
        detached = self.root / "plan-swap-original"
        original_resolve = pathlib.Path.resolve
        swapped = False

        def swap_before_resolve(path: pathlib.Path, *args, **kwargs):
            nonlocal swapped
            if path == self.stage and not swapped:
                self.stage.rename(detached)
                self.stage.symlink_to(outside, target_is_directory=True)
                swapped = True
            return original_resolve(path, *args, **kwargs)

        try:
            with mock.patch.object(pathlib.Path, "resolve", swap_before_resolve):
                with self.assertRaisesRegex(StagingError, "identity changed"):
                    self.plan()
            self.assertTrue(swapped)
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            if self.stage.is_symlink():
                self.stage.unlink()
            if detached.exists():
                detached.rename(self.stage)

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

    def test_inputs_are_read_from_single_no_follow_snapshots(self) -> None:
        protected = {self.package, self.provenance, self.bw, self.color}
        original_read_bytes = pathlib.Path.read_bytes

        def reject_path_reopen(path: pathlib.Path) -> bytes:
            if path in protected:
                raise AssertionError(f"input path was reopened after validation: {path}")
            return original_read_bytes(path)

        with mock.patch.object(pathlib.Path, "read_bytes", reject_path_reopen):
            plan = self.plan()
        self.assertEqual(
            plan.package_sha256,
            hashlib.sha256(self.package.read_bytes()).hexdigest(),
        )

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

        hierarchy = self.root / "hierarchy-collision.zip"
        self.copy_archive_with_entry(
            hierarchy, "Assets/wonderswan/common/not-a-folder", b"file"
        )
        with zipfile.ZipFile(hierarchy, "a", zipfile.ZIP_STORED) as archive:
            archive.writestr(
                "Assets/wonderswan/common/not-a-folder/child.bin", b"child"
            )
        with self.assertRaisesRegex(StagingError, "file/directory path collision"):
            self.plan(package=hierarchy)

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

        document = json.loads(self.provenance.read_text(encoding="utf-8"))
        document["package_provenance"]["license_manifest"][
            "component_count"
        ] += 1
        license_mismatch = self.root / "license-mismatch.json"
        license_mismatch.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(StagingError, "license manifest provenance"):
            self.plan(provenance=license_mismatch)

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
        core_path = foreign_dist / "Cores/RegionallyFamous.SwanSong/core.json"
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

    def test_apply_directory_descriptors_do_not_follow_a_parent_swap(self) -> None:
        plan = self.plan()
        outside = self.root / "outside-swap-target"
        outside.mkdir()
        detached = self.root / "detached-cores"
        original_read_snapshot = staging._read_regular_snapshot_at
        swapped = False

        def swap_parent_after_open(directory: int, name: str):
            nonlocal swapped
            if not swapped:
                (self.stage / "Cores").rename(detached)
                (self.stage / "Cores").symlink_to(outside, target_is_directory=True)
                swapped = True
            return original_read_snapshot(directory, name)

        with mock.patch.object(
            staging, "_read_regular_snapshot_at", swap_parent_after_open
        ):
            with self.assertRaisesRegex(StagingError, "unsafe|symlink"):
                apply_staging(plan)
        self.assertTrue(swapped)
        self.assertEqual(list(outside.iterdir()), [])

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
        self.assertTrue(
            (volume_stage / "Cores/RegionallyFamous.SwanSong/core.json").is_file()
        )

    def test_authorized_release_verifies_exact_identity_and_optionally_stages_bios(self) -> None:
        (
            package,
            provenance,
            policy,
            version,
            commit,
            digest,
            provenance_digest,
        ) = self.release_fixture()
        game = self.stage / "Assets/wonderswan/common/owned-game.wsc"
        game.parent.mkdir(parents=True)
        game_payload = b"private game bytes that the staging tool must not read"
        game.write_bytes(game_payload)

        original_read_bytes = pathlib.Path.read_bytes

        def reject_game_read(path: pathlib.Path) -> bytes:
            if path == game:
                raise AssertionError("staging read a game ROM")
            return original_read_bytes(path)

        with mock.patch.object(staging, "RELEASE_POLICY", policy):
            with mock.patch.object(pathlib.Path, "read_bytes", reject_game_read):
                plan = plan_staging(
                    staging_dir=self.stage,
                    package=package,
                    provenance=provenance,
                    bw_bios=self.bw,
                    color_bios=None,
                    verify_release=True,
                    expected_package_sha256=digest,
                    expected_provenance_sha256=provenance_digest,
                    expected_version=version,
                    expected_source_commit=commit,
                )
                self.assertTrue(plan.release)
                self.assertEqual(plan.source_commit, commit)
                self.assertFalse(
                    (self.stage / "Cores/RegionallyFamous.SwanSong/core.json").exists()
                )
                apply_staging(plan)

        self.assertEqual(game.read_bytes(), game_payload)
        self.assertEqual(
            (self.stage / pathlib.Path(*ASSET_DIRECTORY.parts) / "bw.rom").read_bytes(),
            self.bw.read_bytes(),
        )
        self.assertFalse(
            (self.stage / pathlib.Path(*ASSET_DIRECTORY.parts) / "color.rom").exists()
        )

    def test_release_verification_rejects_checksum_commit_and_schema_drift(self) -> None:
        (
            package,
            provenance,
            policy,
            version,
            commit,
            digest,
            provenance_digest,
        ) = self.release_fixture()
        arguments = {
            "staging_dir": self.stage,
            "package": package,
            "provenance": provenance,
            "bw_bios": None,
            "color_bios": None,
            "verify_release": True,
            "expected_package_sha256": digest,
            "expected_provenance_sha256": provenance_digest,
            "expected_version": version,
            "expected_source_commit": commit,
        }
        with mock.patch.object(staging, "RELEASE_POLICY", policy):
            with self.assertRaisesRegex(StagingError, "expected-provenance-sha256"):
                plan_staging(
                    **{**arguments, "expected_provenance_sha256": None}
                )
            with self.assertRaisesRegex(StagingError, "expected checksum"):
                plan_staging(**{**arguments, "expected_package_sha256": "0" * 64})
            with self.assertRaisesRegex(StagingError, "provenance SHA-256"):
                plan_staging(
                    **{**arguments, "expected_provenance_sha256": "0" * 64}
                )
            with self.assertRaisesRegex(StagingError, "expected commit"):
                plan_staging(**{**arguments, "expected_source_commit": "c" * 40})
            with self.assertRaisesRegex(StagingError, "expected version"):
                plan_staging(**{**arguments, "expected_version": version + ".wrong"})

            policy_document = json.loads(provenance.read_text(encoding="utf-8"))
            policy_document["package_provenance"]["release_policy"][
                "manifest_sha256"
            ] = "0" * 64
            policy_mismatch = self.root / "policy-mismatch.provenance.json"
            policy_mismatch.write_text(json.dumps(policy_document), encoding="utf-8")
            with self.assertRaisesRegex(StagingError, "authorized release policy"):
                plan_staging(
                    **{
                        **arguments,
                        "provenance": policy_mismatch,
                        "expected_provenance_sha256": hashlib.sha256(
                            policy_mismatch.read_bytes()
                        ).hexdigest(),
                    }
                )

            document = json.loads(provenance.read_text(encoding="utf-8"))
            document["package_provenance"]["unexpected"] = True
            malformed = self.root / "extra-field.provenance.json"
            malformed.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(StagingError, "wrong schema"):
                plan_staging(
                    **{
                        **arguments,
                        "provenance": malformed,
                        "expected_provenance_sha256": hashlib.sha256(
                            malformed.read_bytes()
                        ).hexdigest(),
                    }
                )

            license_document = json.loads(provenance.read_text(encoding="utf-8"))
            license_document["package_provenance"]["license_manifest"][
                "requirement_count"
            ] += 1
            license_mismatch = self.root / "release-license-mismatch.json"
            license_mismatch.write_text(
                json.dumps(license_document), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                StagingError, "release license manifest provenance"
            ):
                plan_staging(
                    **{
                        **arguments,
                        "provenance": license_mismatch,
                        "expected_provenance_sha256": hashlib.sha256(
                            license_mismatch.read_bytes()
                        ).hexdigest(),
                    }
                )

            duplicate = self.root / "duplicate-field.provenance.json"
            duplicate.write_text(
                provenance.read_text(encoding="utf-8").replace(
                    '"release": true,', '"release": true, "release": true,', 1
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(StagingError, "duplicate object member"):
                plan_staging(
                    **{
                        **arguments,
                        "provenance": duplicate,
                        "expected_provenance_sha256": hashlib.sha256(
                            duplicate.read_bytes()
                        ).hexdigest(),
                    }
                )

            raw_identity = json.loads(provenance.read_text(encoding="utf-8"))
            raw_identity["package_provenance"]["raw_rbf"]["sha256"] = "0" * 64
            raw_mismatch = self.root / "raw-rbf-mismatch.provenance.json"
            raw_mismatch.write_text(json.dumps(raw_identity), encoding="utf-8")
            with self.assertRaisesRegex(StagingError, "reversible packaged bitstream"):
                plan_staging(
                    **{
                        **arguments,
                        "provenance": raw_mismatch,
                        "expected_provenance_sha256": hashlib.sha256(
                            raw_mismatch.read_bytes()
                        ).hexdigest(),
                        }
                    )

            source_commit = json.loads(provenance.read_text(encoding="utf-8"))
            source_commit["package_provenance"]["source_inputs"][
                "source_commit"
            ] = "c" * 40
            source_commit_mismatch = self.root / "source-commit-mismatch.json"
            source_commit_mismatch.write_text(
                json.dumps(source_commit), encoding="utf-8"
            )
            with self.assertRaisesRegex(StagingError, "source inputs.*expected commit"):
                plan_staging(
                    **{
                        **arguments,
                        "provenance": source_commit_mismatch,
                        "expected_provenance_sha256": hashlib.sha256(
                            source_commit_mismatch.read_bytes()
                        ).hexdigest(),
                    }
                )

            source_static = json.loads(provenance.read_text(encoding="utf-8"))
            source_static["package_provenance"]["source_inputs"]["tracked_files"][
                "dist/Platforms/wonderswan.json"
            ]["sha256"] = "0" * 64
            source_static_mismatch = self.root / "source-static-mismatch.json"
            source_static_mismatch.write_text(
                json.dumps(source_static), encoding="utf-8"
            )
            with self.assertRaisesRegex(StagingError, "commit-derived source"):
                plan_staging(
                    **{
                        **arguments,
                        "provenance": source_static_mismatch,
                        "expected_provenance_sha256": hashlib.sha256(
                            source_static_mismatch.read_bytes()
                        ).hexdigest(),
                    }
                )
        self.assertEqual(list(self.stage.iterdir()), [])

    def test_checked_in_policy_blocks_unauthorized_release_even_with_apply(self) -> None:
        (
            package,
            provenance,
            _policy,
            version,
            commit,
            digest,
            provenance_digest,
        ) = self.release_fixture()
        checked_in_policy = json.loads(
            (ROOT / "release-policy.json").read_text(encoding="utf-8")
        )
        self.assertIs(
            checked_in_policy["release_policy"]["authorization"][
                "distribution_and_licensing_authorized"
            ],
            False,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(
                [
                    "--staging-dir",
                    str(self.stage),
                    "--package",
                    str(package),
                    "--provenance",
                    str(provenance),
                    "--verify-release",
                    "--expected-package-sha256",
                    digest,
                    "--expected-provenance-sha256",
                    provenance_digest,
                    "--expected-version",
                    version,
                    "--expected-source-commit",
                    commit,
                    "--apply",
                ]
            )
        self.assertEqual(result, 2)
        self.assertIn("distribution and licensing are not authorized", stderr.getvalue())
        self.assertEqual(list(self.stage.iterdir()), [])

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
        self.assertIn("core-specific namespace", stdout.getvalue())
        self.assertIn("ROM-aware migration helper", stdout.getvalue())
        self.assertEqual(list(self.stage.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
