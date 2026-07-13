#!/usr/bin/env python3
"""Offline tests for the physical-evidence schema; no hardware pass is claimed."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import shutil
import struct
import tempfile
import unittest
from unittest import mock

import pocket_hardware_qa as hardware_qa
from pocket_hardware_qa import (
    CASE_SPECS,
    OFFICIAL_FIRMWARE_MD5,
    OFFICIAL_FIRMWARE_VERSION,
    REVERSE,
    generate_manifest,
    verify_manifest,
)


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PocketHardwareQATest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-hardware-qa-test-")
        self.root = pathlib.Path(self.temporary.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()

        self.firmware = self.private / "pocket_firmware.bin"
        self.firmware.write_bytes(b"synthetic firmware identity fixture")
        self.synthetic_firmware_md5 = hashlib.md5(self.firmware.read_bytes()).hexdigest()
        self.firmware_identity_patch = mock.patch.object(
            hardware_qa, "OFFICIAL_FIRMWARE_MD5", self.synthetic_firmware_md5
        )
        self.firmware_identity_patch.start()
        self.addCleanup(self.firmware_identity_patch.stop)
        (self.private / "pocket-id.txt").write_text("synthetic-pocket-unit-1", encoding="utf-8")
        (self.private / "dock-id.txt").write_text("synthetic-dock-unit-1", encoding="utf-8")

        self.core_json = self.private / "core.json"
        shutil.copy2(ROOT / "dist/Cores/agg23.WonderSwan/core.json", self.core_json)
        self.raw_rbf = self.private / "ap_core.rbf"
        self.raw_rbf.write_bytes(bytes(range(256)) * 256)
        self.installed = self.private / "wonderswan.rev"
        self.installed.write_bytes(self.raw_rbf.read_bytes().translate(REVERSE))
        (self.private / "bw.rom").write_bytes(bytes(4096))
        (self.private / "color.rom").write_bytes(bytes(8192))
        (self.private / "horizontal.ws").write_bytes(bytes(64 * 1024))
        (self.private / "vertical.wsc").write_bytes(bytes([0xA5]) * (64 * 1024))

        inventory = {
            "hardware_qa_inventory": {
                "magic": "SWAN_SONG_HARDWARE_QA_INVENTORY_V1",
                "run_id": "synthetic-unit-test",
                "created_at": "2026-07-13T12:00:00Z",
                "operator": {"name": "Schema unit test", "organization": "Offline fixture"},
                "firmware": {
                    "version": "2.6.0",
                    "update_path": str(self.firmware),
                    "expected_md5": self.synthetic_firmware_md5,
                },
                "pocket": {
                    "model": "Analogue Pocket",
                    "hardware_revision": "synthetic",
                    "device_id_path": str(self.private / "pocket-id.txt"),
                },
                "dock": {
                    "model": "Analogue Dock",
                    "hardware_revision": "synthetic",
                    "firmware_version": "not-reported",
                    "device_id_path": str(self.private / "dock-id.txt"),
                },
                "core": {
                    "core_json_path": str(self.core_json),
                    "raw_rbf_path": str(self.raw_rbf),
                    "installed_bitstream_path": str(self.installed),
                },
                "bios": [
                    {"id": "bw", "path": str(self.private / "bw.rom")},
                    {"id": "color", "path": str(self.private / "color.rom")},
                ],
                "roms": [
                    {
                        "id": "horizontal-sram", "title": "Synthetic horizontal",
                        "path": str(self.private / "horizontal.ws"), "system": "ws",
                        "native_orientation": "horizontal", "save_media": "sram", "rtc": False,
                    },
                    {
                        "id": "vertical-eeprom-rtc", "title": "Synthetic vertical",
                        "path": str(self.private / "vertical.wsc"), "system": "wsc",
                        "native_orientation": "vertical", "save_media": "eeprom", "rtc": True,
                    },
                ],
                "controllers": [
                    {"id": "pocket", "scope": "pocket", "device_type": "gamepad", "transport": "built_in", "model": "Built in", "firmware_version": "2.6.0", "mapping_mode": "APF type 1"},
                    {"id": "wired", "scope": "dock", "device_type": "gamepad", "transport": "usb", "model": "Synthetic wired", "firmware_version": "not-reported", "mapping_mode": "XInput"},
                    {"id": "wireless", "scope": "dock", "device_type": "gamepad", "transport": "bluetooth", "model": "Synthetic wireless", "firmware_version": "test", "mapping_mode": "XInput"},
                    {"id": "keyboard", "scope": "dock", "device_type": "keyboard", "transport": "usb", "model": "Synthetic keyboard", "firmware_version": "not-reported", "mapping_mode": "USB HID"},
                    {"id": "mouse", "scope": "dock", "device_type": "mouse", "transport": "usb", "model": "Synthetic mouse", "firmware_version": "not-reported", "mapping_mode": "USB HID"},
                ],
            }
        }
        self.inventory = self.root / "inventory.json"
        self.inventory.write_text(json.dumps(inventory), encoding="utf-8")
        self.manifest = self.evidence / "manifest.json"
        generate_manifest(self.inventory, self.manifest)
        self.generated_document = json.loads(self.manifest.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def artifact_bytes(kind: str) -> tuple[str, bytes]:
        if kind == "pocket_screenshot":
            return ".png", b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 224, 144) + b"\x08\x02\x00\x00\x00fixture"
        if kind == "photo":
            return ".png", b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 480) + b"\x08\x02\x00\x00\x00fixture"
        if kind == "video":
            return ".mp4", struct.pack(">I", 24) + b"ftyp" + b"isom" + bytes(32)
        if kind == "audio":
            return ".wav", b"RIFF" + struct.pack("<I", 20) + b"WAVEfmt " + bytes(24)
        if kind == "save":
            return ".sav", b"synthetic save snapshot"
        if kind == "log":
            return ".txt", b"synthetic schema evidence; not a hardware observation\n"
        raise AssertionError(kind)

    def accepted_fixture(self) -> dict:
        """Create schema-complete synthetic bytes, never persisted as claimed QA."""
        document = copy.deepcopy(self.generated_document)
        body = document["hardware_qa"]
        roms = body["environment"]["roms"]
        controllers = body["environment"]["controllers"]

        def rom_selection(requirement: str) -> list[str]:
            if requirement in {"both_orientations", "save_pair", "two"}:
                return [item["id"] for item in roms]
            if requirement in {"eeprom", "rtc", "vertical"}:
                return [next(item["id"] for item in roms if item["id"] == "vertical-eeprom-rtc")]
            return [next(item["id"] for item in roms if item["id"] == "horizontal-sram")]

        def controller_selection(requirement: str) -> list[str]:
            selections = {
                "pocket": ["pocket"],
                "dock_wired_gamepad": ["wired"],
                "dock_wireless_gamepad": ["wireless"],
                "dock_gamepads": ["wired", "wireless"],
                "pocket_and_dock": ["pocket", "wired"],
                "unsupported_devices": ["wired", "wireless", "keyboard", "mouse"],
            }
            return selections[requirement]
        artifacts = []
        by_case = {item["id"]: item for item in body["cases"]}
        counter = 0
        for spec in CASE_SPECS:
            case = by_case[spec.case_id]
            case.update({
                "status": "pass",
                "started_at": "2026-07-13T13:00:00Z",
                "completed_at": "2026-07-13T14:00:00Z",
                "rom_ids": rom_selection(spec.rom_requirement),
                "controller_ids": controller_selection(spec.controller_requirement),
                "notes": "Synthetic unit-test coverage only; not physical evidence.",
            })
            case["checks"] = {name: True for name in spec.checks}
            for need in spec.needs:
                for _ in range(need.minimum):
                    kind = need.kinds[0]
                    counter += 1
                    artifact_id = f"artifact-{counter:04d}"
                    suffix, contents = self.artifact_bytes(kind)
                    relative = pathlib.PurePosixPath("files") / f"{artifact_id}{suffix}"
                    path = self.evidence / relative
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(contents)
                    artifacts.append({
                        "id": artifact_id, "kind": kind, "path": relative.as_posix(),
                        "label": f"Synthetic {kind} for {spec.case_id}",
                        "captured_at": "2026-07-13T13:30:00Z",
                        "size": len(contents), "sha256": hashlib.sha256(contents).hexdigest(),
                    })
                    case["artifact_ids"].append(artifact_id)
        body["artifacts"] = artifacts
        body["attestation"] = {
            "physical_hardware_observed": True,
            "results_not_inferred_from_simulation": True,
            "evidence_reviewed": True,
            "reviewer": "Synthetic schema unit test",
            "reviewed_at": "2026-07-13T15:00:00Z",
        }
        return document

    def write_manifest(self, document: dict) -> None:
        self.manifest.write_text(json.dumps(document), encoding="utf-8")

    def test_generated_manifest_is_valid_pending_and_rejected_for_acceptance(self) -> None:
        summary = verify_manifest(self.manifest, self.inventory, require_pass=False)
        self.assertEqual(summary["cases"], len(CASE_SPECS))
        with self.assertRaisesRegex(ValueError, "not accepted.*pending"):
            verify_manifest(self.manifest, self.inventory)

    def test_production_firmware_identity_is_pinned(self) -> None:
        self.assertEqual(OFFICIAL_FIRMWARE_VERSION, "2.6.0")
        self.assertEqual(OFFICIAL_FIRMWARE_MD5, "d5be2c99e436081266810594117db496")

        document = json.loads(self.inventory.read_text(encoding="utf-8"))
        document["hardware_qa_inventory"]["firmware"]["version"] = "2.5"
        self.inventory.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reviewed official 2.6.0"):
            verify_manifest(self.manifest, self.inventory, require_pass=False)

        document["hardware_qa_inventory"]["firmware"]["version"] = "2.6.0"
        document["hardware_qa_inventory"]["firmware"]["expected_md5"] = "0" * 32
        self.inventory.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reviewed official 2.6.0 identity"):
            verify_manifest(self.manifest, self.inventory, require_pass=False)

    def test_complete_synthetic_schema_fixture_verifies(self) -> None:
        self.write_manifest(self.accepted_fixture())
        summary = verify_manifest(self.manifest, self.inventory)
        self.assertEqual(summary["cases"], len(CASE_SPECS))
        self.assertGreater(summary["artifacts"], len(CASE_SPECS))
        self.assertEqual(
            summary["manifest_sha256"],
            hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
        )

    def test_missing_case_and_false_check_fail_closed(self) -> None:
        document = self.accepted_fixture()
        document["hardware_qa"]["cases"].pop()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "exact hardware QA case catalogue"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        first = document["hardware_qa"]["cases"][0]
        first["checks"][next(iter(first["checks"]))] = False
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "not accepted"):
            verify_manifest(self.manifest, self.inventory)

    def test_missing_or_tampered_artifact_fails_closed(self) -> None:
        document = self.accepted_fixture()
        self.write_manifest(document)
        first = document["hardware_qa"]["artifacts"][0]
        (self.evidence / first["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "(size|SHA-256)"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        self.write_manifest(document)
        first = document["hardware_qa"]["artifacts"][0]
        (self.evidence / first["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "evidence file is missing"):
            verify_manifest(self.manifest, self.inventory)

    def test_identity_changes_and_bad_installed_bitstream_fail_closed(self) -> None:
        self.write_manifest(self.accepted_fixture())
        self.firmware.write_bytes(b"changed firmware fixture")
        with self.assertRaisesRegex(ValueError, "firmware update MD5"):
            verify_manifest(self.manifest, self.inventory)

        self.firmware.write_bytes(b"synthetic firmware identity fixture")
        self.installed.write_bytes(b"not bit reversed")
        with self.assertRaisesRegex(ValueError, "sizes differ"):
            verify_manifest(self.manifest, self.inventory)

        self.installed.write_bytes(bytes(len(self.raw_rbf.read_bytes())))
        with self.assertRaisesRegex(ValueError, "not the bit-reversed raw RBF"):
            verify_manifest(self.manifest, self.inventory)

    def test_tiny_bitstream_fails_plausibility_floor(self) -> None:
        tiny = bytes(range(64))
        self.raw_rbf.write_bytes(tiny)
        self.installed.write_bytes(tiny.translate(REVERSE))
        with self.assertRaisesRegex(ValueError, "implausibly small"):
            verify_manifest(self.manifest, self.inventory, require_pass=False)

    def test_overbroad_case_selections_and_artifact_reuse_fail_closed(self) -> None:
        document = self.accepted_fixture()
        first = document["hardware_qa"]["cases"][0]
        first["rom_ids"] = [item["id"] for item in document["hardware_qa"]["environment"]["roms"]]
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "ROM selection does not satisfy any"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        first = document["hardware_qa"]["cases"][0]
        first["controller_ids"] = [item["id"] for item in document["hardware_qa"]["environment"]["controllers"]]
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "controller selection does not satisfy pocket"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        first, second = document["hardware_qa"]["cases"][:2]
        second["artifact_ids"].append(first["artifact_ids"][0])
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "reused by distinct cases"):
            verify_manifest(self.manifest, self.inventory)

    def test_save_negative_case_requires_supported_type01_check(self) -> None:
        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "save_negative_cases"
        )
        self.assertIn("type01_32k_supported", case["checks"])
        case["checks"]["legacy_type01_rejected"] = case["checks"].pop(
            "type01_32k_supported"
        )
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "checks has invalid members"):
            verify_manifest(self.manifest, self.inventory)

    def test_controls_behavior_is_recorded_without_assuming_outcome(self) -> None:
        expected_cases = {
            "pocket_horizontal_input",
            "dock_wired_input",
            "dock_wireless_input",
        }
        by_id = {spec.case_id: spec for spec in CASE_SPECS}
        for case_id in expected_cases:
            self.assertIn("controls_behavior_recorded", by_id[case_id].checks)
            self.assertNotIn("controls_menu_read_only", by_id[case_id].checks)

        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "dock_wired_input"
        )
        case["checks"]["controls_menu_read_only"] = case["checks"].pop(
            "controls_behavior_recorded"
        )
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "checks has invalid members"):
            verify_manifest(self.manifest, self.inventory)

    def test_unreviewed_attestation_and_wrong_native_screenshot_fail_closed(self) -> None:
        document = self.accepted_fixture()
        document["hardware_qa"]["attestation"]["evidence_reviewed"] = False
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "attestation is not accepted"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        native = next(item for item in document["hardware_qa"]["artifacts"] if item["kind"] == "pocket_screenshot")
        path = self.evidence / native["path"]
        contents = self.artifact_bytes("photo")[1]
        path.write_bytes(contents)
        native["size"] = len(contents)
        native["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "native 224x144"):
            verify_manifest(self.manifest, self.inventory)

    def test_refuses_manifest_overwrite(self) -> None:
        original = self.manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            generate_manifest(self.inventory, self.manifest)
        self.assertEqual(self.manifest.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
