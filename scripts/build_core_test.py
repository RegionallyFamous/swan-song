#!/usr/bin/env python3
"""Executable contract for direct Quartus evidence output."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import quartus_evidence
import quartus_fit_audit


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts/build_core.sh"
SOURCE_COMMIT = "a" * 40
SOURCE_EPOCH = "1700000000"
OUTPUT_NAMES = (
    "ap_core.rbf",
    "ap_core.map.rpt",
    "ap_core.fit.rpt",
    "ap_core.asm.rpt",
    "ap_core.sta.rpt",
    "ap_core.flow.rpt",
)
BUILD_OWNED_EVIDENCE = {
    Path("quartus.log"),
    Path("ap_core.rbf.sha256"),
    Path("build-metadata.txt"),
    Path("toolchain-version.txt"),
    Path("build_id.mif"),
    *(Path("output_files") / name for name in OUTPUT_NAMES),
}
HOST_POSTBUILD_EVIDENCE = {
    Path("container-provenance.json"),
    Path("container-packages.tsv"),
    Path("quartus-audit-candidate.json"),
    Path("quartus-audit-candidate.attestation.json"),
}


class BuildCoreEvidenceTest(unittest.TestCase):
    def fixture(self, *, compile_exit: int = 0, omit: str | None = None):
        temporary = tempfile.TemporaryDirectory(prefix="swan-song-build-core-")
        root = Path(temporary.name)
        scripts = root / "scripts"
        fpga = root / "src/fpga"
        output = fpga / "output_files"
        apf = fpga / "apf"
        tools = root / "tools"
        artifacts = root / "artifacts"
        for directory in (scripts, output, apf, tools, artifacts):
            directory.mkdir(parents=True, exist_ok=True)
        build = scripts / "build_core.sh"
        shutil.copy2(BUILD, build)
        build.chmod(0o755)
        (scripts / "quartus_signoff_paths.tcl").write_text("# fixture\n")
        (apf / "build_id.mif").write_text(
            "-- fixture build ID\n0E2 : aaaaaaaa;\n", encoding="utf-8"
        )

        quartus_sh = tools / "quartus_sh"
        shell_lines = [
            "#!/usr/bin/env bash",
            "set -eu",
            "if [[ \"${1:-}\" == --version ]]; then",
            "  echo 'Version 21.1.1 Build 850 06/23/2022 SJ Lite Edition'",
            "  exit 0",
            "fi",
            "mkdir -p output_files",
            "echo 'fake Quartus compile'",
        ]
        for name in OUTPUT_NAMES:
            if name != omit:
                shell_lines.append(f"printf 'current {name}\\n' > output_files/{name}")
        shell_lines.append(f"exit {compile_exit}")
        quartus_sh.write_text("\n".join(shell_lines) + "\n", encoding="utf-8")
        quartus_sh.chmod(0o755)

        quartus_sta = tools / "quartus_sta"
        quartus_sta.write_text(
            "#!/usr/bin/env bash\nset -eu\n"
            "echo 'fake strict post-fit signoff'\n"
            "printf 'signoff appended\\n' >> output_files/ap_core.sta.rpt\n",
            encoding="utf-8",
        )
        quartus_sta.chmod(0o755)
        uname = tools / "uname"
        uname.write_text(
            "#!/usr/bin/env bash\n"
            "case \"${1:-}\" in -s) echo Linux ;; -m) echo x86_64 ;; *) exit 2 ;; esac\n",
            encoding="utf-8",
        )
        uname.chmod(0o755)

        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{tools}:{environment['PATH']}",
                "QUARTUS_SH": str(quartus_sh),
                "QUARTUS_STA": str(quartus_sta),
                "SWANSONG_SOURCE_COMMIT": SOURCE_COMMIT,
                "SOURCE_DATE_EPOCH": SOURCE_EPOCH,
                "SWANSONG_WORKFLOW_REPOSITORY": "RegionallyFamous/swan-song",
                "SWANSONG_WORKFLOW_PATH": ".github/workflows/quartus-fit.yml",
                "SWANSONG_WORKFLOW_SHA": SOURCE_COMMIT,
                "SWANSONG_WORKFLOW_RUN_ID": "100",
                "SWANSONG_WORKFLOW_RUN_ATTEMPT": "1",
                "SWANSONG_WORKFLOW_JOB": "fit",
                "SWANSONG_BUILD_JOB_NONCE": "0" * 32,
                "SWANSONG_BUILD_CLASS": "candidate",
            }
        )
        return temporary, root, build, output, artifacts, tools, environment

    @staticmethod
    def files(root: Path) -> set[Path]:
        return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}

    def test_success_emits_every_build_owned_allowlisted_file(self) -> None:
        fixture = self.fixture()
        temporary, _, build, _, artifacts, _, environment = fixture
        with temporary:
            result = subprocess.run(
                [str(build), "--artifacts", str(artifacts)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.files(artifacts), BUILD_OWNED_EVIDENCE)
            allowlist = {item.relative for item in quartus_evidence.EVIDENCE_FILES}
            self.assertEqual(
                BUILD_OWNED_EVIDENCE,
                allowlist - HOST_POSTBUILD_EVIDENCE,
            )
            self.assertTrue(HOST_POSTBUILD_EVIDENCE.isdisjoint(self.files(artifacts)))
            rbf = artifacts / "output_files/ap_core.rbf"
            digest = hashlib.sha256(rbf.read_bytes()).hexdigest()
            self.assertEqual(
                (artifacts / "ap_core.rbf.sha256").read_text(),
                f"{digest}  /artifacts/output_files/ap_core.rbf\n",
            )
            self.assertEqual(
                (artifacts / "build-metadata.txt").read_text().splitlines(),
                [
                    f"source_commit={SOURCE_COMMIT}",
                    f"source_date_epoch={SOURCE_EPOCH}",
                    "workflow_repository=RegionallyFamous/swan-song",
                    "workflow_path=.github/workflows/quartus-fit.yml",
                    f"workflow_sha={SOURCE_COMMIT}",
                    "workflow_run_id=100",
                    "workflow_run_attempt=1",
                    "workflow_job=fit",
                    "workflow_job_nonce=" + "0" * 32,
                    "platform=linux/amd64",
                    "quartus=21.1.1.850 Lite",
                    "device=5CEBA4F23C8",
                ],
            )
            self.assertIn("fake Quartus compile", (artifacts / "quartus.log").read_text())
            self.assertIn(
                "fake strict post-fit signoff", (artifacts / "quartus.log").read_text()
            )

    def test_development_evidence_works_without_github_identity_and_cannot_be_candidate(self) -> None:
        fixture = self.fixture()
        temporary, _, build, _, artifacts, _, environment = fixture
        with temporary:
            environment["SWANSONG_BUILD_CLASS"] = "development"
            for name in (
                "SWANSONG_WORKFLOW_REPOSITORY",
                "SWANSONG_WORKFLOW_PATH",
                "SWANSONG_WORKFLOW_SHA",
                "SWANSONG_WORKFLOW_RUN_ID",
                "SWANSONG_WORKFLOW_RUN_ATTEMPT",
                "SWANSONG_WORKFLOW_JOB",
                "SWANSONG_BUILD_JOB_NONCE",
            ):
                environment.pop(name, None)
            result = subprocess.run(
                [str(build), "--artifacts", str(artifacts)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            metadata = (artifacts / "build-metadata.txt").read_text().splitlines()
            self.assertIn("build_class=development", metadata)
            self.assertFalse(any(line.startswith("workflow_") for line in metadata))
            with self.assertRaisesRegex(
                quartus_fit_audit.AuditError,
                "workflow_repository mismatch",
            ):
                quartus_fit_audit.parse_metadata(
                    (artifacts / "build-metadata.txt").read_text()
                )

    def test_failed_compile_preserves_only_current_partial_evidence(self) -> None:
        fixture = self.fixture(compile_exit=37, omit="ap_core.rbf")
        temporary, _, build, output, artifacts, _, environment = fixture
        with temporary:
            for name in OUTPUT_NAMES:
                (output / name).write_text(f"stale {name}\n", encoding="utf-8")
            result = subprocess.run(
                [str(build), "--artifacts", str(artifacts)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
            self.assertFalse((output / "ap_core.rbf").exists())
            self.assertFalse((artifacts / "output_files/ap_core.rbf").exists())
            self.assertEqual(
                self.files(artifacts),
                {Path("quartus.log"), *(Path("output_files") / name for name in OUTPUT_NAMES if name != "ap_core.rbf")},
            )
            for path in self.files(artifacts) - {Path("quartus.log")}:
                self.assertNotIn("stale", (artifacts / path).read_text())

    def test_success_missing_required_report_discards_bitstream(self) -> None:
        fixture = self.fixture(omit="ap_core.asm.rpt")
        temporary, _, build, output, artifacts, _, environment = fixture
        with temporary:
            result = subprocess.run(
                [str(build), "--artifacts", str(artifacts)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
            self.assertIn("required compilation artifact", result.stdout + result.stderr)
            self.assertFalse((output / "ap_core.rbf").exists())
            self.assertFalse((artifacts / "output_files/ap_core.rbf").exists())

    def test_log_failure_discards_bitstream(self) -> None:
        fixture = self.fixture()
        temporary, _, build, output, artifacts, tools, environment = fixture
        with temporary:
            tee = tools / "tee"
            tee.write_text("#!/usr/bin/env bash\ncat >/dev/null\nexit 23\n")
            tee.chmod(0o755)
            result = subprocess.run(
                [str(build), "--artifacts", str(artifacts)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 83, result.stdout + result.stderr)
            self.assertIn("tee status 23", result.stderr)
            self.assertFalse((output / "ap_core.rbf").exists())
            self.assertFalse((artifacts / "output_files/ap_core.rbf").exists())

    def test_rejects_nonempty_output_and_unpaired_identity_before_compile(self) -> None:
        fixture = self.fixture()
        temporary, _, build, _, artifacts, _, environment = fixture
        with temporary:
            (artifacts / "stale").write_text("must not overwrite")
            result = subprocess.run(
                [str(build), "--artifacts", str(artifacts)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 73)
            self.assertIn("must be empty", result.stderr)
            self.assertEqual((artifacts / "stale").read_text(), "must not overwrite")

        fixture = self.fixture()
        temporary, _, build, _, artifacts, _, environment = fixture
        with temporary:
            environment.pop("SOURCE_DATE_EPOCH")
            result = subprocess.run(
                [str(build), "--artifacts", str(artifacts)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(result.returncode, 76)
            self.assertIn("must be supplied together", result.stderr)
            self.assertEqual(self.files(artifacts), set())


if __name__ == "__main__":
    unittest.main()
