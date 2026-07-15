#!/usr/bin/env python3
"""Focused adversarial tests for the production Release Evidence V2 builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import build_release_evidence as builder
from build_chip32 import chip32_image
import known_title_compatibility
import package_core
from package_core import installed_payload_records
from package_validator import validate_distribution
import quartus_fit_audit as fit_audit
import quartus_fit_audit_test as fit_audit_test
from reverse_rbf import REVERSE
import stage_pocket_sd as staging


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40
SOURCE_DATE_EPOCH = 1_700_000_000
CORE_ROOT = Path("Cores/RegionallyFamous.SwanSong")


class BuildReleaseEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="swan-song-release-evidence-test-"
        )
        self.root = Path(self.temporary.name)
        self.artifacts = self.root / "quartus"
        self.artifacts.mkdir()
        fit_audit_test.Fixture(self.artifacts)
        build_id = (
            f"-- Reproducible source commit: {SOURCE_COMMIT}\n"
            f"-- SOURCE_DATE_EPOCH: {SOURCE_DATE_EPOCH}\n"
            "0E0 : 20231114;\n"
            "0E1 : 00221320;\n"
            "0E2 : aaaaaaaa;\n"
        ).encode("utf-8")
        (self.artifacts / "build_id.mif").write_bytes(build_id)
        rbf = self.artifacts / "output_files/ap_core.rbf"
        digest = hashlib.sha256(rbf.read_bytes()).hexdigest()
        (self.artifacts / "ap_core.rbf.sha256").write_text(
            f"{digest}  /artifacts/output_files/ap_core.rbf\n",
            encoding="utf-8",
        )
        audit = fit_audit.audit(self.artifacts)
        (self.artifacts / package_core.QUARTUS_AUDIT_FILENAME).write_text(
            json.dumps(audit, sort_keys=True), encoding="utf-8"
        )
        self.signed_b = self.root / "quartus-b"
        self.signed_b.mkdir()
        fit_audit_test.Fixture(
            self.signed_b,
            workflow_run_id="200",
            workflow_job_nonce="2" * 32,
        )
        (self.signed_b / "build_id.mif").write_bytes(build_id)
        b_rbf = self.signed_b / "output_files/ap_core.rbf"
        b_digest = hashlib.sha256(b_rbf.read_bytes()).hexdigest()
        (self.signed_b / "ap_core.rbf.sha256").write_text(
            f"{b_digest}  /artifacts/output_files/ap_core.rbf\n",
            encoding="utf-8",
        )
        (self.signed_b / "quartus-audit-candidate.attestation.json").write_text(
            '{"synthetic":"attestation-b"}\n', encoding="utf-8"
        )
        audit_b = fit_audit.audit(self.signed_b)
        (self.signed_b / package_core.QUARTUS_AUDIT_FILENAME).write_text(
            json.dumps(audit_b, sort_keys=True), encoding="utf-8"
        )

        def identity(path: Path, filename: str) -> dict[str, object]:
            payload = path.read_bytes()
            return {
                "filename": filename,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

        builds = []
        for label, root, run_id, nonce in (
            ("a", self.artifacts, 100, "0" * 32),
            ("b", self.signed_b, 200, "2" * 32),
        ):
            audit_path = root / package_core.QUARTUS_AUDIT_FILENAME
            audit_document = json.loads(audit_path.read_text(encoding="utf-8"))
            canonical_audit = json.dumps(
                audit_document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
            audit_identity = identity(
                audit_path,
                f"signed-builds/{label}/{package_core.QUARTUS_AUDIT_FILENAME}",
            )
            builds.append(
                {
                    "label": label,
                    "repository": "RegionallyFamous/swan-song",
                    "workflow_path": ".github/workflows/quartus-fit.yml",
                    "source_ref": "refs/heads/main",
                    "source_commit": SOURCE_COMMIT,
                    "run_id": run_id,
                    "run_attempt": 1,
                    "job": "fit",
                    "job_nonce": nonce,
                    "runner_environment": "self-hosted",
                    "candidate_audit": audit_identity,
                    "attestation_bundle": identity(
                        root / "quartus-audit-candidate.attestation.json",
                        (
                            f"signed-builds/{label}/"
                            "quartus-audit-candidate.attestation.json"
                        ),
                    ),
                    "recomputed_audit_sha256": hashlib.sha256(
                        canonical_audit
                    ).hexdigest(),
                    "submitted_audit_sha256": audit_identity["sha256"],
                }
            )
        self.signed_build_origins = {
            "magic": "SWAN_SONG_SIGNED_BUILD_PAIR_V1",
            "source_commit": SOURCE_COMMIT,
            "source_date_epoch": SOURCE_DATE_EPOCH,
            "rbf": identity(rbf, "ap_core.rbf"),
            "build_id": identity(self.artifacts / "build_id.mif", "build_id.mif"),
            "builds": builds,
        }

        self.qa = self.root / "qa"
        private = self.qa / "private"
        private.mkdir(parents=True)
        for name, payload in (
            ("firmware.bin", b"firmware"),
            ("pocket-id.txt", b"pocket"),
            ("dock-id.txt", b"dock"),
            ("bw.rom", b"bw"),
            ("color.rom", b"color"),
            ("game.ws", b"rom"),
        ):
            (private / name).write_bytes(payload)
        capture = self.qa / "captures/result.log"
        capture.parent.mkdir()
        capture.write_text("physical observation\n", encoding="utf-8")

        self.dist = self.root / "dist"
        shutil.copytree(ROOT / "dist", self.dist)
        core_json = self.dist / CORE_ROOT / "core.json"
        definition = json.loads(core_json.read_text(encoding="utf-8"))["core"]
        bitstream_name = definition["cores"][0]["filename"]
        chip32_name = definition["framework"]["chip32_vm"]
        raw_rbf = rbf.read_bytes()
        installed_rbf = raw_rbf.translate(REVERSE)
        installed_root = self.qa / "sd"
        for source in self.dist.rglob("*"):
            if source.is_file():
                relative = source.relative_to(self.dist)
                destination = installed_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        (installed_root / CORE_ROOT / bitstream_name).write_bytes(installed_rbf)
        chip32 = chip32_image(
            ROOT / "src/support/chip32.asm", ROOT / "src/support/chip32.bin.hex"
        )
        (installed_root / CORE_ROOT / chip32_name).write_bytes(chip32)
        raw_copy = self.qa / "build/output_files/ap_core.rbf"
        raw_copy.parent.mkdir(parents=True)
        raw_copy.write_bytes(raw_rbf)

        self.inventory = self.qa / "inventory.json"
        inventory = {
            "hardware_qa_inventory": {
                "magic": "SWAN_SONG_HARDWARE_QA_INVENTORY_V2",
                "run_id": "synthetic-release-evidence",
                "created_at": "2026-07-14T12:00:00Z",
                "operator": {"name": "Test", "organization": "Test"},
                "firmware": {
                    "version": "2.6.0",
                    "update_path": "private/firmware.bin",
                    "expected_md5": "0" * 32,
                },
                "pocket": {
                    "model": "Analogue Pocket",
                    "hardware_revision": "test",
                    "device_id_path": "private/pocket-id.txt",
                },
                "dock": {
                    "model": "Analogue Dock",
                    "hardware_revision": "test",
                    "firmware_version": "test",
                    "device_id_path": "private/dock-id.txt",
                },
                "core": {
                    "installed_dist_path": "sd",
                    "core_json_path": "sd/Cores/RegionallyFamous.SwanSong/core.json",
                    "interact_json_path": "sd/Cores/RegionallyFamous.SwanSong/interact.json",
                    "raw_rbf_path": "build/output_files/ap_core.rbf",
                    "installed_bitstream_path": (
                        "sd/Cores/RegionallyFamous.SwanSong/" + bitstream_name
                    ),
                },
                "bios": [
                    {"id": "bw", "path": "private/bw.rom"},
                    {"id": "color", "path": "private/color.rom"},
                ],
                "roms": [
                    {
                        "id": "test-rom",
                        "title": "Test",
                        "path": "private/game.ws",
                        "system": "ws",
                        "native_orientation": "horizontal",
                        "save_media": "none",
                        "rtc": False,
                    }
                ],
                "controllers": [],
            }
        }
        self.inventory.write_text(
            json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.manifest = self.qa / "manifest.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "hardware_qa": {
                        "artifacts": [
                            {
                                "id": "physical-log",
                                "path": "captures/result.log",
                            }
                        ]
                    }
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        compatibility_capture = self.qa / "compatibility/observed.log"
        compatibility_capture.parent.mkdir()
        compatibility_capture.write_text(
            "synthetic known-title observation\n", encoding="utf-8"
        )
        self.known_title_manifest = self.qa / "known-title-manifest.json"
        self.known_title_manifest.write_text(
            json.dumps(
                {
                    "known_title_compatibility": {
                        "run": {
                            "run_id": "synthetic-known-title-run",
                            "core_commit": SOURCE_COMMIT,
                            "raw_rbf_sha256": hashlib.sha256(raw_rbf).hexdigest(),
                            "firmware_version": "2.6.0",
                        },
                        "artifacts": [
                            {
                                "id": "synthetic-known-title-artifact",
                                "path": "compatibility/observed.log",
                            }
                        ],
                    }
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        metadata = definition["metadata"]
        core_json_bytes = core_json.read_bytes()
        interact_json_bytes = (self.dist / CORE_ROOT / "interact.json").read_bytes()
        self.hardware_core = {
            "core_id": "RegionallyFamous.SwanSong",
            "version": metadata["version"],
            "date_release": metadata["date_release"],
            "core_json": {
                "filename": "core.json",
                "size": len(core_json_bytes),
                "sha256": hashlib.sha256(core_json_bytes).hexdigest(),
            },
            "interact_json": {
                "filename": "interact.json",
                "size": len(interact_json_bytes),
                "sha256": hashlib.sha256(interact_json_bytes).hexdigest(),
            },
            "persistent_settings": list(
                package_core.HARDWARE_QA_PERSISTENT_SETTING_NAMES
            ),
            "raw_rbf": {
                "filename": rbf.name,
                "size": len(raw_rbf),
                "sha256": hashlib.sha256(raw_rbf).hexdigest(),
            },
            "installed_bitstream": {
                "filename": bitstream_name,
                "size": len(installed_rbf),
                "sha256": hashlib.sha256(installed_rbf).hexdigest(),
            },
            "installed_payloads": installed_payload_records(
                dist=self.dist,
                bitstream_name=bitstream_name,
                bitstream=installed_rbf,
                chip32_name=chip32_name,
                chip32=chip32,
            ),
        }
        self.patches = (
            mock.patch.object(
                builder,
                "verify_hardware_qa_manifest",
                side_effect=self.verify_synthetic_hardware,
            ),
            mock.patch.object(
                package_core,
                "verify_hardware_qa_manifest",
                side_effect=self.verify_synthetic_hardware,
            ),
            mock.patch.object(
                builder,
                "verify_known_title_manifest",
                side_effect=self.verify_synthetic_known_title,
            ),
            mock.patch.object(
                package_core,
                "verify_known_title_compatibility_manifest",
                side_effect=self.verify_synthetic_known_title,
            ),
            mock.patch.object(
                package_core,
                "_verify_signed_origin_attestation",
                side_effect=self.verify_synthetic_signed_origin,
            ),
        )
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_relocated_catalogue_snapshots_open_fixtures_and_validates_unmocked(self) -> None:
        destination = self.root / "relocated-known-title"
        destination.mkdir()
        catalogue_copy = destination / builder.KNOWN_TITLE_CATALOGUE_FILENAME
        catalogue_payload = builder.KNOWN_TITLE_CATALOGUE.read_bytes()
        catalogue_copy.write_bytes(catalogue_payload)
        catalogue_document = json.loads(catalogue_payload.decode("utf-8"))

        builder._relocate_known_title_catalogue_fixtures(
            catalogue_path=builder.KNOWN_TITLE_CATALOGUE,
            catalogue_document=catalogue_document,
            destination_root=destination,
        )

        summary = known_title_compatibility.validate_catalogue(catalogue_copy)
        self.assertEqual(summary["open_sanity_cases"], 5)
        body = catalogue_document["known_title_compatibility"]
        open_cases = [
            case for case in body["cases"] if case["class"] == "open_sanity"
        ]
        self.assertEqual(len(open_cases), 5)
        for case in open_cases:
            fixture = destination / case["fixture_path"]
            self.assertTrue(fixture.is_file())
            self.assertEqual(
                hashlib.sha256(fixture.read_bytes()).hexdigest(),
                case["fixture_sha256"],
            )

        bad_hash_document = json.loads(catalogue_payload.decode("utf-8"))
        bad_hash_case = next(
            case
            for case in bad_hash_document["known_title_compatibility"]["cases"]
            if case["class"] == "open_sanity"
        )
        bad_hash_case["fixture_sha256"] = "0" * 64
        bad_hash_destination = self.root / "bad-known-title-hash"
        bad_hash_destination.mkdir()
        with self.assertRaisesRegex(
            builder.ReleaseEvidenceError, "does not match its catalogue SHA-256"
        ):
            builder._relocate_known_title_catalogue_fixtures(
                catalogue_path=builder.KNOWN_TITLE_CATALOGUE,
                catalogue_document=bad_hash_document,
                destination_root=bad_hash_destination,
            )

        (destination / open_cases[0]["fixture_path"]).unlink()
        with self.assertRaisesRegex(ValueError, "fixture_path is missing"):
            known_title_compatibility.validate_catalogue(catalogue_copy)

    def verify_synthetic_hardware(
        self,
        manifest_path: Path,
        inventory_path: Path,
        *,
        require_pass: bool = True,
    ) -> dict[str, object]:
        self.assertTrue(require_pass)
        return {
            "magic": package_core.HARDWARE_QA_MANIFEST_MAGIC,
            "run_id": "synthetic-release-evidence",
            "cases": len(package_core.HARDWARE_QA_CASE_SPECS),
            "artifacts": 1,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
            "firmware_version": "2.6.0",
            "core": self.hardware_core,
            "pocket": {
                "model": "Analogue Pocket",
                "hardware_revision": "test",
                "device_id_sha256": "1" * 64,
            },
            "dock": {
                "model": "Analogue Dock",
                "hardware_revision": "test",
                "firmware_version": "test",
                "device_id_sha256": "2" * 64,
            },
        }

    def verify_synthetic_known_title(
        self,
        catalogue_path: Path,
        manifest_path: Path,
        *,
        require_pass: bool = True,
    ) -> dict[str, object]:
        self.assertTrue(require_pass)
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        body = document["known_title_compatibility"]
        run = body["run"]
        return {
            "magic": package_core.KNOWN_TITLE_COMPATIBILITY_MAGIC,
            "catalogue_revision": 1,
            "catalogue_sha256": hashlib.sha256(catalogue_path.read_bytes()).hexdigest(),
            "required_firmware_version": "2.6.0",
            "cases": len(package_core.KNOWN_TITLE_COMMERCIAL_IDS)
            + len(package_core.KNOWN_TITLE_OPEN_IDS),
            "commercial_cases": len(package_core.KNOWN_TITLE_COMMERCIAL_IDS),
            "open_sanity_cases": len(package_core.KNOWN_TITLE_OPEN_IDS),
            "artifacts": len(body["artifacts"]),
            "status": {"pass": 34, "fail": 0, "pending": 0},
            "artifact_index_sha256": "7" * 64,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "run": run,
        }

    def verify_synthetic_signed_origin(
        self, *, candidate: Path, bundle: Path, source_commit: str
    ) -> dict[str, object]:
        """Stand in only for Sigstore crypto in synthetic offline fixtures."""

        self.assertEqual(source_commit, SOURCE_COMMIT)
        self.assertTrue(candidate.is_file())
        self.assertTrue(bundle.is_file())
        run_ids = {"a": 100, "b": 200}
        label = candidate.parent.name
        self.assertIn(label, run_ids)
        return {
            "run_id": run_ids[label],
            "run_attempt": 1,
            "runner_environment": "self-hosted",
        }

    def build(self, name: str = "release-bundle", **overrides: object) -> Path:
        arguments: dict[str, object] = {
            "artifacts": self.artifacts,
            "signed_artifacts": (self.artifacts, self.signed_b),
            "signed_build_origins": self.signed_build_origins,
            "hardware_manifest": self.manifest,
            "hardware_inventory": self.inventory,
            "known_title_manifest": self.known_title_manifest,
            "output": self.root / name / builder.RELEASE_EVIDENCE_FILENAME,
            "source_commit": SOURCE_COMMIT,
            "source_date_epoch": SOURCE_DATE_EPOCH,
            "compressed_bitstream_reviewed": True,
        }
        arguments.update(overrides)
        return builder.build_release_evidence(**arguments)  # type: ignore[arg-type]

    def test_build_is_deterministic_and_consumable_by_packager_validator(self) -> None:
        first = self.build("first")
        second = self.build("second")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(
            (first.parent / "captures/result.log").read_text(encoding="utf-8"),
            "physical observation\n",
        )
        self.assertEqual(
            (first.parent / "private/game.ws").read_bytes(), b"rom"
        )
        self.assertEqual(
            (first.parent / "compatibility/observed.log").read_text(encoding="utf-8"),
            "synthetic known-title observation\n",
        )
        rbf = first.parent / "output_files/ap_core.rbf"
        validated = package_core.validate_build_evidence(
            first, rbf.read_bytes(), rbf.name
        )
        self.assertEqual(validated["magic"], package_core.RELEASE_EVIDENCE_V2)
        self.assertEqual(
            validated["known_title_compatibility"]["run_id"],
            "synthetic-known-title-run",
        )
        self.assertEqual(validated["source_commit"], SOURCE_COMMIT)
        self.assertTrue(all(validated["gates"].values()))

    @staticmethod
    def source_inputs(dist: Path, rbf: Path) -> dict[str, object]:
        tracked: dict[str, dict[str, object]] = {}
        directories: list[str] = []
        for path in sorted(dist.rglob("*")):
            relative = "dist/" + path.relative_to(dist).as_posix()
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
        for relative in (
            "src/support/chip32.asm",
            "src/support/chip32.bin.hex",
        ):
            payload = (ROOT / relative).read_bytes()
            tracked[relative] = {
                "git_blob": hashlib.sha1(
                    b"blob " + str(len(payload)).encode() + b"\0" + payload
                ).hexdigest(),
                "mode": "100644",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        rbf_payload = rbf.read_bytes()
        return {
            "magic": package_core.RELEASE_SOURCE_INPUTS_V1,
            "repository": package_core.EXPECTED_REPOSITORY,
            "source_commit": SOURCE_COMMIT,
            "source_tree": "c" * 40,
            "dist_directory": "dist",
            "dist_directories": directories,
            "chip32_assembly": "src/support/chip32.asm",
            "chip32_encoded_image": "src/support/chip32.bin.hex",
            "tracked_files": tracked,
            "raw_rbf": {
                "filename": rbf.name,
                "size": len(rbf_payload),
                "sha256": hashlib.sha256(rbf_payload).hexdigest(),
            },
        }

    def test_generated_evidence_drives_release_package_and_verified_stage(self) -> None:
        evidence = self.build("integration")
        rbf = evidence.parent / "output_files/ap_core.rbf"
        release_dist = self.root / "release-dist"
        shutil.copytree(self.dist, release_dist)
        license_path = release_dist / CORE_ROOT / "LICENSE-MANIFEST.json"
        license_document = json.loads(license_path.read_text(encoding="utf-8"))
        license_body = license_document["license_manifest"]
        for component in license_body["components"]:
            if component["review_status"] == "review_required":
                component["review_status"] = "documented"
                component["blocker"] = None
                if component["license_expression"] == "NOASSERTION":
                    component["license_expression"] = "LicenseRef-Test-Reviewed"
        for requirement in license_body["requirements"]:
            requirement["review_status"] = "documented"
            requirement["blocker"] = None
        license_body["release_gate"] = {
            "licensing_review_complete": True,
            "unresolved_ids": [],
        }
        license_path.write_text(
            json.dumps(license_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        policy_document = json.loads(
            (ROOT / "release-policy.json").read_text(encoding="utf-8")
        )
        policy_document["release_policy"]["authorization"][
            "distribution_and_licensing_authorized"
        ] = True
        policy = self.root / "authorized-policy.json"
        policy.write_text(
            json.dumps(policy_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        definition = validate_distribution(release_dist)
        package = self.root / definition.recommended_archive_name
        source_inputs = self.source_inputs(release_dist, rbf)
        chip32 = chip32_image(
            ROOT / "src/support/chip32.asm", ROOT / "src/support/chip32.bin.hex"
        )
        with mock.patch.object(
            package_core, "validate_release_source_checkout", return_value=source_inputs
        ), mock.patch.object(
            package_core, "release_chip32_image", return_value=chip32
        ):
            package_core.create_package(
                dist=release_dist,
                rbf=rbf,
                output=package,
                chip32_assembly=ROOT / "src/support/chip32.asm",
                chip32_encoded_image=ROOT / "src/support/chip32.bin.hex",
                build_evidence=evidence,
                release_policy=policy,
                release=True,
            )

        provenance = package.with_name(package.name + ".provenance.json")
        stage = self.root / "release-stage"
        stage.mkdir()
        with mock.patch.object(staging, "RELEASE_POLICY", policy):
            plan = staging.plan_staging(
                staging_dir=stage,
                package=package,
                provenance=provenance,
                bw_bios=None,
                color_bios=None,
                verify_release=True,
                expected_package_sha256=hashlib.sha256(package.read_bytes()).hexdigest(),
                expected_provenance_sha256=hashlib.sha256(
                    provenance.read_bytes()
                ).hexdigest(),
                expected_version=definition.version,
                expected_source_commit=SOURCE_COMMIT,
            )
            staging.apply_staging(plan)
        self.assertTrue((stage / CORE_ROOT / "core.json").is_file())

    def test_requires_explicit_compression_review_without_creating_output(self) -> None:
        output = self.root / "unreviewed" / builder.RELEASE_EVIDENCE_FILENAME
        with self.assertRaisesRegex(
            builder.ReleaseEvidenceError, "compressed-bitstream-reviewed"
        ):
            self.build(
                "unreviewed", compressed_bitstream_reviewed=False
            )
        self.assertFalse(output.parent.exists())

    def test_rejects_explicit_source_identity_drift_atomically(self) -> None:
        output = self.root / "wrong-source" / builder.RELEASE_EVIDENCE_FILENAME
        with self.assertRaisesRegex(
            builder.ReleaseEvidenceError, "do not match the accepted Quartus audit"
        ):
            self.build("wrong-source", source_commit="b" * 40)
        self.assertFalse(output.parent.exists())

    def test_rejects_mutated_quartus_bundle_atomically(self) -> None:
        output = self.root / "mutated" / builder.RELEASE_EVIDENCE_FILENAME
        with (self.artifacts / "quartus.log").open("ab") as stream:
            stream.write(b"post-audit mutation\n")
        with self.assertRaisesRegex(
            builder.ReleaseEvidenceError, "Quartus evidence collection failed"
        ):
            self.build("mutated")
        self.assertFalse(output.parent.exists())

    def test_rejects_hardware_relative_path_escape_even_after_mocked_acceptance(self) -> None:
        document = json.loads(self.inventory.read_text(encoding="utf-8"))
        document["hardware_qa_inventory"]["firmware"]["update_path"] = "../escape"
        self.inventory.write_text(json.dumps(document), encoding="utf-8")
        output = self.root / "escape" / builder.RELEASE_EVIDENCE_FILENAME
        with self.assertRaisesRegex(builder.ReleaseEvidenceError, "safe relative path"):
            self.build("escape")
        self.assertFalse(output.parent.exists())

    def test_rejects_known_title_rbf_identity_drift_atomically(self) -> None:
        document = json.loads(self.known_title_manifest.read_text(encoding="utf-8"))
        document["known_title_compatibility"]["run"]["raw_rbf_sha256"] = "0" * 64
        self.known_title_manifest.write_text(json.dumps(document), encoding="utf-8")
        output = self.root / "known-title-rbf-drift" / builder.RELEASE_EVIDENCE_FILENAME
        with self.assertRaisesRegex(builder.ReleaseEvidenceError, "known-title.*raw RBF"):
            self.build("known-title-rbf-drift")
        self.assertFalse(output.parent.exists())

    def test_refuses_to_overwrite_an_existing_bundle(self) -> None:
        bundle = self.root / "existing"
        bundle.mkdir()
        (bundle / "keep.txt").write_text("keep\n", encoding="utf-8")
        with self.assertRaisesRegex(builder.ReleaseEvidenceError, "must not already exist"):
            self.build("existing")
        self.assertEqual((bundle / "keep.txt").read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
