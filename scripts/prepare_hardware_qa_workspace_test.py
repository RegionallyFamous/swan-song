#!/usr/bin/env python3
"""Tests for the local Pocket/Dock QA workspace scaffold."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("prepare_hardware_qa_workspace.py")
SPEC = importlib.util.spec_from_file_location("prepare_hardware_qa_workspace", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)


class HardwareQaWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "swan-song-qa"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def planned(self, output: Path | None = None):
        return workspace.plan(
            output=output or self.output,
            run_id="swan-song-final-01",
            operator_name="Regionally Famous",
            operator_organization="Regionally Famous",
            created_at="2026-07-14T12:34:56Z",
        )

    def test_plan_is_read_only_and_binds_reviewed_probe(self) -> None:
        destination, inventory, probe, persistence_probes, instructions = self.planned()
        self.assertEqual(destination, self.output.parent.resolve() / self.output.name)
        self.assertFalse(self.output.exists())
        self.assertEqual(hashlib.sha256(probe).hexdigest(), workspace.EXPECTED_PROBE_SHA256)
        document = json.loads(inventory)
        body = document["hardware_qa_inventory"]
        self.assertEqual(body["magic"], workspace.EXPECTED_MAGIC)
        self.assertEqual(body["run_id"], "swan-song-final-01")
        self.assertEqual(body["created_at"], "2026-07-14T12:34:56Z")
        self.assertEqual(body["operator"]["name"], "Regionally Famous")
        text = instructions.decode()
        self.assertIn(str(self.output / "inventory.json"), text)
        self.assertIn("build_chip32_pending_diagnostic.py", text)
        self.assertIn(str(self.output / "chip32-pending-diagnostic"), text)
        self.assertIn("must never replace the signed release package", text)
        self.assertEqual(len(persistence_probes), 10)
        for name, expected in workspace.EXPECTED_PERSISTENCE_OUTPUT_SHA256.items():
            relative = Path("private/sram-persistence-probes") / name
            self.assertEqual(hashlib.sha256(persistence_probes[relative]).hexdigest(), expected)

    def test_apply_atomically_creates_owner_only_scaffold(self) -> None:
        destination, inventory, probe, persistence_probes, instructions = self.planned()
        workspace.apply(destination, inventory, probe, persistence_probes, instructions)
        self.assertTrue(destination.is_dir())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
        for relative in ("private", "evidence", "sd", "build", "build/output_files"):
            path = destination / relative
            self.assertTrue(path.is_dir())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        for relative in (
            "inventory.json",
            "private/compact-896k.wsc",
            "private/sram-persistence-probes/sram_type03_persistence.ws",
            "private/sram-persistence-probes/sram_type03_persistence.wsc",
            "private/sram-persistence-probes/sram_type04_persistence.ws",
            "private/sram-persistence-probes/sram_type04_persistence.wsc",
            "private/sram-persistence-probes/sram_type05_persistence.ws",
            "private/sram-persistence-probes/sram_type05_persistence.wsc",
            "private/sram-persistence-probes/sram_persistence_boot_mono.bin",
            "private/sram-persistence-probes/sram_persistence_boot_color.bin",
            "private/sram-persistence-probes/sram_persistence_probes.manifest.json",
            "private/sram-persistence-probes/sram_persistence_probes.sha256",
            "NEXT_STEPS.md",
            ".gitignore",
        ):
            path = destination / relative
            self.assertTrue(path.is_file())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual((destination / "private/compact-896k.wsc").read_bytes(), probe)
        private_files = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        self.assertNotIn("private/bw.rom", private_files)
        self.assertNotIn("private/color.rom", private_files)
        self.assertNotIn("private/pocket_firmware.bin", private_files)
        generated_roms = {
            "private/compact-896k.wsc",
            *{
                f"private/sram-persistence-probes/sram_type{save_type}_persistence.{model}"
                for save_type in ("03", "04", "05")
                for model in ("ws", "wsc")
            },
        }
        self.assertEqual(
            {name for name in private_files if name.endswith((".ws", ".wsc"))},
            generated_roms,
        )

    def test_rejects_existing_inside_repo_and_malformed_identity(self) -> None:
        self.output.mkdir()
        with self.assertRaisesRegex(workspace.WorkspaceError, "already exists"):
            self.planned()
        with self.assertRaisesRegex(workspace.WorkspaceError, "outside the repository"):
            self.planned(workspace.ROOT / "private-qa")
        with self.assertRaisesRegex(workspace.WorkspaceError, "run-id"):
            workspace.plan(
                output=self.root / "bad-id",
                run_id="Bad ID",
                operator_name="Regionally Famous",
                operator_organization="Regionally Famous",
                created_at="2026-07-14T12:34:56Z",
            )

    def test_rejects_bad_time_control_text_and_symlink_parent(self) -> None:
        with self.assertRaisesRegex(workspace.WorkspaceError, "real UTC"):
            workspace.plan(
                output=self.root / "bad-time",
                run_id="valid",
                operator_name="Regionally Famous",
                operator_organization="Regionally Famous",
                created_at="2026-02-30T12:34:56Z",
            )
        with self.assertRaisesRegex(workspace.WorkspaceError, "control-free"):
            workspace.plan(
                output=self.root / "bad-name",
                run_id="valid",
                operator_name="Bad\nName",
                operator_organization="Regionally Famous",
                created_at="2026-07-14T12:34:56Z",
            )
        real_parent = self.root / "real"
        real_parent.mkdir()
        linked_parent = self.root / "linked"
        os.symlink(real_parent, linked_parent)
        with self.assertRaisesRegex(workspace.WorkspaceError, "nonsymlink"):
            self.planned(linked_parent / "qa")

    def test_publication_race_never_replaces_empty_destination(self) -> None:
        destination, inventory, probe, persistence_probes, instructions = self.planned()
        native_rename = workspace._rename_noreplace
        raced_identity: list[int] = []

        def race(parent: Path, source_name: str, destination_name: str) -> None:
            raced = parent / destination_name
            raced.mkdir(mode=0o700)
            raced_identity.append(raced.stat().st_ino)
            native_rename(parent, source_name, destination_name)

        with mock.patch.object(workspace, "_rename_noreplace", side_effect=race):
            with self.assertRaises(FileExistsError):
                workspace.apply(destination, inventory, probe, persistence_probes, instructions)

        self.assertTrue(destination.is_dir())
        self.assertEqual(destination.stat().st_ino, raced_identity[0])
        self.assertEqual(list(destination.iterdir()), [])
        self.assertFalse(any(
            path.name.startswith(f".{destination.name}.")
            for path in destination.parent.iterdir()
        ))

    def test_publication_race_never_replaces_destination_symlink(self) -> None:
        destination, inventory, probe, persistence_probes, instructions = self.planned()
        native_rename = workspace._rename_noreplace
        symlink_target = self.root / "existing-target"
        symlink_target.mkdir()
        marker = symlink_target / "owner-file"
        marker.write_text("preserve\n", encoding="utf-8")

        def race(parent: Path, source_name: str, destination_name: str) -> None:
            os.symlink(symlink_target, parent / destination_name)
            native_rename(parent, source_name, destination_name)

        with mock.patch.object(workspace, "_rename_noreplace", side_effect=race):
            with self.assertRaises(FileExistsError):
                workspace.apply(destination, inventory, probe, persistence_probes, instructions)

        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), symlink_target.resolve())
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")
        self.assertFalse(any(
            path.name.startswith(f".{destination.name}.")
            for path in destination.parent.iterdir()
        ))


if __name__ == "__main__":
    unittest.main()
