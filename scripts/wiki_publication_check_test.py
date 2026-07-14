#!/usr/bin/env python3
"""Offline mutation tests for the read-only wiki publication checker."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import wiki_publication_check as checker


class WikiPublicationCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-wiki-check-")
        self.source = Path(self.temporary.name) / "source"
        self.wiki = self.source / checker.WIKI_RELATIVE
        self.wiki.mkdir(parents=True)
        for name in checker.WIKI_MANIFEST:
            heading = Path(name).stem.replace("-", " ").replace("_", "").strip()
            (self.wiki / name).write_text(f"# {heading}\n", encoding="utf-8")

        (self.wiki / "Home.md").write_text(
            "# Home\n\n"
            "## Same heading\n\n"
            "## Same heading\n\n"
            "[Controls](https://github.com/RegionallyFamous/swan-song/wiki/Controls-and-Settings#controls)\n",
            encoding="utf-8",
        )
        (self.wiki / "Controls-and-Settings.md").write_text(
            "# Controls and Settings\n\n## Controls\n", encoding="utf-8"
        )
        (self.wiki / "Architecture.md").write_text(
            "# Architecture\n\n"
            "[Build details](Build-and-Test#build-and-test)\n\n"
            "[Second duplicate](Home#same-heading-1)\n",
            encoding="utf-8",
        )
        (self.wiki / "Developer-Hub.md").write_text(
            "# Developer Hub\n\n"
            "[Repository guide](https://github.com/RegionallyFamous/swan-song/blob/main/GUIDE.md#target-section)\n",
            encoding="utf-8",
        )
        (self.source / "GUIDE.md").write_text(
            "# Guide\n\n## Target section\n", encoding="utf-8"
        )
        required = list(checker.README_REQUIRED_WIKI_PAGES)
        readme_links = []
        for page in required:
            if page == "Developer-Hub":
                readme_links.append(
                    "[Developer\nHub](https://github.com/RegionallyFamous/swan-song/wiki/Developer-Hub)"
                )
            else:
                readme_links.append(
                    f"[{page}](https://github.com/RegionallyFamous/swan-song/wiki/{page})"
                )
        (self.source / "README.md").write_text(
            "# Swan Song\n\n"
            + "\n".join(readme_links)
            + "\n\n[Local guide](GUIDE.md#target-section)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def codes(self, report: checker.PublicationReport) -> set[str]:
        return {item.code for item in report.findings}

    def clean_clone(self) -> Path:
        clone = Path(self.temporary.name) / "wiki-clone"
        clone.mkdir()
        for name in checker.WIKI_MANIFEST:
            shutil.copy2(self.wiki / name, clone / name)
        commands = (
            ("git", "init", "-q"),
            ("git", "config", "user.name", "Offline Wiki Test"),
            ("git", "config", "user.email", "offline@example.invalid"),
            ("git", "add", "--", *checker.WIKI_MANIFEST),
            ("git", "commit", "-q", "-m", "Synthetic clean wiki fixture"),
        )
        for command in commands:
            subprocess.run(command, cwd=clone, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return clone

    def test_exact_manifest_links_and_fragments_pass_without_subprocess(self) -> None:
        with mock.patch.object(
            checker.subprocess, "run", side_effect=AssertionError("unexpected subprocess")
        ):
            report = checker.check_publication(self.source)
        self.assertTrue(report.ok, report.findings)
        self.assertEqual(
            report.readme_wiki_pages,
            tuple(sorted(checker.README_REQUIRED_WIKI_PAGES)),
        )
        self.assertEqual(report.repository_targets, ("GUIDE.md",))
        document = report.document()
        self.assertTrue(document["read_only"])
        self.assertFalse(document["network_access"])
        self.assertFalse(document["publication_performed"])

    def test_exact_manifest_rejects_missing_extra_and_symlink_pages(self) -> None:
        (self.wiki / "Build-and-Test.md").unlink()
        (self.wiki / "Unexpected.md").write_text("# Unexpected\n", encoding="utf-8")
        (self.wiki / "Playing-Games.md").unlink()
        (self.wiki / "Playing-Games.md").symlink_to("Home.md")
        report = checker.check_publication(self.source)
        self.assertIn("wiki-manifest-missing", self.codes(report))
        self.assertIn("wiki-manifest-extra", self.codes(report))
        self.assertIn("unsafe-wiki-page", self.codes(report))
        self.assertFalse(report.ok)

    def test_relative_wiki_targets_and_heading_fragments_fail_closed(self) -> None:
        (self.wiki / "Architecture.md").write_text(
            "# Architecture\n\n"
            "[Missing page](Does-Not-Exist)\n"
            "[Missing heading](Home#not-a-heading)\n"
            "[Escape](../../../outside.md)\n",
            encoding="utf-8",
        )
        report = checker.check_publication(self.source)
        self.assertTrue(
            {
                "missing-local-target",
                "missing-heading-fragment",
                "relative-target-escape",
            }.issubset(self.codes(report))
        )

    def test_fenced_links_are_ignored_and_reference_links_are_checked(self) -> None:
        (self.wiki / "Architecture.md").write_text(
            "# Architecture\n\n"
            "```md\n[Ignored](Missing-In-Fence)\n```\n\n"
            "[Home page][home]\n\n"
            "[home]: Home#home\n",
            encoding="utf-8",
        )
        report = checker.check_publication(self.source)
        self.assertTrue(report.ok, report.findings)
        self.assertNotIn("Missing-In-Fence", "\n".join(item.message for item in report.findings))

    def test_blob_main_target_must_exist_in_supplied_source_tree(self) -> None:
        (self.wiki / "Developer-Hub.md").write_text(
            "# Developer Hub\n\n"
            "[Missing](https://github.com/RegionallyFamous/swan-song/blob/main/MISSING.md)\n",
            encoding="utf-8",
        )
        report = checker.check_publication(self.source)
        self.assertIn("missing-local-target", self.codes(report))
        self.assertEqual(report.repository_targets, ("MISSING.md",))
        finding = next(
            item for item in report.findings if item.code == "missing-local-target"
        )
        self.assertIn("supplied source tree", finding.message)

    def test_readme_required_and_unknown_wiki_targets_are_reported(self) -> None:
        readme = (self.source / "README.md").read_text(encoding="utf-8")
        readme = readme.replace(
            "https://github.com/RegionallyFamous/swan-song/wiki/Playing-Games",
            "https://github.com/RegionallyFamous/swan-song/wiki/Unknown-Page",
        )
        (self.source / "README.md").write_text(readme, encoding="utf-8")
        report = checker.check_publication(self.source)
        self.assertIn("readme-wiki-target-missing", self.codes(report))
        self.assertIn("missing-wiki-target", self.codes(report))

    def test_clean_clone_comparison_emits_deterministic_dry_run_diff(self) -> None:
        clone = self.clean_clone()
        (self.wiki / "Home.md").write_text(
            (self.wiki / "Home.md").read_text(encoding="utf-8") + "\nNew reviewed line.\n",
            encoding="utf-8",
        )
        before = (clone / "Home.md").read_bytes()
        report = checker.check_publication(self.source, clone)
        self.assertTrue(report.ok, report.findings)
        self.assertTrue(report.clone_clean)
        self.assertEqual(report.clone_differences, ("Home.md",))
        self.assertIn("--- wiki-clone/Home.md", report.sync_diff)
        self.assertIn("+++ source/docs/wiki/Home.md", report.sync_diff)
        self.assertIn("+New reviewed line.", report.sync_diff)
        self.assertEqual((clone / "Home.md").read_bytes(), before)
        rendered = checker.render_report(report)
        self.assertIn("DRY-RUN CONTENT DIFF", rendered)
        self.assertIn("never copies, deletes, commits, or pushes", rendered)

    def test_dirty_clone_and_unexpected_page_are_refused_without_deletion(self) -> None:
        clone = self.clean_clone()
        extra = clone / "Unreviewed.md"
        extra.write_text("# Do not delete me\n", encoding="utf-8")
        report = checker.check_publication(self.source, clone)
        self.assertFalse(report.ok)
        self.assertFalse(report.clone_clean)
        self.assertIn("wiki-clone-dirty", self.codes(report))
        self.assertIn("wiki-manifest-extra", self.codes(report))
        extra_finding = next(
            item for item in report.findings if item.code == "wiki-manifest-extra"
        )
        self.assertIn("will not be deleted automatically", extra_finding.message)
        self.assertTrue(extra.exists())

    def test_clean_clone_with_symlink_page_is_still_unsafe(self) -> None:
        clone = self.clean_clone()
        page = clone / "Controls-and-Settings.md"
        page.unlink()
        page.symlink_to("Home.md")
        subprocess.run(
            ("git", "add", "--", "Controls-and-Settings.md"),
            cwd=clone,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ("git", "commit", "-q", "-m", "Synthetic unsafe symlink"),
            cwd=clone,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        report = checker.check_publication(self.source, clone)
        self.assertTrue(report.clone_clean)
        self.assertFalse(report.ok)
        self.assertIn("unsafe-wiki-clone-page", self.codes(report))
        self.assertTrue(page.is_symlink())

    def test_unversioned_comparison_directory_is_not_called_a_clean_clone(self) -> None:
        comparison = Path(self.temporary.name) / "plain-directory"
        shutil.copytree(self.wiki, comparison)
        report = checker.check_publication(self.source, comparison)
        self.assertFalse(report.ok)
        self.assertFalse(report.clone_clean)
        self.assertIn("wiki-clone-not-git", self.codes(report))

    def test_json_cli_is_deterministic_and_offline(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output), mock.patch.object(
            checker.subprocess, "run", side_effect=AssertionError("unexpected subprocess")
        ):
            result = checker.main(["--source-root", str(self.source), "--json"])
        self.assertEqual(result, 0)
        document = json.loads(output.getvalue())
        self.assertEqual(document["status"], "ready")
        self.assertTrue(document["read_only"])
        self.assertFalse(document["network_access"])
        self.assertFalse(document["publication_performed"])


if __name__ == "__main__":
    unittest.main()
