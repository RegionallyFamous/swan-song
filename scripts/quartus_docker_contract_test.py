#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "scripts/quartus_docker.sh"
WORKFLOW = ROOT / ".github/workflows/quartus-fit.yml"
DOCKERFILE = ROOT / "toolchains/quartus-21.1.1/Dockerfile"
CONTAINER_BUILD = ROOT / "toolchains/quartus-21.1.1/container-build-core.sh"
TOOLCHAIN_CHECK = ROOT / "toolchains/quartus-21.1.1/toolchain-check.sh"


class QuartusDockerContractTest(unittest.TestCase):
    @staticmethod
    def run_fake_image_check(overrides: dict[str, Path] | None = None) -> subprocess.CompletedProcess[str]:
        payloads = {
            "FAKE_CONTAINER_BUILD": CONTAINER_BUILD,
            "FAKE_TOOLCHAIN_CHECK": TOOLCHAIN_CHECK,
            "FAKE_VERIFY_TCL": ROOT / "toolchains/quartus-21.1.1/verify-toolchain.tcl",
        }
        payloads.update(overrides or {})
        with tempfile.TemporaryDirectory() as temporary:
            docker = Path(temporary) / "docker"
            docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  info)
    ;;
  image)
    [[ "${2:-}" == inspect ]] || exit 90
    if [[ "${3:-}" == --format ]]; then
      case "${4:-}" in
        '{{.Os}}/{{.Architecture}}') echo linux/amd64 ;;
        *quartus.edition*) echo Lite ;;
        *quartus.version*) echo 21.1.1.850 ;;
        *quartus.device*) echo 5CEBA4F23C8 ;;
        *quartus.archive-sha1*) echo 789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc ;;
        *) exit 91 ;;
      esac
    fi
    ;;
  create)
    echo fake-container
    ;;
  cp)
    case "${2:-}" in
      *:/usr/local/bin/container-build-core) source="$FAKE_CONTAINER_BUILD" ;;
      *:/usr/local/bin/toolchain-check) source="$FAKE_TOOLCHAIN_CHECK" ;;
      *:/usr/local/share/swan-song/verify-toolchain.tcl) source="$FAKE_VERIFY_TCL" ;;
      *) exit 92 ;;
    esac
    /bin/cp "$source" "${3:-}"
    ;;
  rm|run)
    ;;
  *)
    exit 93
    ;;
