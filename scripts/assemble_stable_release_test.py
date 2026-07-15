#!/usr/bin/env python3
"""Signed integration and adversarial tests for stable release assembly."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
import tarfile
import unittest
from unittest import mock

import assemble_stable_release as assembler
from package_validator import validate_distribution
import quartus_fit_audit
import quartus_fit_audit_test


SOURCE_COMMIT = "a" * 40
SOURCE_DATE_EPOCH = 1_700_000_000


def make_candidate(
    root: Path,
    *,
    rbf: bytes = b"fixture-rbf\x01",
    build_id: bytes | None = None,
    workflow_run_id: str = "101",
    workflow_job_nonce: str = "1" * 32,
) -> None:
    root.mkdir()
    quartus_fit_audit_test.Fixture(
        root,
        workflow_run_id=workflow_run_id,
        workflow_job_nonce=workflow_job_nonce,
    )
    (root / "output_files/ap_core.rbf").write_bytes(rbf)
    if build_id is not None:
        (root / "build_id.mif").write_bytes(build_id)
    digest = hashlib.sha256(rbf).hexdigest()
    (root / "ap_core.rbf.sha256").write_text(
        f"{digest}  /artifacts/output_files/ap_core.rbf\n", encoding="utf-8"
    )
    document = quartus_fit_audit.audit(root)
    (root / "quartus-audit-candidate.json").write_text(
        json.dumps(document, sort_keys=True), encoding="utf-8"
    )


class StableReleaseBuildPairTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="swan-song-stable-pair-test-"
        )
        self.root = Path(self.temporary.name)
        self.a = self.root / "a"
        self.b = self.root / "b"
        make_candidate(self.a, workflow_run_id="101", workflow_job_nonce="1" * 32)
        make_candidate(self.b, workflow_run_id="102", workflow_job_nonce="2" * 32)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def pair(self) -> assembler.BuildPair:
        scratch = self.root / "scratch"
        scratch.mkdir()
        def fake_attestation(**arguments: object) -> dict[str, object]:
            identity = dict(arguments["workflow_identity"])
            candidate = Path(arguments["candidate"])
            bundle = Path(arguments["bundle"])
            return {
                "repository": assembler.ATTESTATION_REPOSITORY,
                "workflow_path": ".github/workflows/quartus-fit.yml",
                "source_ref": assembler.ATTESTATION_SOURCE_REF,
                "source_commit": SOURCE_COMMIT,
                "run_id": int(identity["workflow_run_id"]),
                "run_attempt": int(identity["workflow_run_attempt"]),
                "job": "fit",
                "job_nonce": identity["workflow_job_nonce"],
                "runner_environment": "self-hosted",
                "candidate_audit": assembler._identity(candidate),
                "attestation_bundle": assembler._identity(bundle),
            }

        with mock.patch.object(
            assembler, "_verify_candidate_attestation", side_effect=fake_attestation
        ):
            return assembler.snapshot_and_audit_pair(
                artifacts_a=self.a,
                artifacts_b=self.b,
                scratch=scratch,
                source_commit=SOURCE_COMMIT,
                source_date_epoch=SOURCE_DATE_EPOCH,
            )

    def test_accepts_two_complete_passed_identical_candidates(self) -> None:
        pair = self.pair()
        self.assertEqual(pair.rbf["sha256"], hashlib.sha256(b"fixture-rbf\x01").hexdigest())
        self.assertNotEqual(pair.audit_sha256[0], pair.audit_sha256[1])
        self.assertEqual([item["run_id"] for item in pair.attestations], [101, 102])
        self.assertTrue(pair.audits[0]["audit_pass"])
        self.assertTrue(pair.audits[1]["audit_pass"])

    def test_rejects_one_bundle_supplied_twice(self) -> None:
        scratch = self.root / "same-scratch"
        scratch.mkdir()
        with self.assertRaisesRegex(assembler.AssemblyError, "distinct bundles"):
            assembler.snapshot_and_audit_pair(
                artifacts_a=self.a,
                artifacts_b=self.a,
                scratch=scratch,
                source_commit=SOURCE_COMMIT,
                source_date_epoch=SOURCE_DATE_EPOCH,
            )

    def test_rejects_candidate_copied_to_a_different_directory(self) -> None:
        shutil.rmtree(self.b)
        shutil.copytree(self.a, self.b)
        with self.assertRaisesRegex(assembler.AssemblyError, "signed workflow run IDs"):
            self.pair()

    def test_rejects_same_identity_even_when_bundle_bytes_differ(self) -> None:
        shutil.rmtree(self.b)
        make_candidate(
            self.b, workflow_run_id="101", workflow_job_nonce="1" * 32
        )
        with (self.b / "quartus.log").open("ab") as stream:
            stream.write(b"Info: distinct log bytes\n")
        document = quartus_fit_audit.audit(self.b)
        (self.b / "quartus-audit-candidate.json").write_text(
            json.dumps(document, sort_keys=True), encoding="utf-8"
        )
        with self.assertRaisesRegex(assembler.AssemblyError, "signed workflow run IDs"):
            self.pair()

    def test_rejects_missing_workflow_identity(self) -> None:
        metadata = self.b / "build-metadata.txt"
        metadata.write_text(
            "\n".join(
                line
                for line in metadata.read_text(encoding="utf-8").splitlines()
                if not line.startswith("workflow_job_nonce=")
            )
            + "\n",
            encoding="utf-8",
        )
        candidate = self.b / "quartus-audit-candidate.json"
        document = json.loads(candidate.read_text(encoding="utf-8"))
        document["quartus_audit"]["artifacts"]["build-metadata.txt"] = (
            quartus_fit_audit.digest(metadata)
        )
        candidate.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        with self.assertRaisesRegex(assembler.AssemblyError, "workflow_job_nonce"):
            self.pair()

    def test_rejects_different_rbf_even_when_each_audit_passes(self) -> None:
        for path in self.b.rglob("*"):
            if path.is_file():
                path.unlink()
        for path in sorted(self.b.rglob("*"), reverse=True):
            if path.is_dir():
                path.rmdir()
        self.b.rmdir()
        make_candidate(
            self.b,
            rbf=b"fixture-rbf\x02",
            workflow_run_id="102",
            workflow_job_nonce="2" * 32,
        )
        with self.assertRaisesRegex(assembler.AssemblyError, "RBF outputs"):
            self.pair()

    def test_rejects_different_build_id_even_when_each_audit_passes(self) -> None:
        (self.b / "build_id.mif").write_bytes(b"different-build-id\n")
        document = quartus_fit_audit.audit(self.b)
        (self.b / "quartus-audit-candidate.json").write_text(
            json.dumps(document, sort_keys=True), encoding="utf-8"
        )
        with self.assertRaisesRegex(assembler.AssemblyError, "build IDs"):
            self.pair()

    def test_rejects_failed_second_audit(self) -> None:
        fit = self.b / "output_files/ap_core.fit.rpt"
        fit.write_text(
            fit.read_text(encoding="utf-8").replace(
                "280 / 308 (91%)", "290 / 308 (94%)"
            ),
            encoding="utf-8",
        )
        document = quartus_fit_audit.audit(self.b)
        self.assertFalse(document["quartus_audit"]["audit_pass"])
        (self.b / "quartus-audit-candidate.json").write_text(
            json.dumps(document, sort_keys=True), encoding="utf-8"
        )
        with self.assertRaisesRegex(assembler.AssemblyError, "not accepted"):
            self.pair()

    def test_public_provenance_refuses_bytes_changed_after_attestation(self) -> None:
        pair = self.pair()
        candidate = pair.snapshots[1] / assembler.package_core.QUARTUS_AUDIT_FILENAME
        candidate.write_bytes(candidate.read_bytes() + b"\n")
        with self.assertRaisesRegex(assembler.AssemblyError, "changed after verification"):
            assembler._signed_provenance_archive_bytes(
                pair, source_date_epoch=SOURCE_DATE_EPOCH
            )


class StableReleaseAttestationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="swan-song-attestation-test-"
        )
        self.root = Path(self.temporary.name)
        self.candidate = self.root / "quartus-audit-candidate.json"
        self.bundle = self.root / assembler.ATTESTATION_FILENAME
        self.candidate.write_bytes(b'{"candidate":"audit"}\n')
        self.bundle.write_bytes(b'{"synthetic":"sigstore-bundle"}\n')
        self.workflow_identity = {
            "workflow_repository": "RegionallyFamous/swan-song",
            "workflow_path": ".github/workflows/quartus-fit.yml",
            "workflow_sha": SOURCE_COMMIT,
            "workflow_run_id": "101",
            "workflow_run_attempt": "2",
            "workflow_job": "fit",
            "workflow_job_nonce": "1" * 32,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def verification_payload(self) -> list[dict[str, object]]:
        signer = (
            "https://github.com/RegionallyFamous/swan-song/"
            ".github/workflows/quartus-fit.yml@refs/heads/main"
        )
        return [
            {
                "verificationResult": {
                    "signature": {
                        "certificate": {
                            "githubWorkflowTrigger": "workflow_dispatch",
                            "githubWorkflowSHA": SOURCE_COMMIT,
                            "githubWorkflowRepository": "RegionallyFamous/swan-song",
                            "githubWorkflowRef": "refs/heads/main",
                            "buildSignerURI": signer,
                            "buildSignerDigest": SOURCE_COMMIT,
                            "runnerEnvironment": "self-hosted",
                            "sourceRepositoryURI": (
                                "https://github.com/RegionallyFamous/swan-song"
                            ),
                            "sourceRepositoryDigest": SOURCE_COMMIT,
                            "sourceRepositoryRef": "refs/heads/main",
                            "buildConfigURI": signer,
                            "buildConfigDigest": SOURCE_COMMIT,
                            "buildTrigger": "workflow_dispatch",
                            "runInvocationURI": (
                                "https://github.com/RegionallyFamous/swan-song/"
                                "actions/runs/101/attempts/2"
                            ),
                        }
                    },
                    "verifiedTimestamps": [
                        {"type": "Tlog", "timestamp": "2026-07-14T12:00:00Z"}
                    ],
                    "statement": {
                        "subject": [
                            {
                                "name": "quartus-audit-candidate.json",
                                "digest": {
                                    "sha256": hashlib.sha256(
                                        self.candidate.read_bytes()
                                    ).hexdigest()
                                },
                            }
                        ]
                    },
                }
            }
        ]

    def verify(self, payload: object) -> tuple[dict[str, object], mock.Mock]:
        completed = SimpleNamespace(
            stdout=json.dumps(payload), stderr="", returncode=0
        )
        runner = mock.Mock(return_value=completed)
        with mock.patch.object(assembler.subprocess, "run", runner):
            result = assembler._verify_candidate_attestation(
                candidate=self.candidate,
                bundle=self.bundle,
                source_commit=SOURCE_COMMIT,
                workflow_identity=self.workflow_identity,
            )
        return result, runner

    def test_requires_official_online_trust_and_exact_signed_origin(self) -> None:
        result, runner = self.verify(self.verification_payload())
        self.assertEqual(result["run_id"], 101)
        self.assertEqual(result["run_attempt"], 2)
        self.assertEqual(result["job_nonce"], "1" * 32)
        command = runner.call_args.args[0]
        self.assertIn("--repo", command)
        self.assertIn("--signer-workflow", command)
        self.assertIn("--source-digest", command)
        self.assertIn("--source-ref", command)
        self.assertIn("--bundle", command)
        self.assertNotIn("--custom-trusted-root", command)

    def test_rejects_signed_run_that_disagrees_with_metadata(self) -> None:
        payload = self.verification_payload()
        payload[0]["verificationResult"]["signature"]["certificate"][
            "runInvocationURI"
        ] = (
            "https://github.com/RegionallyFamous/swan-song/"
            "actions/runs/999/attempts/2"
        )
        with self.assertRaisesRegex(assembler.AssemblyError, "run invocation"):
            self.verify(payload)

    def test_rejects_missing_timestamp_or_wrong_subject(self) -> None:
        payload = self.verification_payload()
        payload[0]["verificationResult"]["verifiedTimestamps"] = []
        with self.assertRaisesRegex(assembler.AssemblyError, "timestamp"):
            self.verify(payload)

        payload = self.verification_payload()
        payload[0]["verificationResult"]["statement"]["subject"][0]["digest"] = {
            "sha256": "0" * 64
        }
        with self.assertRaisesRegex(assembler.AssemblyError, "subject"):
            self.verify(payload)


class StableReleaseAssemblyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="swan-song-stable-assembly-test-"
        )
        self.root = Path(self.temporary.name)
        self.definition = validate_distribution(assembler.DIST)
        self.rbf_payload = b"accepted-rbf"
        self.build_id_payload = b"accepted-build-id\n"
        self.patches: list[mock._patch] = []

        def fake_pair(**arguments: object) -> assembler.BuildPair:
            scratch = Path(arguments["scratch"])
            snapshots = (scratch / "quartus-a", scratch / "quartus-b")
            attestations: list[dict[str, object]] = []
            for index, snapshot in enumerate(snapshots):
                (snapshot / "output_files").mkdir(parents=True)
                (snapshot / "output_files/ap_core.rbf").write_bytes(self.rbf_payload)
                (snapshot / "build_id.mif").write_bytes(self.build_id_payload)
                audit = (f'{{"synthetic":"audit-{index}"}}\n').encode("ascii")
                bundle = (f'{{"synthetic":"bundle-{index}"}}\n').encode("ascii")
                (snapshot / assembler.package_core.QUARTUS_AUDIT_FILENAME).write_bytes(
                    audit
                )
                (snapshot / assembler.ATTESTATION_FILENAME).write_bytes(bundle)
                attestations.append(
                    {
                        "repository": assembler.ATTESTATION_REPOSITORY,
                        "workflow_path": ".github/workflows/quartus-fit.yml",
                        "source_ref": assembler.ATTESTATION_SOURCE_REF,
                        "source_commit": SOURCE_COMMIT,
                        "run_id": 101 + index,
                        "run_attempt": 1,
                        "job": "fit",
                        "job_nonce": str(index + 1) * 32,
                        "runner_environment": "self-hosted",
                        "candidate_audit": {
                            "filename": assembler.package_core.QUARTUS_AUDIT_FILENAME,
                            "size": len(audit),
                            "sha256": hashlib.sha256(audit).hexdigest(),
                        },
                        "attestation_bundle": {
                            "filename": assembler.ATTESTATION_FILENAME,
                            "size": len(bundle),
                            "sha256": hashlib.sha256(bundle).hexdigest(),
                        },
                    }
                )
            return assembler.BuildPair(
                snapshots=snapshots,
                audits=({"audit_pass": True}, {"audit_pass": True}),
                audit_sha256=("1" * 64, "2" * 64),
                submitted_audit_sha256=("3" * 64, "4" * 64),
                attestations=(attestations[0], attestations[1]),
                rbf={
                    "filename": "ap_core.rbf",
                    "size": len(self.rbf_payload),
                    "sha256": hashlib.sha256(self.rbf_payload).hexdigest(),
                },
                build_id={
                    "filename": "build_id.mif",
                    "size": len(self.build_id_payload),
                    "sha256": hashlib.sha256(self.build_id_payload).hexdigest(),
                },
            )

        def fake_evidence(**arguments: object) -> Path:
            output = Path(arguments["output"])
            output.parent.mkdir()
            output.write_bytes(b"release-evidence\n")
            (output.parent / "output_files").mkdir()
            (output.parent / "output_files/ap_core.rbf").write_bytes(self.rbf_payload)
            return output

        def fake_package(**arguments: object) -> None:
            output = Path(arguments["output"])
            output.write_bytes(b"release-package\n")
            output.with_name(output.name + ".provenance.json").write_bytes(
                b'{"synthetic":"provenance"}\n'
            )

        empty_stage = SimpleNamespace(new_files=(), replaced_files=())
        replacements = {
            "_release_preflight": mock.Mock(
                return_value=(
                    self.definition,
                    {"magic": "SWAN_SONG_RELEASE_POLICY_V2"},
                    {"licensing_review_complete": True, "unresolved_ids": []},
                )
            ),
            "snapshot_and_audit_pair": mock.Mock(side_effect=fake_pair),
            "_accepted_hardware": mock.Mock(
                return_value={
                    "magic": "SWAN_SONG_HARDWARE_QA_V2",
                    "run_id": "accepted-run",
                    "manifest_sha256": "5" * 64,
                    "inventory_sha256": "6" * 64,
                }
            ),
            "_accepted_known_title_compatibility": mock.Mock(
                return_value={
                    "magic": "SWAN_SONG_KNOWN_TITLE_COMPATIBILITY_V1",
                    "catalogue_sha256": "7" * 64,
                    "manifest_sha256": "8" * 64,
                    "run": {
                        "run_id": "accepted-known-title-run",
                        "core_commit": SOURCE_COMMIT,
                        "raw_rbf_sha256": hashlib.sha256(
                            self.rbf_payload
                        ).hexdigest(),
                        "firmware_version": "2.6.0",
                    },
                }
            ),
            "build_release_evidence.build_release_evidence": mock.Mock(
                side_effect=fake_evidence
            ),
            "package_core.validate_build_evidence": mock.Mock(
                return_value={
                    "hardware_qa": {
                        "magic": "SWAN_SONG_HARDWARE_QA_V2",
                        "run_id": "accepted-run",
                        "manifest": {"sha256": "5" * 64},
                        "inventory": {"sha256": "6" * 64},
                    },
                    "known_title_compatibility": {
                        "magic": "SWAN_SONG_KNOWN_TITLE_COMPATIBILITY_V1",
                        "run_id": "accepted-known-title-run",
                        "catalogue": {"sha256": "7" * 64},
                        "manifest": {"sha256": "8" * 64},
                        "case_count": 17,
                        "mode_pass_count": 34,
                        "artifact_count": 100,
                        "artifact_index_sha256": "9" * 64,
                    },
                }
            ),
            "package_core.create_package": mock.Mock(side_effect=fake_package),
            "stage_pocket_sd.plan_staging": mock.Mock(return_value=empty_stage),
            "stage_pocket_sd.apply_staging": mock.Mock(),
            "_source_archive_bytes": mock.Mock(
                return_value=b"deterministic-source-tar\n"
            ),
        }
        for name, replacement in replacements.items():
            target, _, attribute = name.rpartition(".")
            owner = getattr(assembler, target) if target else assembler
            patcher = mock.patch.object(owner, attribute or name, replacement)
            patcher.start()
            self.patches.append(patcher)

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temporary.cleanup()

    def assemble(
        self,
        name: str,
        *,
        apply: bool,
        reviewed_release_body: bool = True,
        reviewed_release_body_sha256: str | None = None,
    ) -> assembler.ReleasePlan:
        reviewed_sha256 = reviewed_release_body_sha256
        if apply and reviewed_release_body and reviewed_sha256 is None:
            review = self.assemble(name + "-review", apply=False)
            reviewed_sha256 = review.release_body_sha256
        return assembler.assemble_release(
            artifacts_a=self.root / "input-a",
            artifacts_b=self.root / "input-b",
            hardware_manifest=self.root / "hardware.json",
            hardware_inventory=self.root / "inventory.json",
            known_title_manifest=self.root / "known-title.json",
            output=self.root / name,
            source_commit=SOURCE_COMMIT,
            source_date_epoch=SOURCE_DATE_EPOCH,
            expected_version=self.definition.version,
            expected_release_date=self.definition.release_date,
            compressed_bitstream_reviewed=True,
            release_body_reviewed_sha256=reviewed_sha256,
            apply=apply,
        )

    def test_default_plan_validates_without_durable_output(self) -> None:
        plan = self.assemble("planned", apply=False)
        self.assertEqual(plan.hardware_run_id, "accepted-run")
        self.assertEqual(plan.known_title_run_id, "accepted-known-title-run")
        self.assertFalse((self.root / "planned").exists())
        assembler.package_core.create_package.assert_not_called()

    def test_apply_is_deterministic_and_publishes_only_public_files(self) -> None:
        self.assemble("release-one", apply=True)
        self.assemble("release-two", apply=True)
        first = self.root / "release-one"
        second = self.root / "release-two"
        expected = {
            self.definition.recommended_archive_name,
            self.definition.recommended_archive_name + ".provenance.json",
            self.definition.recommended_archive_name.removesuffix(".zip") + "-source.tar",
            assembler.SIGNED_PROVENANCE_FILENAME,
            "release-body.md",
            "release-manifest.json",
            "SHA256SUMS",
        }
        self.assertEqual({path.name for path in first.iterdir()}, expected)
        self.assertEqual({path.name for path in second.iterdir()}, expected)
        for name in expected:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        manifest = json.loads((first / "release-manifest.json").read_text())[
            "release_manifest"
        ]
        self.assertEqual(manifest["magic"], assembler.MAGIC)
        self.assertTrue(all(manifest["verification"].values()))
        self.assertFalse(manifest["private_release_evidence"]["published"])
        self.assertEqual(
            manifest["known_title_compatibility"]["mode_pass_count"], 34
        )
        self.assertEqual(
            manifest["artifacts"]["release-body.md"]["sha256"],
            hashlib.sha256((first / "release-body.md").read_bytes()).hexdigest(),
        )
        signed_archive = first / assembler.SIGNED_PROVENANCE_FILENAME
        with tarfile.open(fileobj=io.BytesIO(signed_archive.read_bytes()), mode="r:") as archive:
            members = archive.getmembers()
            self.assertEqual(
                [member.name for member in members],
                [
                    "signed-builds/a/quartus-audit-candidate.attestation.json",
                    "signed-builds/a/quartus-audit-candidate.json",
                    "signed-builds/b/quartus-audit-candidate.attestation.json",
                    "signed-builds/b/quartus-audit-candidate.json",
                ],
            )
            self.assertTrue(all(member.isfile() for member in members))
            self.assertTrue(all(member.mode == 0o644 for member in members))
            self.assertTrue(
                all(member.mtime == SOURCE_DATE_EPOCH for member in members)
            )
        self.assertEqual(
            manifest["artifacts"][assembler.SIGNED_PROVENANCE_FILENAME]["sha256"],
            hashlib.sha256(signed_archive.read_bytes()).hexdigest(),
        )
        body = (first / "release-body.md").read_text(encoding="utf-8")
        self.assertIn("Install or update", body)
        self.assertIn("Rollback safety", body)
        self.assertIn("RegionallyFamous.SwanSong", body)
        self.assertIn("verify both workflow attestations", body)
        checksums = (first / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(checksums, sorted(checksums, key=lambda line: line.split("  ", 1)[1]))
        self.assertEqual(
            {line.split("  ", 1)[1] for line in checksums}, expected - {"SHA256SUMS"}
        )

    def test_apply_requires_exact_reviewed_release_body_hash(self) -> None:
        with self.assertRaisesRegex(
            assembler.AssemblyError, "release-body-reviewed-sha256"
        ):
            self.assemble(
                "unreviewed", apply=True, reviewed_release_body=False
            )
        self.assertFalse((self.root / "unreviewed").exists())
        with self.assertRaisesRegex(
            assembler.AssemblyError, "release-body-reviewed-sha256"
        ):
            self.assemble(
                "wrong-review",
                apply=True,
                reviewed_release_body_sha256="0" * 64,
            )
        self.assertFalse((self.root / "wrong-review").exists())

    def test_plan_prints_exact_release_body_and_review_hash(self) -> None:
        plan = self.assemble("body-plan", apply=False)
        summary = assembler._render_summary(plan, applied=False)
        self.assertIn(plan.release_body_sha256, summary)
        self.assertIn(plan.release_body, summary)
        self.assertIn("--release-body-reviewed-sha256", summary)

    def test_failure_removes_partial_output_atomically(self) -> None:
        assembler.package_core.create_package.side_effect = ValueError("synthetic failure")
        with self.assertRaisesRegex(assembler.AssemblyError, "synthetic failure"):
            self.assemble("failed", apply=True)
        self.assertFalse((self.root / "failed").exists())
        self.assertFalse(any("failed.assemble-" in path.name for path in self.root.iterdir()))


class StableReleaseBoundaryTest(unittest.TestCase):
    def test_release_documentation_requires_exact_completed_decisions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-release-docs-") as raw:
            root = Path(raw)
            for relative in assembler.RELEASE_DOCUMENT_STALE_MARKERS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Release-ready documentation.\n", encoding="utf-8")
            decisions = "\n".join(
                f"- [x] **{label}.** Accepted."
                for label in assembler.RELEASE_DECISION_LABELS
            )
            decisions = decisions.replace(
                "**Build the final commit.**",
                "**Build the final\n  commit.**",
            )
            (root / "RELEASE_DECISIONS.md").write_text(
                decisions + "\n", encoding="utf-8"
            )

            assembler._validate_release_documentation(root)

            (root / "RELEASE_DECISIONS.md").write_text(
                decisions.replace("- [x]", "- [ ]", 1) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(assembler.AssemblyError, "incomplete"):
                assembler._validate_release_documentation(root)

    def test_release_documentation_rejects_stale_public_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-release-docs-stale-") as raw:
            root = Path(raw)
            for relative in assembler.RELEASE_DOCUMENT_STALE_MARKERS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Release-ready documentation.\n", encoding="utf-8")
            (root / "RELEASE_DECISIONS.md").write_text(
                "\n".join(
                    f"- [x] **{label}.** Accepted."
                    for label in assembler.RELEASE_DECISION_LABELS
                )
                + "\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text(
                "Swan Song is still in development. There is not yet a verified public\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(assembler.AssemblyError, "README.md"):
                assembler._validate_release_documentation(root)

    def test_release_documentation_rejects_symlinked_public_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-release-docs-link-") as raw:
            root = Path(raw)
            for relative in assembler.RELEASE_DOCUMENT_STALE_MARKERS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Release-ready documentation.\n", encoding="utf-8")
            (root / "RELEASE_DECISIONS.md").write_text(
                "\n".join(
                    f"- [x] **{label}.** Accepted."
                    for label in assembler.RELEASE_DECISION_LABELS
                )
                + "\n",
                encoding="utf-8",
            )
            home = root / "docs/wiki/Home.md"
            home.unlink()
            home.symlink_to(root / "README.md")

            with self.assertRaisesRegex(assembler.AssemblyError, "nonsymlink"):
                assembler._validate_release_documentation(root)

    def test_checked_in_pending_known_title_catalogue_is_a_hard_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-known-title-pending-") as raw:
            manifest = Path(raw) / "manifest.json"
            document = json.loads(
                assembler.KNOWN_TITLE_CATALOGUE.read_text(encoding="utf-8")
            )
            document["known_title_compatibility"]["run"].update(
                {
                    "run_id": "pending-release-gate",
                    "created_at": "2026-07-14T12:00:00Z",
                    "operator": "Release gate test",
                    "core_commit": "a" * 40,
                    "raw_rbf_sha256": "0" * 64,
                    "firmware_version": "2.6.0",
                    "pocket_hardware_revision": "test",
                    "dock_hardware_revision": "test",
                }
            )
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(assembler.AssemblyError, "pending"):
                assembler._accepted_known_title_compatibility(
                    manifest=manifest,
                    expected_rbf={"sha256": "0" * 64},
                    source_commit="a" * 40,
                )

    def test_current_false_release_policy_remains_a_hard_gate(self) -> None:
        definition = validate_distribution(assembler.DIST)
        with mock.patch.object(assembler, "_validate_checkout"), mock.patch.object(
            assembler, "_validate_release_documentation"
        ):
            with self.assertRaisesRegex(assembler.AssemblyError, "not accepted"):
                assembler._release_preflight(
                    source_root=assembler.ROOT,
                    dist=assembler.DIST,
                    release_policy=assembler.RELEASE_POLICY,
                    source_commit="a" * 40,
                    source_date_epoch=SOURCE_DATE_EPOCH,
                    expected_version=definition.version,
                    expected_release_date=definition.release_date,
                    compressed_bitstream_reviewed=True,
                )

    def test_corresponding_source_archive_is_byte_deterministic(self) -> None:
        commit = (
            assembler._git(assembler.ROOT, "rev-parse", "HEAD")
            .decode("ascii")
            .strip()
        )
        first = assembler._source_archive_bytes(
            source_root=assembler.ROOT,
            source_commit=commit,
            prefix="SwanSong-test-source",
        )
        second = assembler._source_archive_bytes(
            source_root=assembler.ROOT,
            source_commit=commit,
            prefix="SwanSong-test-source",
        )
        self.assertEqual(first, second)
        self.assertGreater(len(first), 1024)


if __name__ == "__main__":
    unittest.main()
