#!/usr/bin/env python3
"""Offline integration tests for prepare_launch_pr.py."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_launch_pr.py").resolve()
SPEC = importlib.util.spec_from_file_location("prepare_launch_pr", SCRIPT)
assert SPEC and SPEC.loader
HANDOFF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDOFF)


def run(args: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            f"command failed ({' '.join(args)}):\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


class Fixture:
    def __init__(self, root: Path, *, tree_drift: bool = False) -> None:
        self.root = root
        self.repo = root / "repo"
        self.origin = root / "origin.git"
        self.mock_bin = root / "bin"
        self.gh_log = root / "gh.log"
        self.repo.mkdir()
        self.mock_bin.mkdir()

        run(["git", "init", "--initial-branch=main"], self.repo)
        run(["git", "config", "user.name", "Swan Song Test"], self.repo)
        run(["git", "config", "user.email", "test@example.invalid"], self.repo)
        for path, status in HANDOFF.EXPECTED_CHANGES.items():
            if status == "A":
                continue
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"base:{path}\n")
        (self.repo / "unrelated-tracked.txt").write_text("leave unchanged\n")
        run(["git", "add", "--all"], self.repo)
        run(["git", "commit", "-m", "base"], self.repo)

        run(["git", "init", "--bare", str(self.origin)], root)
        self._disable_bare_background_writers(self.origin)
        github_url = f"https://github.com/{HANDOFF.REPOSITORY}.git"
        run(
            ["git", "remote", "add", "origin", f"file://{self.origin.as_posix()}"],
            self.repo,
        )
        run(["git", "push", "--set-upstream", "origin", "main"], self.repo)
        run(["git", "remote", "set-url", "origin", github_url], self.repo)
        if tree_drift:
            (self.repo / "base-drift.txt").write_text("not on origin/main\n")
            run(["git", "add", "base-drift.txt"], self.repo)
            run(["git", "commit", "-m", "different tree"], self.repo)
        else:
            # Mirror the real handoff: commit IDs may differ while trees are exact.
            run(["git", "commit", "--allow-empty", "-m", "same tree metadata"], self.repo)

        for path, status in HANDOFF.EXPECTED_CHANGES.items():
            target = self.repo / path
            if status == "M":
                with target.open("a") as handle:
                    handle.write("launch hardening\n")
            elif status == "D":
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"new:{path}\n")

        self.preserved_snapshot: dict[str, tuple[str, bytes | str]] = {}
        for path in sorted(HANDOFF.PRESERVED_UNTRACKED):
            target = self.repo / path
            if path == "node_modules":
                target.symlink_to("/private/tmp/swan-song-node-modules")
                self.preserved_snapshot[path] = ("symlink", os.readlink(target))
            elif path.endswith("/"):
                target.mkdir(parents=True)
                payload = target / "user-work.bin"
                content = f"preserve:{path}".encode()
                payload.write_bytes(content)
                self.preserved_snapshot[path] = ("directory", content)
            else:
                content = f"preserve:{path}".encode()
                target.write_bytes(content)
                self.preserved_snapshot[path] = ("file", content)

        mock = self.mock_bin / "gh"
        mock.write_text(
            """#!/bin/sh
printf '%s\\n' "$*" >> "$MOCK_GH_LOG"
if [ "$1 $2" = "auth status" ]; then
  [ "${MOCK_GH_AUTH_FAIL:-0}" = 0 ]
  exit $?
fi
if [ "$1 $2" = "repo view" ]; then
  printf '%s\\n' "${MOCK_GH_REPO:-RegionallyFamous/swan-song}"
  exit 0
fi
if [ "$1 $2" = "pr create" ]; then
  printf '%s\\n' 'https://github.com/RegionallyFamous/swan-song/pull/999'
  exit 0
fi
exit 91
"""
        )
        mock.chmod(0o755)

        real_git = shutil.which("git")
        if real_git is None:
            raise AssertionError("git is required for the handoff fixture")
        git_mock = self.mock_bin / "git"
        git_mock.write_text(
            """#!/usr/bin/env python3
