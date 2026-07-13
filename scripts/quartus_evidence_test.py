#!/usr/bin/env python3

from pathlib import Path
import tempfile
import unittest

import quartus_evidence as evidence


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

    def test_copies_exact_allowlist_and_excludes_unknown_extras(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifacts, output = self.roots(temporary)
            expected = set()
            for index, item in enumerate(evidence.EVIDENCE_FILES):
                source = artifacts / item.relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f"evidence-{index}".encode())
                expected.add(item.relative)

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


if __name__ == "__main__":
    unittest.main()
