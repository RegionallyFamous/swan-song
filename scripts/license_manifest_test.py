#!/usr/bin/env python3
"""Focused tests for the fail-closed Swan Song license manifest."""

import hashlib
import json
import pathlib
import shutil
import tempfile
import unittest

from license_manifest import (
    CORE_RELATIVE,
    MODIFIED_GPL_PATHS,
    SV_MODIFICATION_NOTICE,
    WONDERSWAN_NOTICE,
    WONDERSWAN_WRAPPER,
    validate_license_manifest,
    validate_modified_file_notices,
    validate_wonderswan_notice,
)


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

    def copy_modified_gpl_sources(self, destination: pathlib.Path) -> None:
        for relative in MODIFIED_GPL_PATHS:
            target = destination / pathlib.Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / pathlib.Path(*relative.parts), target)

    def test_checked_manifest_binds_notices_assets_and_open_blockers(self) -> None:
        summary = validate_license_manifest(self.dist, source_root=ROOT)
        self.assertEqual(summary["package_notice_count"], 7)
        self.assertEqual(summary["component_count"], 10)
        self.assertEqual(summary["legacy_test_asset_count"], 0)
        self.assertFalse(summary["licensing_review_complete"])
        self.assertEqual(
            summary["wonderswan_notice_sha256"],
            hashlib.sha256(WONDERSWAN_NOTICE.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            summary["unresolved_ids"],
            [
                "agg23-pocket-adaptation",
                "analogue-apf",
                "corresponding-source-delivery",
                "intel-altera-generated-material",
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
                if item["id"] == "regionally-famous-original-work"
            )
            component["review_status"] = "documented"
            component["blocker"] = None
            manifest["release_gate"]["unresolved_ids"].remove(
                "regionally-famous-original-work"
            )

        self.mutate(update)
        with self.assertRaisesRegex(ValueError, "cannot be documented.*NOASSERTION"):
            validate_license_manifest(self.dist)

    def test_retired_legacy_asset_roots_must_stay_empty(self) -> None:
        source = self.root / "source"
        self.copy_modified_gpl_sources(source)
        validate_license_manifest(self.dist, source_root=source)

        retired = source / "testroms/spritepriority/unknown.ws"
        retired.parent.mkdir(parents=True)
        retired.write_bytes(b"unreviewed inherited fixture")
        with self.assertRaisesRegex(ValueError, "must remain empty"):
            validate_license_manifest(self.dist, source_root=source)

    def test_exact_modified_gpl_sources_retain_dated_notices(self) -> None:
        expected_paths = {
            "src/fpga/core/wonderswan.sv",
            "src/fpga/core/rtl/IRQ.vhd",
            "src/fpga/core/rtl/cpu.vhd",
            "src/fpga/core/rtl/dma.vhd",
            "src/fpga/core/rtl/dummyregs.vhd",
            "src/fpga/core/rtl/eeprom.vhd",
            "src/fpga/core/rtl/gpu.vhd",
            "src/fpga/core/rtl/gpu_bg.vhd",
            "src/fpga/core/rtl/joypad.vhd",
            "src/fpga/core/rtl/memorymux.vhd",
            "src/fpga/core/rtl/reg_savestates.vhd",
            "src/fpga/core/rtl/reg_swan.vhd",
            "src/fpga/core/rtl/registerpackage.vhd",
            "src/fpga/core/rtl/rtc.vhd",
            "src/fpga/core/rtl/savestate_ui.sv",
            "src/fpga/core/rtl/savestates.vhd",
            "src/fpga/core/rtl/sprites.vhd",
            "src/fpga/core/rtl/swanTop.vhd",
            "src/fpga/core/rtl/swanbios.vhd",
            "src/fpga/core/rtl/swanbioscolor.vhd",
            "src/fpga/core/rtl/sdram.sv",
        }
        self.assertEqual(
            {path.as_posix() for path in MODIFIED_GPL_PATHS}, expected_paths
        )

        source = self.root / "modified-gpl-source"
        self.copy_modified_gpl_sources(source)
        notices = validate_modified_file_notices(source)
        self.assertEqual(set(notices), expected_paths)

        changed = source / "src/fpga/core/rtl/sdram.sv"
        changed.write_text(
            changed.read_text(encoding="utf-8").replace(
                SV_MODIFICATION_NOTICE, "", 1
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "exact dated Swan Song notice"):
            validate_modified_file_notices(source)

        shutil.copy2(ROOT / "src/fpga/core/rtl/sdram.sv", changed)
        vhdl = source / "src/fpga/core/rtl/IRQ.vhd"
        vhdl.write_text(
            vhdl.read_text(encoding="utf-8").replace(
                "2026-07-14", "2026-07-15", 1
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "exact dated Swan Song notice"):
            validate_modified_file_notices(source)

        vhdl.unlink()
        vhdl.symlink_to(ROOT / "src/fpga/core/rtl/IRQ.vhd")
        with self.assertRaisesRegex(ValueError, "must be a regular file"):
            validate_modified_file_notices(source)

        vhdl.unlink()
        vhdl.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(ValueError, "must be UTF-8"):
            validate_modified_file_notices(source)

    def test_modified_notice_paths_are_bound_to_manifest_scopes(self) -> None:
        def update(manifest) -> None:
            component = next(
                item
                for item in manifest["components"]
                if item["id"] == "sorgelig-memory-controllers"
            )
            component["scope"].remove("src/fpga/core/rtl/sdram.sv")

        self.mutate(update)
        with self.assertRaisesRegex(ValueError, "scope omits audited modified files"):
            validate_license_manifest(self.dist)

    def test_wonderswan_program_notice_is_exact_and_source_bound(self) -> None:
        source = self.root / "notice-source"
        wrapper = source / pathlib.Path(*WONDERSWAN_WRAPPER.parts)
        wrapper.parent.mkdir(parents=True)
        shutil.copy2(ROOT / pathlib.Path(*WONDERSWAN_WRAPPER.parts), wrapper)
        validate_wonderswan_notice(source)

        wrapper.write_text(
            wrapper.read_text(encoding="utf-8").replace(
                "Copyright (c) 2021 Robert Peip",
                "Copyright (c) 2021 Someone Else",
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ValueError, "exact upstream GPL-2.0-or-later notice"
        ):
            validate_wonderswan_notice(source)


if __name__ == "__main__":
    unittest.main()