import os
import subprocess
import sys

args = sys.argv[1:]
if args and args[0] == "push" and os.environ.get("RACE_MARKER"):
    marker = os.environ["RACE_MARKER"]
    if not os.path.exists(marker):
        subprocess.run(
            [
                os.environ["REAL_GIT"],
                "--git-dir=" + os.environ["RACE_ORIGIN"],
                "update-ref",
                "refs/heads/" + os.environ["RACE_BRANCH"],
                os.environ["RACE_BASE"],
            ],
            check=True,
        )
        open(marker, "x").close()

transport = "file://" + os.environ["MOCK_GIT_ORIGIN"]
canonical = os.environ["MOCK_GIT_CANONICAL"]
args = [transport if arg in ("origin", canonical) else arg for arg in args]
os.execv(os.environ["REAL_GIT"], [os.environ["REAL_GIT"], *args])
"""
        )
        git_mock.chmod(0o755)

    @staticmethod
    def _disable_bare_background_writers(repository: Path) -> None:
        # A receive-pack may otherwise detach maintenance/update-server-info
        # after a push. Keep TemporaryDirectory cleanup strict by preventing
        # background writers rather than masking ENOTEMPTY.
        for key, value in (
            ("gc.auto", "0"),
            ("gc.autoDetach", "false"),
            ("maintenance.auto", "false"),
            ("maintenance.autoDetach", "false"),
            ("receive.autogc", "false"),
            ("receive.updateServerInfo", "false"),
            ("repack.updateServerInfo", "false"),
        ):
            run(
                ["git", f"--git-dir={repository}", "config", key, value],
                repository.parent,
            )

    def env(self, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.mock_bin}{os.pathsep}{env['PATH']}"
        env["MOCK_GH_LOG"] = str(self.gh_log)
        env["REAL_GIT"] = shutil.which("git") or "git"
        env["MOCK_GIT_ORIGIN"] = str(self.origin)
        env["MOCK_GIT_CANONICAL"] = HANDOFF.CANONICAL_REPOSITORY_URL
        env.update(extra)
        return env

    def handoff(
        self, *args: str, input_text: str | None = None, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [os.environ.get("PYTHON", "python3"), str(SCRIPT), *args],
            cwd=self.repo,
            env=env or self.env(),
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def assert_preserved(self, testcase: unittest.TestCase) -> None:
        for path, (kind, content) in self.preserved_snapshot.items():
            target = self.repo / path
            if kind == "symlink":
                testcase.assertTrue(target.is_symlink())
                testcase.assertEqual(os.readlink(target), content)
            elif kind == "directory":
                testcase.assertEqual((target / "user-work.bin").read_bytes(), content)
            else:
                testcase.assertEqual(target.read_bytes(), content)


class HandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-song-handoff-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self, *, tree_drift: bool = False) -> Fixture:
        return Fixture(self.root, tree_drift=tree_drift)

    def test_allowlist_covers_current_launch_hardening_work(self) -> None:
        required = {
            "FIRST_CLASS_INPUT_DOCK.md",
            "FRAME_DELIVERY.md",
            "HOMEBREW_WONDERWITCH.md",
            "MEMORIES_STAGING.md",
            "SAVESTATE_SDRAM_READER.md",
            "SAVESTATE_V2_FORMAT.md",
            "SWAN_SONG_DOCTOR.md",
            "docs/wiki/Architecture.md",
            "scripts/frame_delivery_metrics.py",
            "scripts/frame_delivery_metrics_test.py",
            "scripts/known_title_compatibility.py",
            "scripts/known_title_compatibility_test.py",
            "scripts/mapper_2003_gpo_contract_test.py",
            "scripts/pocket_console_setup_contract_test.py",
            "scripts/pocket_hardware_qa.py",
            "scripts/pocket_hardware_qa_test.py",
            "scripts/pocket_menu_focus_contract_test.py",
            "scripts/pocket_synchronizer_attribute_contract_test.py",
            "scripts/prepare_hardware_qa_workspace.py",
            "scripts/prepare_hardware_qa_workspace_test.py",
            "scripts/swan_song_doctor.py",
            "scripts/swan_song_doctor_test.py",
            "scripts/with_native_macos_ghdl.sh",
            "scripts/with_native_macos_ghdl_test.py",
            "sim/rtl/apf_console_setup_tb.sv",
            "sim/rtl/apf_menu_focus_cdc_tb.sv",
            "sim/rtl/apf_menu_focus_pause_tb.sv",
            "sim/rtl/apf_scanout_cadence_tb.sv",
            "sim/rtl/apf_savestate_sdram_reader_tb.sv",
            "sim/rtl/apf_savestate_v2_load_settle_guard_tb.sv",
            "sim/rtl/apf_savestate_v2_owner_tb.sv",
            "sim/rtl/apf_savestate_v2_restore_preflight_tb.sv",
            "sim/rtl/apf_system_type_reset_composition_tb.sv",
            "sim/rtl/eeprom_state_tb.vhd",
            "sim/rtl/footer_snapshot_tb.sv",
            "sim/rtl/rtc_state_tb.vhd",
            "sim/rtl/run_sdram_quiescent_tb.sh",
            "sim/rtl/sdram_quiescent_tb.sv",
            "sim/rtl/apf_interact_readback_tb.sv",
            "sim/rtl/run_apf_interact_readback_tb.sh",
            "sim/rtl/run_apf_menu_focus_cdc_tb.sh",
            "sim/rtl/run_apf_menu_focus_pause_tb.sh",
            "sim/rtl/run_apf_savestate_v2_load_settle_guard_tb.sh",
            "sim/rtl/run_apf_savestate_v2_restore_preflight_tb.sh",
            "sim/rtl/run_swantop_menu_pause_tb.sh",
            "sim/rtl/swantop_menu_pause_tb.sv",
            "sim/rtl/apf_temporal_blend_tb.sv",
            "src/fpga/ap_core.qsf",
            "src/fpga/core/apf_console_setup.sv",
            "src/fpga/core/apf_interact_readback.sv",
            "src/fpga/core/apf_menu_focus_cdc.sv",
            "src/fpga/core/apf_scanout_cadence.sv",
            "src/fpga/core/apf_savestate_sdram_reader.sv",
            "src/fpga/core/apf_savestate_v2_load_settle_guard.sv",
            "src/fpga/core/apf_savestate_v2_owner.sv",
            "src/fpga/core/apf_savestate_v2_restore_preflight.sv",
            "src/fpga/core/apf_temporal_blend.sv",
            "src/fpga/core/core_top.v",
            "scripts/pocket_control_layout_contract_test.py",
            "scripts/memories_channel1_contract_test.py",
            "docs/wiki/Playing-Games.md",
        }
        self.assertEqual(len(HANDOFF.EXPECTED_CHANGES), 188)
        self.assertEqual(len(HANDOFF.PRESERVED_UNTRACKED), 12)
        self.assertLessEqual(required, set(HANDOFF.EXPECTED_CHANGES))
        added = {
            "scripts/mapper_2003_gpo_contract_test.py",
            "scripts/prepare_hardware_qa_workspace.py",
            "scripts/prepare_hardware_qa_workspace_test.py",
            "scripts/with_native_macos_ghdl.sh",
            "scripts/with_native_macos_ghdl_test.py",
            "sim/rtl/apf_menu_focus_cdc_tb.sv",
            "sim/rtl/apf_interact_readback_tb.sv",
            "sim/rtl/apf_menu_focus_pause_tb.sv",
            "sim/rtl/apf_savestate_v2_load_settle_guard_tb.sv",
            "sim/rtl/apf_savestate_v2_restore_preflight_tb.sv",
            "sim/rtl/run_apf_menu_focus_cdc_tb.sh",
            "sim/rtl/run_apf_interact_readback_tb.sh",
            "sim/rtl/run_apf_menu_focus_pause_tb.sh",
            "sim/rtl/run_apf_savestate_v2_load_settle_guard_tb.sh",
            "sim/rtl/run_apf_savestate_v2_restore_preflight_tb.sh",
            "sim/rtl/run_swantop_menu_pause_tb.sh",
            "sim/rtl/swantop_menu_pause_tb.sv",
            "src/fpga/core/apf_menu_focus_cdc.sv",
            "src/fpga/core/apf_interact_readback.sv",
            "src/fpga/core/apf_savestate_v2_load_settle_guard.sv",
            "src/fpga/core/apf_savestate_v2_restore_preflight.sv",
        }
        self.assertTrue(
            all(HANDOFF.EXPECTED_CHANGES[path] == "A" for path in added)
        )
        self.assertTrue(
            all(
                HANDOFF.EXPECTED_CHANGES[path] == "M"
                for path in required - added
            )
        )
        self.assertTrue(
            set(HANDOFF.EXPECTED_CHANGES).isdisjoint(HANDOFF.PRESERVED_UNTRACKED)
        )

    def test_dry_run_is_read_only(self) -> None:
        fixture = self.fixture()
        before = run(["git", "rev-parse", "HEAD"], fixture.repo)
        result = fixture.handoff()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("no merge", result.stdout)
        self.assertIn("none will be staged", result.stdout)
        self.assertEqual(run(["git", "rev-parse", "HEAD"], fixture.repo), before)
        self.assertEqual(run(["git", "branch", "--show-current"], fixture.repo), "main")
        self.assertNotIn("pr create", fixture.gh_log.read_text())
        fixture.assert_preserved(self)

    def test_apply_stages_exact_set_pushes_and_opens_without_merge(self) -> None:
        fixture = self.fixture()
        branch = "codex/offline-handoff-test"
        phrase = HANDOFF.confirmation(branch)
        result = fixture.handoff("--apply", "--branch", branch, input_text=f"{phrase}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("intentionally did not merge", result.stdout)
        self.assertEqual(run(["git", "branch", "--show-current"], fixture.repo), branch)
        self.assertEqual(
            HANDOFF.parse_status(fixture.repo),
            {path: "A" for path in HANDOFF.PRESERVED_UNTRACKED},
        )
        local = run(["git", "rev-parse", "HEAD"], fixture.repo)
        remote = run(
            ["git", f"--git-dir={fixture.origin}", "rev-parse", f"refs/heads/{branch}"],
            fixture.root,
        )
        self.assertEqual(local, remote)
        names = run(
            ["git", "diff", "--name-only", "origin/main..HEAD"], fixture.repo
        ).splitlines()
        self.assertEqual(names, sorted(HANDOFF.EXPECTED_CHANGES))
        gh_calls = fixture.gh_log.read_text()
        self.assertIn("auth status", gh_calls)
        self.assertIn("repo view", gh_calls)
        self.assertIn("pr create", gh_calls)
        self.assertNotIn("pr merge", gh_calls)
        fixture.assert_preserved(self)

    def test_apply_ignores_origin_pushurl_and_uses_canonical_repository(self) -> None:
        fixture = self.fixture()
        other = self.root / "other.git"
        run(["git", "init", "--bare", str(other)], self.root)
        fixture._disable_bare_background_writers(other)
        run(
            ["git", "config", "remote.origin.pushurl", f"file://{other}"],
            fixture.repo,
        )
        branch = "codex/pushurl-isolation-test"
        result = fixture.handoff(
            "--apply",
            "--branch",
            branch,
            input_text=f"{HANDOFF.confirmation(branch)}\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = run(
            [
                "git",
                f"--git-dir={fixture.origin}",
                "rev-parse",
                f"refs/heads/{branch}",
            ],
            self.root,
        )
        self.assertEqual(expected, run(["git", "rev-parse", "HEAD"], fixture.repo))
        absent = subprocess.run(
            [
                "git",
                f"--git-dir={other}",
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
            ],
            cwd=self.root,
            check=False,
        )
        self.assertEqual(absent.returncode, 1)

    def test_push_instead_of_rewrite_is_rejected_before_mutation(self) -> None:
        fixture = self.fixture()
        evil = self.root / "evil-push.git"
        run(["git", "init", "--bare", str(evil)], self.root)
        fixture._disable_bare_background_writers(evil)
        run(
            [
                "git",
                "config",
                f"url.file://{evil.as_posix()}.pushInsteadOf",
                HANDOFF.CANONICAL_REPOSITORY_URL,
            ],
            fixture.repo,
        )
        branch = "codex/push-rewrite-rejected"
        before = run(["git", "rev-parse", "HEAD"], fixture.repo)
        result = fixture.handoff(
            "--apply",
            "--branch",
            branch,
            input_text=f"{HANDOFF.confirmation(branch)}\n",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Git URL rewrite", result.stderr)
        self.assertEqual(run(["git", "rev-parse", "HEAD"], fixture.repo), before)
        self.assertEqual(run(["git", "branch", "--show-current"], fixture.repo), "main")
        for repository in (fixture.origin, evil):
            absent = subprocess.run(
                [
                    "git",
                    f"--git-dir={repository}",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch}",
                ],
                cwd=self.root,
                check=False,
            )
            self.assertEqual(absent.returncode, 1)
        self.assertFalse(fixture.gh_log.exists())

    def test_instead_of_rewrite_is_rejected_before_mutation(self) -> None:
        fixture = self.fixture()
        evil = self.root / "evil-general.git"
        run(["git", "init", "--bare", str(evil)], self.root)
        fixture._disable_bare_background_writers(evil)
        run(
            [
                "git",
                "config",
                f"url.file://{evil.as_posix()}.insteadOf",
                "https://github.com/RegionallyFamous/",
            ],
            fixture.repo,
        )
        branch = "codex/general-rewrite-rejected"
        result = fixture.handoff(
            "--apply",
            "--branch",
            branch,
            input_text=f"{HANDOFF.confirmation(branch)}\n",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Git URL rewrite", result.stderr)
        self.assertEqual(run(["git", "branch", "--show-current"], fixture.repo), "main")
        self.assertFalse(fixture.gh_log.exists())
        for repository in (fixture.origin, evil):
            absent = subprocess.run(
                [
                    "git",
                    f"--git-dir={repository}",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch}",
                ],
                cwd=self.root,
                check=False,
            )
            self.assertEqual(absent.returncode, 1)

    def test_apply_disables_follow_tags_from_repository_config(self) -> None:
        fixture = self.fixture()
        tag = "private-local-tag"
        run(
            ["git", "tag", "--annotate", tag, "--message", "must stay local", "origin/main"],
            fixture.repo,
        )
        run(["git", "config", "push.followTags", "true"], fixture.repo)
        branch = "codex/no-follow-tags-test"
        result = fixture.handoff(
            "--apply",
            "--branch",
            branch,
            input_text=f"{HANDOFF.confirmation(branch)}\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        absent = subprocess.run(
            [
                "git",
                f"--git-dir={fixture.origin}",
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/tags/{tag}",
            ],
            cwd=self.root,
            check=False,
        )
        self.assertEqual(absent.returncode, 1)

    def test_branch_created_after_preflight_cannot_be_overwritten(self) -> None:
        fixture = self.fixture()
        branch = "codex/create-only-race-test"
        base = run(
            [
                "git",
                f"--git-dir={fixture.origin}",
                "rev-parse",
                "refs/heads/main",
            ],
            self.root,
        )
        marker = self.root / "race-injected"
        result = fixture.handoff(
            "--apply",
            "--branch",
            branch,
            input_text=f"{HANDOFF.confirmation(branch)}\n",
            env=fixture.env(
                RACE_ORIGIN=str(fixture.origin),
                RACE_BRANCH=branch,
                RACE_BASE=base,
                RACE_MARKER=str(marker),
            ),
        )
        self.assertEqual(result.returncode, 2)
        self.assertTrue(marker.exists())
        self.assertIn("force-with-lease", result.stderr)
        self.assertEqual(
            run(
                [
                    "git",
                    f"--git-dir={fixture.origin}",
                    "rev-parse",
                    f"refs/heads/{branch}",
                ],
                self.root,
            ),
            base,
        )
        self.assertNotIn("pr create", fixture.gh_log.read_text())

    def test_confirmation_mismatch_has_no_branch_commit_push_or_pr(self) -> None:
        fixture = self.fixture()
        before = run(["git", "rev-parse", "HEAD"], fixture.repo)
        result = fixture.handoff("--apply", input_text="no\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("confirmation did not match", result.stderr)
        self.assertEqual(run(["git", "rev-parse", "HEAD"], fixture.repo), before)
        self.assertEqual(run(["git", "branch", "--show-current"], fixture.repo), "main")
        self.assertNotIn("pr create", fixture.gh_log.read_text())

    def test_unrelated_untracked_file_is_rejected(self) -> None:
        fixture = self.fixture()
        (fixture.repo / "unrelated.txt").write_text("must not be staged\n")
        result = fixture.handoff()
        self.assertEqual(result.returncode, 2)
        self.assertIn("unexpected A  unrelated.txt", result.stderr)
        self.assertEqual(run(["git", "branch", "--show-current"], fixture.repo), "main")

    def test_unrelated_tracked_change_is_rejected(self) -> None:
        fixture = self.fixture()
        (fixture.repo / "unrelated-tracked.txt").write_text("do not stage this\n")
        result = fixture.handoff()
        self.assertEqual(result.returncode, 2)
        self.assertIn("unexpected M  unrelated-tracked.txt", result.stderr)
        self.assertEqual(run(["git", "branch", "--show-current"], fixture.repo), "main")

    def test_wrong_status_is_rejected(self) -> None:
        fixture = self.fixture()
        (fixture.repo / "BUILDING.md").unlink()
        result = fixture.handoff()
        self.assertEqual(result.returncode, 2)
        self.assertIn("wrong status D (expected M)  BUILDING.md", result.stderr)

    def test_different_head_tree_is_rejected_before_branch_switch(self) -> None:
        fixture = self.fixture(tree_drift=True)
        result = fixture.handoff(
            "--apply", input_text=f"{HANDOFF.confirmation(HANDOFF.DEFAULT_BRANCH)}\n"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not equal the freshly fetched origin/main tree", result.stderr)
        self.assertEqual(run(["git", "branch", "--show-current"], fixture.repo), "main")
        self.assertFalse(fixture.gh_log.exists() and "pr create" in fixture.gh_log.read_text())

    def test_auth_and_repository_identity_are_enforced(self) -> None:
        fixture = self.fixture()
        auth = fixture.handoff(env=fixture.env(MOCK_GH_AUTH_FAIL="1"))
        self.assertEqual(auth.returncode, 2)
        self.assertIn("gh auth status", auth.stderr)

        wrong_repo = fixture.handoff(env=fixture.env(MOCK_GH_REPO="someone/else"))
        self.assertEqual(wrong_repo.returncode, 2)
        self.assertIn("expected repository", wrong_repo.stderr)

    def test_existing_remote_branch_is_rejected(self) -> None:
        fixture = self.fixture()
        branch = HANDOFF.DEFAULT_BRANCH
        run(
            ["git", "push", "origin", f"HEAD:refs/heads/{branch}"],
            fixture.repo,
            env=fixture.env(),
        )
        result = fixture.handoff()
        self.assertEqual(result.returncode, 2)
        self.assertIn(f"remote branch already exists: origin/{branch}", result.stderr)
        self.assertNotIn("pr create", fixture.gh_log.read_text())


if __name__ == "__main__":
    unittest.main()
