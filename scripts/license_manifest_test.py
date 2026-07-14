#!/usr/bin/env python3
"""Focused tests for the fail-closed Swan Song license manifest."""

import json
import pathlib
import shutil
import tempfile
import unittest

from license_manifest import CORE_RELATIVE, validate_license_manifest


ROOT = pathlib.Path(__file__).resolve().parent.parent


class LicenseManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="swan-song-license-manifest-test-"
        )
        self.root = pathlib.Path(self.temporary.name)
        self.dist = self.root / "dist"
        shutil.copytree(ROOT / "dist", self.dist)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @property
    def manifest_path(self) -> pathlib.Path:
        return self.dist / CORE_RELATIVE / "LICENSE-MANIFEST.json"

    def mutate(self, callback) -> None:
        document = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        callback(document["license_manifest"])
        self.manifest_path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def mark_reviewed(self) -> None:
        def update(manifest) -> None:
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

        self.mutate(update)

    def test_checked_manifest_binds_notices_assets_and_open_blockers(self) -> None:
        summary = validate_license_manifest(self.dist, source_root=ROOT)
        self.assertEqual(summary["package_notice_count"], 7)
        self.assertEqual(summary["component_count"], 11)
        self.assertEqual(summary["legacy_test_asset_count"], 19)
        self.assertFalse(summary["licensing_review_complete"])
        self.assertEqual(
            summary["unresolved_ids"],
            [
                "agg23-pocket-adaptation",
                "analogue-apf",
                "corresponding-source-delivery",
                "intel-altera-generated-material",
                "legacy-mister-test-assets",
                "regionally-famous-original-work",
                "wonderswan-program",
            ],
        )
        document = json.loads(self.manifest_path.read_text(encoding="utf-8"))[
            "license_manifest"
        ]
        explicit = next(
            component
            for component in document["components"]
            if component["id"] == "swan-song-explicit-gpl2-simulation"
        )
        actual_gpl2 = {
            path.relative_to(ROOT).as_posix()
            for directory in (ROOT / "sim/rtl", ROOT / "sim/verilator")
            for path in directory.rglob("*")
            if path.is_file()
            and any(
                "SPDX-License-Identifier: GPL-2.0-only" in line
                for line in path.read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()[:2]
            )
        }
        self.assertEqual(set(explicit["scope"]), actual_gpl2)
        with self.assertRaisesRegex(ValueError, "review is not complete"):
            validate_license_manifest(
                self.dist, source_root=ROOT, require_release_ready=True
            )

    def test_reviewed_fixture_is_accepted_without_weakening_notice_checks(self) -> None:
        self.mark_reviewed()
        summary = validate_license_manifest(
            self.dist, source_root=ROOT, require_release_ready=True
        )
        self.assertTrue(summary["licensing_review_complete"])
        self.assertEqual(summary["unresolved_ids"], [])

        notice = self.dist / CORE_RELATIVE / "NOTICE-Analogue-APF.txt"
        notice.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "notice SHA-256 does not match"):
            validate_license_manifest(
                self.dist, source_root=ROOT, require_release_ready=True
            )

    def test_gate_and_status_cannot_disagree(self) -> None:
        self.mutate(
            lambda manifest: manifest["release_gate"].update(
                {"licensing_review_complete": True, "unresolved_ids": []}
            )
        )
        with self.assertRaisesRegex(
            ValueError, "unresolved_ids do not match review_required"
        ):
            validate_license_manifest(self.dist)

    def test_noassertion_cannot_be_marked_documented(self) -> None:
        def update(manifest) -> None:
            component = next(
                item
                for item in manifest["components"]
                if item["id"] == "legacy-mister-test-assets"
            )
            component["review_status"] = "documented"
            component["blocker"] = None
            manifest["release_gate"]["unresolved_ids"].remove(
                "legacy-mister-test-assets"
            )

        self.mutate(update)
        with self.assertRaisesRegex(ValueError, "cannot be documented.*NOASSERTION"):
            validate_license_manifest(self.dist)

    def test_legacy_asset_bytes_are_source_bound(self) -> None:
        source = self.root / "source"
        for relative in (
            "testroms/spritepriority",
            "testroms/timingtest",
            "testroms/windowtest",
        ):
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ROOT / relative, target)
        validate_license_manifest(self.dist, source_root=source)

        changed = source / "testroms/spritepriority/spritepriority.asm"
        changed.write_bytes(changed.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "identity is absent or changed"):
            validate_license_manifest(self.dist, source_root=source)


if __name__ == "__main__":
    unittest.main()
