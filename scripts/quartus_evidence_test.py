#!/usr/bin/env python3

from pathlib import Path
import json
import tempfile
import unittest

import quartus_evidence as evidence
import quartus_container_provenance as container_provenance
import quartus_fit_audit as fit_audit
import quartus_fit_audit_test as fit_audit_test


IMAGE_ID = "sha256:" + "a" * 64


class QuartusEvidenceTest(unittest.TestCase):
    def roots(self, temporary: str) -> tuple[Path, Path]:
        root = Path(temporary)
        artifacts = root / "artifacts"
        output = root / "evidence"
        artifacts.mkdir()
        output.mkdir()
        return artifacts, output

    @staticmethod
    def files_under(root: Path) -> set[Path]:
        return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}

    @staticmethod
    def add_container_provenance(artifacts: Path) -> None:
        packages = artifacts / "container-packages.tsv"
        packages.write_text("bash\t5.0-6ubuntu1.2\tamd64\n")
        container_provenance.create_provenance(
            image_id=IMAGE_ID,
            repo_digests_text="",
            packages=packages,
            output=artifacts / "container-provenance.json",
        )

    @staticmethod
    def add_candidate_binding(artifacts: Path) -> None:
        fit_audit_test.Fixture(artifacts)
        (artifacts / "quartus-audit-candidate.json").write_text(
            json.dumps(fit_audit.audit(artifacts))
        )

    def test_copies_exact_allowlist_and_excludes_unknown_extras(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            self.add_candidate_binding(artifacts)
            expected = {item.relative for item in evidence.EVIDENCE_FILES}

            (artifacts / "unknown-secret.txt").write_text("do not upload")
            (artifacts / "output_files/unknown.qdb").write_text("do not upload")
            (artifacts / "unknown-directory").mkdir()
            (artifacts / "unknown-link").symlink_to("unknown-secret.txt")

            collected = evidence.collect_evidence(artifacts, output)

            self.assertEqual(set(collected), expected)
            self.assertEqual(self.files_under(output), expected)
            self.assertNotIn(Path("unknown-secret.txt"), self.files_under(output))
            self.assertNotIn(Path("output_files/unknown.qdb"), self.files_under(output))

    def test_static_allowlist_stays_within_total_size_bound(self) -> None:
        self.assertLessEqual(
            sum(item.max_bytes for item in evidence.EVIDENCE_FILES),
            evidence.MAX_EVIDENCE_BYTES,
        )
        allowlist = {item.relative for item in evidence.EVIDENCE_FILES}
        self.assertLessEqual(
            {Path(relative) for relative in fit_audit.REQUIRED_ARTIFACTS},
            allowlist,
        )

    def test_partial_failed_fit_collects_only_files_that_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            (artifacts / "quartus.log").write_text("compile failed")
            reports = artifacts / "output_files"
            reports.mkdir()
            connectivity = (
                b"Analysis & Synthesis Connectivity Checks\n"
                b"| Port | Type | Severity | Details |\n"
                b"| data | Output | Warning | Declared but not connected |\n"
            )
            (reports / "ap_core.map.rpt").write_bytes(connectivity)
            (reports / "ap_core.fit.rpt").write_text("partial fitter report")
            (reports / "ap_core.sta.rpt").write_text("partial TimeQuest report")
            (reports / "unrelated.rpt").write_text("must not escape")

            collected = evidence.collect_evidence(artifacts, output)

            expected = {
                Path("quartus.log"),
                Path("output_files/ap_core.map.rpt"),
                Path("output_files/ap_core.fit.rpt"),
                Path("output_files/ap_core.sta.rpt"),
            }
            self.assertEqual(set(collected), expected)
            self.assertEqual(self.files_under(output), expected)
            self.assertEqual(
                (output / "output_files/ap_core.map.rpt").read_bytes(),
                connectivity,
            )

    def test_connectivity_report_keeps_the_report_size_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            item = next(
                candidate
                for candidate in evidence.EVIDENCE_FILES
                if candidate.relative == Path("output_files/ap_core.map.rpt")
            )
            source = artifacts / item.relative
            source.parent.mkdir(parents=True)
            with source.open("wb") as oversized:
                oversized.truncate(item.max_bytes + 1)

            with self.assertRaisesRegex(
                evidence.EvidenceError, "evidence input exceeds"
            ):
                evidence.collect_evidence(artifacts, output)

            self.assertEqual(self.files_under(output), set())

    def test_allowlisted_symlink_fails_before_copying_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            (artifacts / "real.log").write_text("not safe through a link")
            (artifacts / "quartus.log").symlink_to("real.log")
            (artifacts / "build-metadata.txt").write_text("otherwise valid")

            with self.assertRaises(evidence.EvidenceError):
                evidence.collect_evidence(artifacts, output)

            self.assertEqual(self.files_under(output), set())

    def test_allowlisted_directory_fails_before_copying_anything(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            (artifacts / "quartus.log").mkdir()

            with self.assertRaises(evidence.EvidenceError):
                evidence.collect_evidence(artifacts, output)

            self.assertEqual(self.files_under(output), set())

    def test_oversized_allowlisted_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            item = next(
                candidate
                for candidate in evidence.EVIDENCE_FILES
                if candidate.relative == Path("build_id.mif")
            )
            with (artifacts / item.relative).open("wb") as oversized:
                oversized.truncate(item.max_bytes + 1)

            with self.assertRaises(evidence.EvidenceError):
                evidence.collect_evidence(artifacts, output)

            self.assertEqual(self.files_under(output), set())

    def test_nonempty_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            (output / "stale.txt").write_text("stale")

            with self.assertRaises(evidence.EvidenceError):
                evidence.collect_evidence(artifacts, output)

    def test_container_provenance_requires_valid_bound_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            (artifacts / "container-packages.tsv").write_text(
                "bash\t5.0-6ubuntu1.2\tamd64\n"
            )
            with self.assertRaises(evidence.EvidenceError):
                evidence.collect_evidence(artifacts, output)
            self.assertEqual(self.files_under(output), set())

    def test_successful_candidate_requires_and_binds_container_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            (artifacts / "quartus-audit-candidate.json").write_text("{}")
            with self.assertRaisesRegex(
                evidence.EvidenceError, "requires container provenance pair"
            ):
                evidence.collect_evidence(artifacts, output)
            self.assertEqual(self.files_under(output), set())

        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            self.add_candidate_binding(artifacts)
            (artifacts / "container-provenance.json").unlink()
            container_provenance.create_provenance(
                image_id="sha256:" + "b" * 64,
                repo_digests_text="",
                packages=artifacts / "container-packages.tsv",
                output=artifacts / "container-provenance.json",
            )
            with self.assertRaisesRegex(
                evidence.EvidenceError, "does not bind collected container-provenance"
            ):
                evidence.collect_evidence(artifacts, output)
            self.assertEqual(self.files_under(output), set())

        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            self.add_container_provenance(artifacts)
            (artifacts / "container-packages.tsv").write_text(
                "bash\tmutated\tamd64\n"
            )
            with self.assertRaises(evidence.EvidenceError):
                evidence.collect_evidence(artifacts, output)
            self.assertEqual(self.files_under(output), set())

    def test_audited_candidate_requires_and_binds_collected_map_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            self.add_candidate_binding(artifacts)
            (artifacts / "output_files/ap_core.map.rpt").unlink()
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "requires collected output_files/ap_core.map.rpt",
            ):
                evidence.collect_evidence(artifacts, output)
            self.assertEqual(self.files_under(output), set())

    def test_audited_candidate_rejects_incomplete_or_unknown_artifact_set(self) -> None:
        for mutation in ("missing", "unknown"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                artifacts, output = self.roots(temporary)
                self.add_candidate_binding(artifacts)
                candidate = artifacts / "quartus-audit-candidate.json"
                document = json.loads(candidate.read_text())
                identities = document["quartus_audit"]["artifacts"]
                if mutation == "missing":
                    identities.pop("quartus.log")
                else:
                    identities["unknown-secret.txt"] = {
                        "sha256": "0" * 64,
                        "size": 1,
                    }
                candidate.write_text(json.dumps(document))

                with self.assertRaisesRegex(
                    evidence.EvidenceError,
                    "unknown or missing audited artifact members",
                ):
                    evidence.collect_evidence(artifacts, output)
                self.assertEqual(self.files_under(output), set())

    def test_audited_candidate_rejects_post_audit_artifact_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            self.add_candidate_binding(artifacts)
            (artifacts / "quartus.log").write_text("mutated after audit\n")

            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "does not bind collected quartus.log",
            ):
                evidence.collect_evidence(artifacts, output)
            self.assertEqual(self.files_under(output), set())

        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            self.add_candidate_binding(artifacts)
            (artifacts / "output_files/ap_core.map.rpt").write_text(
                "mutated after audit\n"
            )
            with self.assertRaisesRegex(
                evidence.EvidenceError,
                "does not bind collected output_files/ap_core.map.rpt",
            ):
                evidence.collect_evidence(artifacts, output)
            self.assertEqual(self.files_under(output), set())

    def test_audited_candidate_rejects_post_audit_claim_mutation(self) -> None:
        mutations = {
            "magic": lambda audit: audit.__setitem__("magic", "FORGED_AUDIT"),
            "audit_pass": lambda audit: audit.__setitem__("audit_pass", False),
            "release_eligible": lambda audit: audit.__setitem__(
                "release_eligible", True
            ),
            "candidate_gates": lambda audit: audit["candidate_gates"].__setitem__(
                "pocket_hardware", True
            ),
            "timing": lambda audit: audit["timing"]["clocks"]["required"].append(
                "forged_clock"
            ),
            "provenance": lambda audit: audit["provenance"].__setitem__(
                "source_commit", "b" * 40
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                artifacts, output = self.roots(temporary)
                self.add_candidate_binding(artifacts)
                candidate = artifacts / "quartus-audit-candidate.json"
                document = json.loads(candidate.read_text())
                mutate(document["quartus_audit"])
                candidate.write_text(json.dumps(document))

                with self.assertRaisesRegex(
                    evidence.EvidenceError,
                    "does not match the audit recomputed from collected evidence",
                ):
                    evidence.collect_evidence(artifacts, output)
                self.assertEqual(self.files_under(output), set())

    def test_review_failed_candidate_is_still_reproducible_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            self.add_candidate_binding(artifacts)
            map_report = artifacts / "output_files/ap_core.map.rpt"
            map_report.write_text(
                map_report.read_text()
                + "Warning (12241): hierarchy has connectivity warnings\n"
            )
            payload = fit_audit.audit(artifacts)
            self.assertFalse(payload["quartus_audit"]["audit_pass"])
            (artifacts / "quartus-audit-candidate.json").write_text(
                json.dumps(payload)
            )

            collected = evidence.collect_evidence(artifacts, output)

            self.assertEqual(
                set(collected), {item.relative for item in evidence.EVIDENCE_FILES}
            )
            self.assertEqual(
                json.loads((output / "quartus-audit-candidate.json").read_text()),
                payload,
            )


if __name__ == "__main__":
    unittest.main()
