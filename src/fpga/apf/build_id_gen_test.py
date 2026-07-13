#!/usr/bin/env python3
"""Focused contract tests for the reproducible APF build-ID generator."""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).with_name("build_id_gen.tcl")
MIF_RELATIVE = pathlib.Path("src/fpga/apf/build_id.mif")
DECLARED_ENV = ("SOURCE_DATE_EPOCH", "SWANSONG_SOURCE_COMMIT")


def command(
    arguments: list[str],
    *,
    cwd: pathlib.Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def clean_environment() -> dict[str, str]:
    result = os.environ.copy()
    for name in (*DECLARED_ENV, "TZ"):
        result.pop(name, None)
    return result


def run_generator(
    root: pathlib.Path,
    *,
    overrides: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    environment = clean_environment()
    if overrides:
        environment.update(overrides)
    return command(
        [shutil.which("tclsh") or "tclsh", "apf/build_id_gen.tcl"],
        cwd=root / "src/fpga",
        env=environment,
        check=check,
    )


def parse_mif(data: bytes) -> tuple[str, dict[str, str]]:
    text = data.decode("utf-8")
    if "\r" in text:
        raise AssertionError("build ID MIF must use stable LF line endings")
    assignments = dict(
        re.findall(
            r"^\s*([0-9A-F]{3})\s*:\s*([0-9A-Fa-f]{8});\s*$",
            text,
            re.MULTILINE,
        )
    )
    return text, assignments


class BuildIdGeneratorTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if shutil.which("git") is None:
            self.fail("git is required for build_id_gen_test.py")
        if shutil.which("tclsh") is None:
            self.fail("tclsh is required for build_id_gen_test.py")

    def make_git_checkout(self, parent: pathlib.Path) -> tuple[pathlib.Path, str, int]:
        root = parent / "checkout"
        apf = root / "src/fpga/apf"
        apf.mkdir(parents=True)
        shutil.copy2(SCRIPT, apf / SCRIPT.name)
        (apf / "build_id.mif").write_text("-- tracked placeholder\n")
        (root / "tracked-input.txt").write_text("source input\n")

        command(["git", "init", "-q"], cwd=root)
        command(["git", "config", "user.name", "Build ID Test"], cwd=root)
        command(
            ["git", "config", "user.email", "build-id-test.invalid@example.invalid"],
            cwd=root,
        )
        command(["git", "add", "."], cwd=root)
        commit_environment = clean_environment()
        commit_environment.update(
            {
                "GIT_AUTHOR_DATE": "2001-02-03T04:05:06Z",
                "GIT_COMMITTER_DATE": "2001-02-03T04:05:06Z",
            }
        )
        command(
            ["git", "commit", "-q", "-m", "fixture"],
            cwd=root,
            env=commit_environment,
        )
        commit = command(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
        epoch = int(
            command(
                ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=root
            ).stdout.strip()
        )
        return root, commit, epoch

    def assert_mif_contract(
        self,
        data: bytes,
        *,
        commit: str,
        epoch: int,
        date: str,
        time: str,
    ) -> None:
        text, assignments = parse_mif(data)
        self.assertIn("DEPTH = 256;", text)
        self.assertIn("WIDTH = 32;", text)
        self.assertIn("ADDRESS_RADIX = HEX;", text)
        self.assertIn("DATA_RADIX = HEX;", text)
        self.assertIn(f"-- Reproducible source commit: {commit.lower()}", text)
        self.assertIn(f"-- SOURCE_DATE_EPOCH: {epoch}", text)
        self.assertEqual(
            assignments,
            {
                "0E0": date,
                "0E1": f"00{time}",
                "0E2": commit[:8].lower(),
            },
        )

    def test_git_commit_identity_is_repeatable_and_utc(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-build-id-git-") as temporary:
            root, commit, epoch = self.make_git_checkout(pathlib.Path(temporary))
            mif = root / MIF_RELATIVE

            run_generator(root)
            first = mif.read_bytes()
            source_time = dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
            self.assert_mif_contract(
                first,
                commit=commit,
                epoch=epoch,
                date=source_time.strftime("%Y%m%d"),
                time=source_time.strftime("%H%M%S"),
            )

            # The generated, tracked MIF is deliberately excluded from the clean
            # source check, so a second identical build remains possible.
            run_generator(root)
            self.assertEqual(mif.read_bytes(), first)

            declared = {
                "SOURCE_DATE_EPOCH": "0",
                "SWANSONG_SOURCE_COMMIT": commit,
                "TZ": "Pacific/Kiritimati",
            }
            run_generator(root, overrides=declared)
            epoch_zero = mif.read_bytes()
            self.assert_mif_contract(
                epoch_zero,
                commit=commit,
                epoch=0,
                date="19700101",
                time="000000",
            )
            declared["TZ"] = "America/Chicago"
            run_generator(root, overrides=declared)
            self.assertEqual(mif.read_bytes(), epoch_zero)

    def test_git_checkout_fails_closed_on_mismatch_or_dirty_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-build-id-dirty-") as temporary:
            root, commit, _ = self.make_git_checkout(pathlib.Path(temporary))
            mif = root / MIF_RELATIVE
            run_generator(root)
            before = mif.read_bytes()

            marker = root / "tracked-input.txt"
            marker.write_text("dirty source input\n")
            failed = run_generator(root, check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("unstaged changes", failed.stderr)
            self.assertEqual(mif.read_bytes(), before)
            marker.write_text("source input\n")

            failed = run_generator(
                root,
                overrides={
                    "SOURCE_DATE_EPOCH": "0",
                    "SWANSONG_SOURCE_COMMIT": "0" * 40,
                },
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("does not match Git HEAD", failed.stderr)
            self.assertEqual(mif.read_bytes(), before)

            for invalid in ("not-an-epoch", "253402300800"):
                failed = run_generator(
                    root,
                    overrides={
                        "SOURCE_DATE_EPOCH": invalid,
                        "SWANSONG_SOURCE_COMMIT": commit,
                    },
                    check=False,
                )
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("SOURCE_DATE_EPOCH", failed.stderr)
                self.assertEqual(mif.read_bytes(), before)

    def test_non_git_source_requires_both_declared_inputs(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="swan-build-id-archive-"
        ) as temporary:
            root = pathlib.Path(temporary) / "archive"
            apf = root / "src/fpga/apf"
            apf.mkdir(parents=True)
            shutil.copy2(SCRIPT, apf / SCRIPT.name)
            commit = "a1b2c3d4" * 5
            mif = root / MIF_RELATIVE

            failed = run_generator(root, check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("SWANSONG_SOURCE_COMMIT is required", failed.stderr)
            self.assertFalse(mif.exists())

            failed = run_generator(
                root,
                overrides={"SWANSONG_SOURCE_COMMIT": commit},
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("SOURCE_DATE_EPOCH is required", failed.stderr)
            self.assertFalse(mif.exists())

            declared = {
                "SOURCE_DATE_EPOCH": "946684800",
                "SWANSONG_SOURCE_COMMIT": commit.upper(),
                "TZ": "America/Chicago",
            }
            run_generator(root, overrides=declared)
            first = mif.read_bytes()
            self.assert_mif_contract(
                first,
                commit=commit,
                epoch=946684800,
                date="20000101",
                time="000000",
            )
            declared["TZ"] = "Asia/Tokyo"
            run_generator(root, overrides=declared)
            self.assertEqual(mif.read_bytes(), first)

    def test_live_clock_and_rng_primitives_are_absent(self) -> None:
        source = SCRIPT.read_text()
        self.assertNotIn("clock seconds", source)
        self.assertNotRegex(source, r"\brand\s*\(")


if __name__ == "__main__":
    unittest.main(verbosity=2)
