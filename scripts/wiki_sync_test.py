#!/usr/bin/env python3
"""Offline mutation tests for the guarded Swan Song Wiki synchronizer."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import wiki_publication_check as checker
import wiki_sync as sync


class WikiSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-wiki-sync-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.wiki = self.source / checker.WIKI_RELATIVE
        self.wiki.mkdir(parents=True)
        for name in checker.WIKI_MANIFEST:
            heading = Path(name).stem.replace("-", " ").replace("_", "").strip()
            (self.wiki / name).write_text(f"# {heading}\n", encoding="utf-8")
        (self.wiki / "Home.md").write_text(
            "# Home\n\n[Controls](Controls-and-Settings#controls)\n",
            encoding="utf-8",
        )
        (self.wiki / "Controls-and-Settings.md").write_text(
            "# Controls and Settings\n\n## Controls\n", encoding="utf-8"
        )
        (self.wiki / "Developer-Hub.md").write_text(
            "# Developer Hub\n\n[Guide](https://github.com/RegionallyFamous/swan-song/blob/main/GUIDE.md#details)\n",
            encoding="utf-8",
        )
        (self.source / "GUIDE.md").write_text(
            "# Guide\n\n## Details\n", encoding="utf-8"
        )
        links = [
            f"[{page}](https://github.com/RegionallyFamous/swan-song/wiki/{page})"
            for page in checker.README_REQUIRED_WIKI_PAGES
        ]
        (self.source / "README.md").write_text(
            "# Swan Song\n\n" + "\n".join(links) + "\n",
            encoding="utf-8",
        )
        self.remote = self.root / "wiki.git"
        self.clone = self._make_clone()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(
        self, cwd: Path, *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            arguments,
            cwd=cwd,
            check=check,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _make_clone(self) -> Path:
        self._run(self.root, "git", "init", "--bare", "-q", str(self.remote))
        seed = self.root / "seed"
        seed.mkdir()
        for name in checker.WIKI_MANIFEST:
            shutil.copy2(self.wiki / name, seed / name)
        (seed / "Playing-Games.md").unlink()
        (seed / "Home.md").write_text("# Old home\n", encoding="utf-8")
        (seed / "Old-Page.md").write_text("# Retired page\n", encoding="utf-8")
        self._run(seed, "git", "init", "-q")
        self._run(seed, "git", "branch", "-M", "master")
        self._run(seed, "git", "config", "user.name", "Offline Wiki Test")
        self._run(seed, "git", "config", "user.email", "offline@example.invalid")
        self._run(seed, "git", "add", "-A")
        self._run(seed, "git", "commit", "-q", "-m", "Initial synthetic Wiki")
        self._run(seed, "git", "remote", "add", "origin", str(self.remote))
        self._run(seed, "git", "push", "-q", "-u", "origin", "master")

        clone = self.root / "wiki-clone"
        self._run(self.root, "git", "clone", "-q", str(self.remote), str(clone))
        self._run(clone, "git", "config", "user.name", "Offline Wiki Test")
        self._run(clone, "git", "config", "user.email", "offline@example.invalid")
        canonical = "https://github.com/RegionallyFamous/swan-song.wiki.git"
        self._run(clone, "git", "remote", "set-url", "origin", canonical)
        return clone

    def _push_fixture(self) -> None:
        self._run(self.clone, "git", "push", "-q", str(self.remote), "HEAD:master")
        self._run(
            self.clone,
            "git",
            "update-ref",
            "refs/remotes/origin/master",
            "HEAD",
        )

    def _head(self, worktree: Path | None = None) -> bytes:
        return self._run(worktree or self.clone, "git", "rev-parse", "HEAD").stdout.strip()

    def _status(self) -> bytes:
        return self._run(
            self.clone, "git", "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout

    def test_default_plan_is_exact_and_never_commits_or_pushes(self) -> None:
        before_head = self._head()
        before_files = {
            path.name: path.read_bytes()
            for path in self.clone.iterdir()
            if path.name != ".git"
        }
        original = sync._run_git

        def guarded(clone: Path, arguments: tuple[str, ...], **keywords: object):
            self.assertNotIn(arguments[0], {"commit", "push"})
            return original(clone, arguments, **keywords)

        with mock.patch.object(sync, "_run_git", side_effect=guarded):
            plan = sync.build_plan(self.source, self.clone)
        self.assertEqual(
            [(item.operation, item.path) for item in plan.entries],
            [
                ("add", "Playing-Games.md"),
                ("change", "Home.md"),
                ("delete", "Old-Page.md"),
            ],
        )
        rendered = sync.render_plan(plan)
        self.assertIn("ADD (1)\n  Playing-Games.md", rendered)
        self.assertIn("CHANGE (1)\n  Home.md", rendered)
        self.assertIn("DELETE (1)\n  Old-Page.md", rendered)
        self.assertEqual(self._head(), before_head)
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in self.clone.iterdir()
                if path.name != ".git"
            },
            before_files,
        )
        self.assertEqual(self._status(), b"")

    def test_apply_requires_exact_confirmation_without_mutation(self) -> None:
        before = self._head()
        error = io.StringIO()
        with redirect_stderr(error):
            result = sync.main(
                [
                    "--source-root",
                    str(self.source),
                    "--wiki-clone",
                    str(self.clone),
                    "--apply",
                ]
            )
        self.assertEqual(result, 2)
        self.assertIn("must exactly equal", error.getvalue())
        self.assertEqual(self._head(), before)
        self.assertEqual(self._status(), b"")

    def test_apply_copies_deletes_commits_and_pushes_to_offline_remote(self) -> None:
        plan = sync.build_plan(self.source, self.clone)
        git_directory = self.clone / ".git"
        real_run_git = sync._run_git

        def offline_push(clone: Path, arguments: tuple[str, ...], **keywords: object):
            if arguments[0] == "push":
                return subprocess.run(
                    ["git", "-C", str(clone), "push", "--porcelain", str(self.remote), "HEAD:master"],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            return real_run_git(clone, arguments, **keywords)

        with mock.patch.object(sync, "_run_git", side_effect=offline_push):
            result = sync.apply_plan(plan, sync.CONFIRMATION, "Publish reviewed Wiki")
        self.assertTrue(result.committed)
        self.assertTrue(result.pushed)
        self.assertIsNotNone(result.commit)
        self.assertTrue(git_directory.is_dir())
        self.assertEqual(self._status(), b"")
        for name in checker.WIKI_MANIFEST:
            self.assertEqual(
                (self.clone / name).read_bytes(),
                (self.wiki / name).read_bytes(),
            )
        self.assertFalse((self.clone / "Old-Page.md").exists())
        remote_home = self._run(
            self.root,
            "git",
            f"--git-dir={self.remote}",
            "show",
            "master:Home.md",
        ).stdout
        self.assertEqual(remote_home, (self.wiki / "Home.md").read_bytes())
        message = self._run(self.clone, "git", "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(message, b"Publish reviewed Wiki")

    def test_dirty_clone_is_rejected(self) -> None:
        (self.clone / "Home.md").write_text("# Dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(sync.WikiSyncError, "must be clean"):
            sync.build_plan(self.source, self.clone)

    def test_wrong_remote_is_rejected(self) -> None:
        self._run(
            self.clone,
            "git",
            "remote",
            "set-url",
            "origin",
            "https://github.com/example/not-the-wiki.git",
        )
        with self.assertRaisesRegex(sync.WikiSyncError, "origin must fetch and push"):
            sync.build_plan(self.source, self.clone)

    def test_clean_tracked_symlink_page_is_rejected(self) -> None:
        page = self.clone / "Home.md"
        page.unlink()
        page.symlink_to("Architecture.md")
        self._run(self.clone, "git", "add", "Home.md")
        self._run(self.clone, "git", "commit", "-q", "-m", "Unsafe link fixture")
        self._push_fixture()
        with self.assertRaisesRegex(sync.WikiSyncError, "regular nonsymlink"):
            sync.build_plan(self.source, self.clone)

    def test_clean_unexpected_non_markdown_path_is_rejected(self) -> None:
        (self.clone / "notes.txt").write_text("unexpected\n", encoding="utf-8")
        self._run(self.clone, "git", "add", "notes.txt")
        self._run(self.clone, "git", "commit", "-q", "-m", "Unexpected fixture")
        self._push_fixture()
        with self.assertRaisesRegex(sync.WikiSyncError, "unexpected wiki-clone entry"):
            sync.build_plan(self.source, self.clone)

    def test_invalid_source_utf8_is_rejected_by_publication_check(self) -> None:
        (self.wiki / "Home.md").write_bytes(b"# Home\n\xff")
        with self.assertRaisesRegex(sync.WikiSyncError, "wiki_publication_check rejected"):
            sync.build_plan(self.source, self.clone)

    def test_source_change_after_plan_requires_a_new_dry_run(self) -> None:
        plan = sync.build_plan(self.source, self.clone)
        (self.wiki / "Home.md").write_text("# New source after plan\n", encoding="utf-8")
        with self.assertRaisesRegex(sync.WikiSyncError, "changed after planning"):
            sync.apply_plan(plan, sync.CONFIRMATION, "Publish reviewed Wiki")
        self.assertEqual(self._status(), b"")

    def test_commit_failure_rolls_clone_back_to_clean_original_state(self) -> None:
        plan = sync.build_plan(self.source, self.clone)
        original_head = self._head()
        original_pages = {
            path.name: path.read_bytes()
            for path in self.clone.iterdir()
            if path.name != ".git"
        }
        real_run_git = sync._run_git

        def fail_commit(clone: Path, arguments: tuple[str, ...], **keywords: object):
            if arguments[0] == "commit":
                raise sync.WikiSyncError("synthetic commit failure")
            return real_run_git(clone, arguments, **keywords)

        with mock.patch.object(sync, "_run_git", side_effect=fail_commit):
            with self.assertRaisesRegex(sync.WikiSyncError, "synthetic commit failure"):
                sync.apply_plan(plan, sync.CONFIRMATION, "Publish reviewed Wiki")
        self.assertEqual(self._head(), original_head)
        self.assertEqual(self._status(), b"")
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in self.clone.iterdir()
                if path.name != ".git"
            },
            original_pages,
        )

    def test_json_plan_is_deterministic_and_declares_no_publication(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = sync.main(
                [
                    "--source-root",
                    str(self.source),
                    "--wiki-clone",
                    str(self.clone),
                    "--json",
                ]
            )
        self.assertEqual(result, 0)
        document = json.loads(output.getvalue())
        self.assertEqual(document["mode"], "dry-run")
        self.assertFalse(document["network_access"])
        self.assertFalse(document["publication_performed"])
        self.assertEqual(document["counts"], {"add": 1, "change": 1, "delete": 1})


if __name__ == "__main__":
    unittest.main()
