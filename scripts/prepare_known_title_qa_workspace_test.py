#!/usr/bin/env python3
"""Tests for the private known-title Pocket/Dock QA workspace scaffold."""

from __future__ import annotations

from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("prepare_known_title_qa_workspace.py")
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location(
    "prepare_known_title_qa_workspace", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)


class KnownTitleQaWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "swan-song-known-title-qa"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def planned(self, output: Path | None = None):
        return workspace.plan(
            output=output or self.output,
            run_id="known-title-final-01",
            operator="Regionally Famous",
            core_commit="1" * 40,
            raw_rbf_sha256="2" * 64,
            pocket_hardware_revision="Pocket test revision",
            dock_hardware_revision="Dock test revision",
            created_at="2026-07-15T12:34:56Z",
        )

    def test_plan_is_read_only_all_pending_and_complete(self) -> None:
        (
            destination,
            manifest_bytes,
            evidence_plan_bytes,
            worksheet_bytes,
            _instructions,
            directories,
        ) = self.planned()

        self.assertEqual(destination, self.output.parent.resolve() / self.output.name)
        self.assertFalse(self.output.exists())
        manifest = json.loads(manifest_bytes)["known_title_compatibility"]
        plan = json.loads(evidence_plan_bytes)["known_title_evidence_plan"]
        slots = plan["slots"]

        self.assertEqual(manifest["run"]["run_id"], "known-title-final-01")
        self.assertEqual(manifest["run"]["operator"], "Regionally Famous")
        self.assertEqual(
            manifest["run"]["firmware_version"],
            workspace.compatibility.REQUIRED_FIRMWARE,
        )
        self.assertEqual(len(manifest["cases"]), 17)
        self.assertEqual(manifest["artifacts"], [])
        self.assertEqual(
            Counter(
                mode["status"]
                for case in manifest["cases"]
                for mode in case["modes"].values()
            ),
            {"pending": 34},
        )
        self.assertFalse(manifest["attestation"]["physical_hardware_observed"])
        self.assertFalse(
            manifest["attestation"]["results_not_inferred_from_simulation"]
        )

        self.assertEqual(plan["magic"], workspace.PLAN_MAGIC)
        self.assertEqual(len(slots), workspace.TOTAL_SLOT_COUNT)
        self.assertEqual(
            Counter(slot["owner"] for slot in slots),
            {"reference": 20, "pocket": 52, "dock": 52},
        )
        self.assertEqual(len({slot["id"] for slot in slots}), len(slots))
        self.assertEqual(len({slot["path"] for slot in slots}), len(slots))
        self.assertTrue(
            all(Path(slot["path"]).parts[0] == "evidence" for slot in slots)
        )

        # Every commercial scenario receives one independent original-hardware
        # reference slot. Open fixtures receive none.
        expected_references = {
            (case["id"], scenario["id"])
            for case in manifest["cases"]
            if case["class"] == "commercial"
            for scenario in case["scenarios"]
        }
        actual_references = {
            (slot["case_id"], slot["scenario_id"])
            for slot in slots
            if slot["owner"] == "reference"
        }
        self.assertEqual(actual_references, expected_references)
        self.assertEqual(len(expected_references), 20)

        # Each mode receives at least the checked-in minimum for every accepted
        # evidence-kind group.
        for case in manifest["cases"]:
            for mode in ("pocket", "dock"):
                planned = [
                    slot
                    for slot in slots
                    if slot["case_id"] == case["id"] and slot["owner"] == mode
                ]
                for requirement in case["mode_evidence_requirements"]:
                    matching = sum(
                        slot["kind"] in requirement["kinds"] for slot in planned
                    )
                    self.assertGreaterEqual(matching, requirement["minimum"])

        self.assertEqual(
            set(directories),
            {
                Path(slot["path"]).parent
                for slot in slots
            }
            | {Path("evidence")},
        )
        worksheet = worksheet_bytes.decode("utf-8")
        self.assertIn("0 pass / 0 fail / 34 pending", worksheet)
        self.assertIn("this helper never passes a case", worksheet)
        for case in manifest["cases"]:
            self.assertIn(f"`{case['id']}`", worksheet)

    def test_deterministic_paths_and_mode_appropriate_visual_kind(self) -> None:
        first = self.planned()
        second = self.planned(self.root / "second-run")
        first_plan = json.loads(first[2])["known_title_evidence_plan"]
        second_plan = json.loads(second[2])["known_title_evidence_plan"]

        self.assertEqual(first_plan["slots"], second_plan["slots"])
        by_id = {slot["id"]: slot for slot in first_plan["slots"]}
        self.assertEqual(
            by_id["cho-denki-crash-ref-01"]["path"],
            "evidence/cho-denki-crash/reference/cho-denki-crash-ref-01.mp4",
        )
        self.assertEqual(
            by_id["cho-denki-crash-pocket-video-01"]["path"],
            "evidence/cho-denki-crash/pocket/"
            "cho-denki-crash-pocket-video-01.mp4",
        )
        counts = Counter(
            (slot["owner"], slot["kind"]) for slot in first_plan["slots"]
        )
        self.assertEqual(counts[("pocket", "pocket_screenshot")], 5)
        self.assertEqual(counts[("dock", "photo")], 5)
        self.assertEqual(counts[("dock", "pocket_screenshot")], 0)
        manifest = json.loads(first[1])["known_title_compatibility"]
        meta = next(
            case for case in manifest["cases"]
            if case["id"] == "meta-communication-name-select"
        )
        self.assertEqual(meta["system"], "ws")

    def test_apply_creates_owner_only_empty_evidence_scaffold(self) -> None:
        planned = self.planned()
        workspace.apply(*planned)

        destination = planned[0]
        self.assertTrue(destination.is_dir())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
        for relative in planned[5]:
            path = destination / relative
            self.assertTrue(path.is_dir(), relative)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        for relative in (
            "manifest.json",
            "evidence-plan.json",
            "operator-worksheet.md",
            "NEXT_STEPS.md",
            ".gitignore",
        ):
            path = destination / relative
            self.assertTrue(path.is_file())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

        files = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            files,
            {
                "manifest.json",
                "evidence-plan.json",
                "operator-worksheet.md",
                "NEXT_STEPS.md",
                ".gitignore",
            },
        )
        result = workspace.compatibility.verify_manifest(
            workspace.CATALOGUE, destination / "manifest.json"
        )
        self.assertEqual(
            result["status"], {"pass": 0, "fail": 0, "pending": 34}
        )

    def test_worksheet_refresh_does_not_mutate_manifest_or_evidence(self) -> None:
        planned = self.planned()
        workspace.apply(*planned)
        destination = planned[0]
        manifest = destination / "manifest.json"
        worksheet = destination / "operator-worksheet.md"
        manifest_before = manifest.read_bytes()
        evidence_before = sorted(
            path.relative_to(destination).as_posix()
            for path in (destination / "evidence").rglob("*")
        )

        rendered = workspace.render_operator_worksheet(manifest)
        workspace.write_operator_worksheet(manifest, worksheet)

        self.assertEqual(worksheet.read_text(encoding="utf-8"), rendered)
        self.assertEqual(manifest.read_bytes(), manifest_before)
        self.assertEqual(
            sorted(
                path.relative_to(destination).as_posix()
                for path in (destination / "evidence").rglob("*")
            ),
            evidence_before,
        )
        with self.assertRaisesRegex(workspace.WorkspaceError, "must not replace"):
            workspace.write_operator_worksheet(manifest, manifest)
        linked = destination / "linked-worksheet.md"
        os.symlink(worksheet, linked)
        with self.assertRaisesRegex(workspace.WorkspaceError, "regular file"):
            workspace.write_operator_worksheet(manifest, linked)

        hardlinked = destination / "hardlinked-worksheet.md"
        os.link(manifest, hardlinked)
        try:
            with self.assertRaisesRegex(workspace.WorkspaceError, "single-link"):
                workspace.write_operator_worksheet(manifest, hardlinked)
            self.assertEqual(manifest.read_bytes(), manifest_before)
        finally:
            hardlinked.unlink()

        os.chmod(worksheet, 0o644)
        workspace.write_operator_worksheet(manifest, worksheet)
        self.assertEqual(stat.S_IMODE(worksheet.stat().st_mode), 0o600)
        self.assertFalse(any("-snapshot." in path.name for path in destination.rglob("*")))

        os.chmod(destination, 0o500)
        try:
            self.assertIn(
                "34 required device modes",
                workspace.render_operator_worksheet(manifest),
            )
        finally:
            os.chmod(destination, 0o700)

    def test_rejects_existing_inside_repo_malformed_identity_and_symlink_parent(self) -> None:
        self.output.mkdir()
        with self.assertRaisesRegex(workspace.WorkspaceError, "already exists"):
            self.planned()
        with self.assertRaisesRegex(workspace.WorkspaceError, "outside the repository"):
            self.planned(workspace.ROOT / "private-known-title-qa")
        with self.assertRaisesRegex(ValueError, "run-id"):
            workspace.plan(
                output=self.root / "bad-id",
                run_id="Bad ID",
                operator="Regionally Famous",
                core_commit="1" * 40,
                raw_rbf_sha256="2" * 64,
                pocket_hardware_revision="Pocket",
                dock_hardware_revision="Dock",
                created_at="2026-07-15T12:34:56Z",
            )
        with self.assertRaisesRegex(ValueError, "Git commit"):
            workspace.plan(
                output=self.root / "bad-commit",
                run_id="valid",
                operator="Regionally Famous",
                core_commit="ABC",
                raw_rbf_sha256="2" * 64,
                pocket_hardware_revision="Pocket",
                dock_hardware_revision="Dock",
                created_at="2026-07-15T12:34:56Z",
            )
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            workspace.plan(
                output=self.root / "bad-hash",
                run_id="valid",
                operator="Regionally Famous",
                core_commit="1" * 40,
                raw_rbf_sha256="nope",
                pocket_hardware_revision="Pocket",
                dock_hardware_revision="Dock",
                created_at="2026-07-15T12:34:56Z",
            )

        real_parent = self.root / "real"
        real_parent.mkdir()
        linked_parent = self.root / "linked"
        os.symlink(real_parent, linked_parent)
        with self.assertRaisesRegex(workspace.WorkspaceError, "nonsymlink"):
            self.planned(linked_parent / "qa")

    def test_publication_race_never_replaces_destination(self) -> None:
        planned = self.planned()
        destination = planned[0]
        native_rename = workspace._rename_noreplace
        raced_identity: list[int] = []

        def race(parent: Path, source_name: str, destination_name: str) -> None:
            raced = parent / destination_name
            raced.mkdir(mode=0o700)
            raced_identity.append(raced.stat().st_ino)
            native_rename(parent, source_name, destination_name)

        with mock.patch.object(workspace, "_rename_noreplace", side_effect=race):
            with self.assertRaises(FileExistsError):
                workspace.apply(*planned)

        self.assertTrue(destination.is_dir())
        self.assertEqual(destination.stat().st_ino, raced_identity[0])
        self.assertEqual(list(destination.iterdir()), [])
        self.assertFalse(
            any(
                path.name.startswith(f".{destination.name}.")
                for path in destination.parent.iterdir()
            )
        )

    def test_publication_race_never_replaces_destination_symlink(self) -> None:
        planned = self.planned()
        destination = planned[0]
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
                workspace.apply(*planned)

        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), symlink_target.resolve())
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")
        self.assertFalse(
            any(
                path.name.startswith(f".{destination.name}.")
                for path in destination.parent.iterdir()
            )
        )


if __name__ == "__main__":
    unittest.main()