esac
"""
            )
            docker.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{temporary}:{environment['PATH']}"
            for name, path in payloads.items():
                environment[name] = str(path)
            return subprocess.run(
                [str(HOST), "check-image"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

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

    def test_host_returns_container_artifacts_to_runner_ownership(self) -> None:
        host = HOST.read_text()
        container = CONTAINER_BUILD.read_text()
        self.assertIn('--env "ARTIFACT_UID=$(id -u)"', host)
        self.assertIn('--env "ARTIFACT_GID=$(id -g)"', host)
        self.assertIn('case "${ARTIFACT_UID:-}"', container)
        self.assertIn('case "${ARTIFACT_GID:-}"', container)
        self.assertIn("trap cleanup EXIT", container)
        self.assertIn("chown -R --no-dereference", container)
        self.assertIn('"$ARTIFACT_UID:$ARTIFACT_GID" "$artifact_root"', container)
        self.assertLess(
            container.index("trap cleanup EXIT"),
            container.index("/usr/local/bin/toolchain-check"),
        )

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

    def test_image_gate_compares_all_embedded_toolchain_payloads(self) -> None:
        host = HOST.read_text()
        for checkout, embedded in (
            ("container-build-core.sh", "/usr/local/bin/container-build-core"),
            ("toolchain-check.sh", "/usr/local/bin/toolchain-check"),
            ("verify-toolchain.tcl", "/usr/local/share/swan-song/verify-toolchain.tcl"),
        ):
            self.assertIn(checkout, host)
            self.assertIn(embedded, host)
        self.assertIn("sha256_file", host)
        self.assertIn("docker cp", host)

    def test_image_gate_accepts_byte_identical_embedded_payloads(self) -> None:
        result = self.run_fake_image_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_image_gate_rejects_each_stale_embedded_payload(self) -> None:
        for variable in (
            "FAKE_CONTAINER_BUILD",
            "FAKE_TOOLCHAIN_CHECK",
            "FAKE_VERIFY_TCL",
        ):
            with self.subTest(variable=variable), tempfile.TemporaryDirectory() as temporary:
                stale = Path(temporary) / "stale"
                stale.write_text("stale embedded payload\n")
                result = self.run_fake_image_check({variable: stale})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("does not match checkout", result.stderr)

    def test_vm_fit_workflow_is_manual_only_and_read_only(self) -> None:
        workflow = WORKFLOW.read_text()
        self.assertIn("on:\n  workflow_dispatch:\n", workflow)
        for forbidden_trigger in (
            "pull_request:",
            "pull_request_target:",
            "push:",
            "schedule:",
            "workflow_run:",
        ):
            self.assertNotIn(forbidden_trigger, workflow)
        self.assertIn("permissions:\n  contents: read\n", workflow)
        self.assertIn(
            "runs-on: [self-hosted, linux, x64, swan-song-quartus-21-1-1]",
            workflow,
        )
        self.assertIn(
            "if: ${{ github.ref == format('refs/heads/{0}', "
            "github.event.repository.default_branch) }}",
            workflow,
        )
        self.assertIn("persist-credentials: false", workflow)

    def test_vm_fit_workflow_checks_real_host_before_checkout(self) -> None:
        workflow = WORKFLOW.read_text()
        host_check = workflow.index('operating_system="$(uname -s)"')
        self.assertIn('architecture="$(uname -m)"', workflow)
        self.assertIn('[[ "$operating_system" != Linux ]]', workflow)
        self.assertIn('[[ "$architecture" != x86_64 ]]', workflow)
        self.assertLess(host_check, workflow.index("uses: actions/checkout@"))

    def test_vm_fit_workflow_runs_regression_before_quartus(self) -> None:
        workflow = WORKFLOW.read_text()
        for digest in (
            "verilator/verilator@sha256:"
            "c531ae1e5da8e7293a2bd6793060c2bf484dac358746e69bcc3e689ec265b299",
            "ghdl/ghdl@sha256:"
            "8b3ec37c3873b2eee9387759e66c50830c15ae5b7b533badaa97ce007a0f8022",
        ):
            self.assertIn(digest, workflow)
        toolchain = workflow.index(".github/toolchain/verify.sh")
        regression = workflow.index("run: make regression")
        image = workflow.index("quartus_docker.sh check-image")
        fit = workflow.index('quartus_docker.sh build "$ARTIFACT_DIR"')
        self.assertLess(toolchain, regression)
        self.assertLess(regression, image)
        self.assertLess(image, fit)

    def test_vm_fit_workflow_pins_actions_and_preserves_evidence(self) -> None:
        workflow = WORKFLOW.read_text()
        uses = [
            line.strip()
            for line in workflow.splitlines()
            if line.strip().startswith("uses:")
        ]
        self.assertEqual(
            uses,
            [
                "uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4.3.1",
                "uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2",
            ],
        )
        self.assertIn('mktemp -d "$RUNNER_TEMP/quartus-fit.XXXXXX"', workflow)
        self.assertIn('mktemp -d "$RUNNER_TEMP/quartus-evidence.XXXXXX"', workflow)
        self.assertIn('quartus_docker.sh check-image', workflow)
        self.assertIn('quartus_docker.sh build "$ARTIFACT_DIR"', workflow)
        self.assertIn("python3 scripts/quartus_evidence.py", workflow)
        self.assertIn("always()", workflow)
        self.assertIn("id: collect", workflow)
        self.assertIn("steps.collect.outcome == 'success'", workflow)
        self.assertIn("path: ${{ env.EVIDENCE_DIR }}", workflow)
        self.assertNotIn("path: ${{ env.ARTIFACT_DIR }}", workflow)
        self.assertIn("if-no-files-found: warn", workflow)
        self.assertIn("retention-days: 14", workflow)

    def test_vm_fit_workflow_never_installs_or_distributes_quartus(self) -> None:
        workflow = WORKFLOW.read_text()
        for forbidden in (
            "QUARTUS_ACCEPT_EULA",
            "quartus_docker.sh image",
            "quartus_archive.py",
            "Quartus-lite-21.1.1.850-linux.tar",
            "docker build",
            "docker push",
        ):
            self.assertNotIn(forbidden, workflow)


if __name__ == "__main__":
    unittest.main()
