#!/usr/bin/env python3

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "scripts/quartus_docker.sh"
DOCKERFILE = ROOT / "toolchains/quartus-21.1.1/Dockerfile"
CONTAINER_BUILD = ROOT / "toolchains/quartus-21.1.1/container-build-core.sh"
TOOLCHAIN_CHECK = ROOT / "toolchains/quartus-21.1.1/toolchain-check.sh"


class QuartusDockerContractTest(unittest.TestCase):
    def test_shell_scripts_parse(self) -> None:
        for script in (HOST, CONTAINER_BUILD, TOOLCHAIN_CHECK):
            subprocess.run(["bash", "-n", str(script)], check=True)

    def test_archive_and_component_identities_are_pinned(self) -> None:
        sources = (ROOT / "scripts/quartus_archive.py").read_text() + DOCKERFILE.read_text()
        for digest in (
            "789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc",
            "6b25e8c62535d0ac02a1075b3dd334d2b04394aa",
            "467123b7bd5e6907beb7d6b1e073ed7bad3e5e94",
        ):
            self.assertIn(digest, sources)

    def test_image_is_amd64_lite_and_cyclone_v_only(self) -> None:
        dockerfile = DOCKERFILE.read_text()
        self.assertIn("FROM --platform=linux/amd64", dockerfile)
        self.assertIn("QUARTUS_ACCEPT_EULA", dockerfile)
        self.assertIn("QuartusLiteSetup-21.1.1.850-linux.run", dockerfile)
        self.assertIn("cyclonev-21.1.1.850.qdz", dockerfile)
        self.assertNotIn("QuestaSetup", dockerfile)
        self.assertNotIn("QuartusHelpSetup", dockerfile)
        for excluded in ("arria_lite-", "cyclone10lp-", "max10-", "max-"):
            self.assertNotIn(excluded, dockerfile)

    def test_runtime_is_offline_and_source_is_read_only(self) -> None:
        host = HOST.read_text()
        self.assertIn("--platform linux/amd64", host)
        self.assertIn("--network none", host)
        self.assertIn('"$ROOT:/source:ro"', host)
        self.assertIn('"$output:/artifacts:rw"', host)

    def test_build_uses_exact_clean_commit_and_requires_reports(self) -> None:
        script = CONTAINER_BUILD.read_text()
        self.assertIn("diff --quiet", script)
        self.assertIn("diff --cached --quiet", script)
        self.assertIn('safe.directory=$source_root', script)
        self.assertIn('"${git_source[@]}" archive', script)
        self.assertIn("SWANSONG_SOURCE_COMMIT", script)
        self.assertIn("SOURCE_DATE_EPOCH", script)
        for artifact in (
            "ap_core.rbf",
            "ap_core.fit.rpt",
            "ap_core.asm.rpt",
            "ap_core.sta.rpt",
            "ap_core.flow.rpt",
        ):
            self.assertIn(artifact, script)

    def test_host_runs_fail_closed_candidate_auditor(self) -> None:
        host = HOST.read_text()
        self.assertIn('python3 "$ROOT/scripts/quartus_fit_audit.py"', host)
        self.assertIn("quartus-audit-candidate.json", host)

    def test_toolchain_gate_checks_exact_version_edition_and_part(self) -> None:
        check = TOOLCHAIN_CHECK.read_text()
        self.assertIn("Version 21.1.1 Build 850", check)
        self.assertIn("Lite Edition", check)
        self.assertIn("5CEBA4F23C8", check)
        self.assertIn("Cyclone V", check)


if __name__ == "__main__":
    unittest.main()
