#!/usr/bin/env python3

from pathlib import Path
import hashlib
import json
import tempfile
import unittest

import quartus_evidence as evidence
import quartus_container_provenance as container_provenance


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
        provenance = container_provenance.validate_provenance(
            artifacts / "container-provenance.json",
            artifacts / "container-packages.tsv",
        )
        identities = {}
        for name in ("container-provenance.json", "container-packages.tsv"):
            data = (artifacts / name).read_bytes()
            identities[name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        (artifacts / "quartus-audit-candidate.json").write_text(
            json.dumps(
                {
                    "quartus_audit": {
                        "artifacts": identities,
                        "container_provenance": provenance,
                    }
                }
            )
        )

    def test_copies_exact_allowlist_and_excludes_unknown_extras(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            expected = set()
            for index, item in enumerate(evidence.EVIDENCE_FILES):
                if item.relative in {
                    Path("quartus-audit-candidate.json"),
                    Path("container-provenance.json"),
                    Path("container-packages.tsv"),
                }:
                    continue
                source = artifacts / item.relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f"evidence-{index}".encode())
                expected.add(item.relative)
            self.add_container_provenance(artifacts)
            self.add_candidate_binding(artifacts)
            expected.update(
                {
                    Path("quartus-audit-candidate.json"),
                    Path("container-provenance.json"),
                    Path("container-packages.tsv"),
                }
            )

            (artifacts / "unknown-secret.txt").write_text("do not upload")
            (artifacts / "output_files/unknown.qdb").write_text("do not upload")
            (artifacts / "unknown-directory").mkdir()
            (artifacts / "unknown-link").symlink_to("unknown-secret.txt")

            collected = evidence.collect_evidence(artifacts, output)

            self.assertEqual(set(collected), expected)
            self.assertEqual(self.files_under(output), expected)
            self.assertNotIn(Path("unknown-secret.txt"), self.files_under(output))
            self.assertNotIn(Path("output_files/unknown.qdb"), self.files_under(output))

    def test_partial_failed_fit_collects_only_files_that_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            (artifacts / "quartus.log").write_text("compile failed")
            reports = artifacts / "output_files"
            reports.mkdir()
            (reports / "ap_core.fit.rpt").write_text("partial fitter report")
            (reports / "unrelated.rpt").write_text("must not escape")

            collected = evidence.collect_evidence(artifacts, output)

            expected = {
                Path("quartus.log"),
                Path("output_files/ap_core.fit.rpt"),
            }
            self.assertEqual(set(collected), expected)
            self.assertEqual(self.files_under(output), expected)

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
            self.add_container_provenance(artifacts)
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


if __name__ == "__main__":
    unittest.main()
