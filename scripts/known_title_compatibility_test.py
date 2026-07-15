#!/usr/bin/env python3
"""Offline tests for the known-title evidence contract; no title pass is claimed."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re
import struct
import tempfile
import unittest

from known_title_compatibility import validate_catalogue, verify_manifest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "known-title-compatibility.json"


class KnownTitleCompatibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-known-title-test-")
        self.root = pathlib.Path(self.temporary.name)
        self.manifest = self.root / "manifest.json"
        self.document = json.loads(CATALOGUE.read_text(encoding="utf-8"))
        run = self.document["known_title_compatibility"]["run"]
        run.update(
            {
                "run_id": "synthetic-contract-test",
                "created_at": "2026-07-13T12:00:00Z",
                "operator": "Offline schema test",
                "core_commit": "1" * 40,
                "raw_rbf_sha256": "2" * 64,
                "firmware_version": "2.6.0",
                "pocket_hardware_revision": "synthetic-pocket",
                "dock_hardware_revision": "synthetic-dock",
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, document: dict) -> None:
        self.manifest.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def add_artifact(self, body: dict, kind: str, label: str) -> str:
        artifact_id = f"artifact-{len(body['artifacts']) + 1:04d}"
        suffixes = {
            "pocket_screenshot": ".png",
            "photo": ".jpg",
            "video": ".mp4",
            "save": ".sav",
            "log": ".txt",
            "reference_photo": ".jpg",
            "reference_video": ".mp4",
        }
        if kind in {"video", "reference_video"}:
            data = struct.pack(">I", 24) + b"ftyp" + b"isom" + bytes(32)
        else:
            data = f"synthetic {kind} bytes for {label}\n".encode("utf-8")
        relative = pathlib.PurePosixPath("evidence") / f"{artifact_id}{suffixes[kind]}"
        path = self.root / pathlib.Path(relative)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        body["artifacts"].append(
            {
                "id": artifact_id,
                "kind": kind,
                "path": relative.as_posix(),
                "label": label,
                "captured_at": "2026-07-13T13:00:00Z",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        return artifact_id

    def accepted_fixture(self) -> dict:
        document = copy.deepcopy(self.document)
        body = document["known_title_compatibility"]
        for case in body["cases"]:
            if case["class"] == "commercial":
                case["owner_rom_sha256"] = hashlib.sha256(case["id"].encode("utf-8")).hexdigest()
                case["operator_steps"] = [
                    "Synthetic exact button sequence used only to exercise the schema."
                ]
                reference_ids = [
                    self.add_artifact(
                        body,
                        "reference_video",
                        f"Synthetic reference for {case['id']} scenario {scenario['id']}",
                    )
                    for scenario in case["scenarios"]
                ]
                case["reference"] = {
                    "source": "original_hardware_same_revision",
                    "artifact_ids": reference_ids,
                    "notes": "Synthetic contract bytes, not a real original-hardware observation.",
                }
            else:
                case["reference"] = {
                    "source": "checked_in_open_fixture",
                    "artifact_ids": [],
                    "notes": None,
                }

            for mode_name, mode in case["modes"].items():
                mode.update(
                    {
                        "status": "pass",
                        "started_at": "2026-07-13T13:00:00Z",
                        "completed_at": "2026-07-13T13:05:00Z",
                        "notes": "Synthetic schema coverage only; not physical evidence.",
                    }
                )
                for requirement in case["mode_evidence_requirements"]:
                    kind = requirement["kinds"][0]
                    for _ in range(requirement["minimum"]):
                        mode["artifact_ids"].append(
                            self.add_artifact(
                                body, kind, f"Synthetic {mode_name} evidence for {case['id']}"
                            )
                        )
        body["attestation"] = {
            "physical_hardware_observed": True,
            "results_not_inferred_from_simulation": True,
            "reviewer": "Synthetic schema reviewer",
            "reviewed_at": "2026-07-13T14:00:00Z",
        }
        return document

    def test_checked_in_catalogue_is_exact_pending_and_hash_bound(self) -> None:
        summary = validate_catalogue(CATALOGUE)
        self.assertEqual(summary["cases"], 17)
        self.assertEqual(summary["commercial_cases"], 12)
        self.assertEqual(summary["open_sanity_cases"], 5)
        cases = self.document["known_title_compatibility"]["cases"]
        final_lap = next(case for case in cases if case["id"] == "final-lap-2000-track")
        self.assertEqual(final_lap["title"], "Final Lap 2000")
        self.assertEqual(final_lap["system"], "ws")
        self.assertEqual(
            [scenario["id"] for scenario in final_lap["scenarios"]],
            ["track-flicker", "final-lap-2000-england-start"],
        )
        by_id = {case["id"]: case for case in cases}
        meta_communication = by_id["meta-communication-name-select"]
        self.assertEqual(
            meta_communication["title"],
            "Metakomi Theraphy: Nee Kiite! (upstream shorthand: Meta comm)",
        )
        self.assertEqual(meta_communication["system"], "ws")
        required_issue_roots = {
            "cho-denki-crash": {"https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/3"},
            "meta-communication-name-select": {"https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/4"},
            "star-hearts-trial-rain": {"https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/4"},
            "final-lap-2000-track": {
                "https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/4",
                "https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/30",
            },
            "one-piece-grand-battle-video": {"https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/2"},
            "makaimura-map-scroll": {"https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/12"},
            "romancing-saga-text-box": {"https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/15"},
            "digimon-battle-spirit-1.5-video": {"https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/24"},
            "super-robot-wars-compact-battle": {
                "https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/25",
                "https://github.com/agg23/openfpga-wonderswan/issues/7",
            },
            "engacho-eeprom-persistence": {"https://github.com/agg23/openfpga-wonderswan/issues/3"},
            "another-heaven-eeprom-persistence": {
                "https://github.com/agg23/openfpga-wonderswan/issues/3#issuecomment-1514058112"
            },
            "star-hearts-save-copy-protection": {"https://github.com/agg23/openfpga-wonderswan/issues/2"},
        }
        for case_id, sources in required_issue_roots.items():
            self.assertTrue(sources.issubset(set(by_id[case_id]["source_urls"])), case_id)

    def test_catalogue_rejects_duplicate_members_and_nonstandard_numbers(self) -> None:
        original = CATALOGUE.read_text(encoding="utf-8")
        duplicate = original.replace(
            '"catalogue_revision": 1,',
            '"catalogue_revision": 1,\n    "catalogue_revision": 1,',
            1,
        )
        self.manifest.write_text(duplicate, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate object member 'catalogue_revision'"):
            validate_catalogue(self.manifest)

        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                nonstandard = original.replace(
                    '"catalogue_revision": 1,',
                    f'"catalogue_revision": {constant},',
                    1,
                )
                self.manifest.write_text(nonstandard, encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError,
                    rf"contains non-standard number {re.escape(constant)}",
                ):
                    validate_catalogue(self.manifest)

    def test_final_lap_2000_ws_identity_mutation_fails_closed(self) -> None:
        document = self.accepted_fixture()
        cases = document["known_title_compatibility"]["cases"]
        final_lap = next(case for case in cases if case["id"] == "final-lap-2000-track")
        final_lap["system"] = "wsc"
        self.write(document)
        with self.assertRaisesRegex(ValueError, "system differs from the reviewed catalogue"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

    def test_started_pending_run_verifies_but_cannot_be_accepted(self) -> None:
        self.write(self.document)
        summary = verify_manifest(CATALOGUE, self.manifest)
        self.assertEqual(summary["status"]["pending"], 34)
        with self.assertRaisesRegex(ValueError, "is pending"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

    def test_complete_synthetic_contract_verifies(self) -> None:
        self.write(self.accepted_fixture())
        summary = verify_manifest(CATALOGUE, self.manifest, require_pass=True)
        self.assertEqual(summary["magic"], "SWAN_SONG_KNOWN_TITLE_COMPATIBILITY_V1")
        self.assertEqual(summary["catalogue_revision"], 1)
        self.assertEqual(
            summary["catalogue_sha256"],
            hashlib.sha256(CATALOGUE.read_bytes()).hexdigest(),
        )
        self.assertEqual(summary["cases"], 17)
        self.assertEqual(summary["commercial_cases"], 12)
        self.assertEqual(summary["open_sanity_cases"], 5)
        self.assertEqual(summary["status"], {"pass": 34, "fail": 0, "pending": 0})
        self.assertGreater(summary["artifacts"], 100)
        self.assertEqual(summary["run"]["core_commit"], "1" * 40)
        self.assertEqual(summary["run"]["raw_rbf_sha256"], "2" * 64)

    def test_case_deletion_and_procedure_mutation_fail_closed(self) -> None:
        document = self.accepted_fixture()
        document["known_title_compatibility"]["cases"].pop()
        self.write(document)
        with self.assertRaisesRegex(ValueError, "exact catalogue case count"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

        document = self.accepted_fixture()
        document["known_title_compatibility"]["cases"][0]["scenarios"][0]["steps"].pop()
        self.write(document)
        with self.assertRaisesRegex(ValueError, "differs from the reviewed catalogue"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

    def test_commercial_identity_reference_and_operator_steps_fail_closed(self) -> None:
        document = self.accepted_fixture()
        case = document["known_title_compatibility"]["cases"][0]
        case["owner_rom_sha256"] = None
        self.write(document)
        with self.assertRaisesRegex(ValueError, "owner-computed SHA-256"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

        document = self.accepted_fixture()
        case = document["known_title_compatibility"]["cases"][0]
        case["operator_steps"] = []
        self.write(document)
        with self.assertRaisesRegex(ValueError, "operator_steps is required"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

        document = self.accepted_fixture()
        case = document["known_title_compatibility"]["cases"][0]
        case["reference"]["source"] = "upstream_screenshot"
        self.write(document)
        with self.assertRaisesRegex(ValueError, "original_hardware_same_revision"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

    def test_missing_tampered_and_reused_evidence_fail_closed(self) -> None:
        document = self.accepted_fixture()
        body = document["known_title_compatibility"]
        first_mode = body["cases"][0]["modes"]["pocket"]
        first_mode["artifact_ids"] = first_mode["artifact_ids"][1:]
        self.write(document)
        with self.assertRaisesRegex(ValueError, "requires at least"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

        document = self.accepted_fixture()
        body = document["known_title_compatibility"]
        self.write(document)
        first = body["artifacts"][0]
        (self.root / first["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "(size|SHA-256) mismatch"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

        document = self.accepted_fixture()
        body = document["known_title_compatibility"]
        first_case = body["cases"][0]
        reused = first_case["modes"]["pocket"]["artifact_ids"][0]
        first_case["modes"]["dock"]["artifact_ids"][0] = reused
        self.write(document)
        with self.assertRaisesRegex(ValueError, "artifact .* reused"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

    def test_video_evidence_requires_safe_extension_and_media_signature(self) -> None:
        document = self.accepted_fixture()
        body = document["known_title_compatibility"]
        video = next(item for item in body["artifacts"] if item["kind"] == "video")
        path = self.root / video["path"]
        contents = b"not a media container"
        path.write_bytes(contents)
        video["size"] = len(contents)
        video["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write(document)
        with self.assertRaisesRegex(ValueError, "matching media signature"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

        document = self.accepted_fixture()
        body = document["known_title_compatibility"]
        reference = next(
            item for item in body["artifacts"] if item["kind"] == "reference_video"
        )
        source = self.root / reference["path"]
        replacement = source.with_suffix(".txt")
        source.rename(replacement)
        reference["path"] = replacement.relative_to(self.root).as_posix()
        self.write(document)
        with self.assertRaisesRegex(ValueError, "MP4/MOV/MKV/WebM"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

    def test_mode_and_reference_evidence_timestamps_fail_closed(self) -> None:
        document = self.accepted_fixture()
        body = document["known_title_compatibility"]
        first_mode = body["cases"][0]["modes"]["pocket"]
        first_mode_artifact = first_mode["artifact_ids"][0]
        next(
            item for item in body["artifacts"] if item["id"] == first_mode_artifact
        )["captured_at"] = "2026-07-13T12:59:59Z"
        self.write(document)
        with self.assertRaisesRegex(ValueError, "outside its test interval"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

        document = self.accepted_fixture()
        body = document["known_title_compatibility"]
        reference_artifact = body["cases"][0]["reference"]["artifact_ids"][0]
        next(
            item for item in body["artifacts"] if item["id"] == reference_artifact
        )["captured_at"] = "2026-07-13T11:59:59Z"
        self.write(document)
        with self.assertRaisesRegex(ValueError, "outside the run window"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

        document = self.accepted_fixture()
        body = document["known_title_compatibility"]
        body["cases"][0]["modes"]["pocket"]["started_at"] = "2026-07-13T11:59:59Z"
        self.write(document)
        with self.assertRaisesRegex(ValueError, "starts before the compatibility run"):
            verify_manifest(CATALOGUE, self.manifest, require_complete=True)

    def test_fail_status_is_evidence_complete_but_not_accepted(self) -> None:
        document = self.accepted_fixture()
        document["known_title_compatibility"]["cases"][0]["modes"]["dock"]["status"] = "fail"
        self.write(document)
        summary = verify_manifest(CATALOGUE, self.manifest, require_complete=True)
        self.assertEqual(summary["status"]["fail"], 1)
        with self.assertRaisesRegex(ValueError, "is not a pass"):
            verify_manifest(CATALOGUE, self.manifest, require_pass=True)


if __name__ == "__main__":
    unittest.main()
