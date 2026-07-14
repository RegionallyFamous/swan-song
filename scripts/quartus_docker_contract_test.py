#!/usr/bin/env python3

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "scripts/quartus_docker.sh"
WORKFLOW = ROOT / ".github/workflows/quartus-fit.yml"
REGRESSION_WORKFLOW = ROOT / ".github/workflows/regression.yml"
DOCKERFILE = ROOT / "toolchains/quartus-21.1.1/Dockerfile"
CONTAINER_BUILD = ROOT / "toolchains/quartus-21.1.1/container-build-core.sh"
TOOLCHAIN_CHECK = ROOT / "toolchains/quartus-21.1.1/toolchain-check.sh"
VERIFY_TCL = ROOT / "toolchains/quartus-21.1.1/verify-toolchain.tcl"


class QuartusDockerContractTest(unittest.TestCase):
    @staticmethod
    def run_fake_failed_image_build() -> tuple[
        subprocess.CompletedProcess[str], str, list[Path]
    ]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            contexts = root / "contexts"
            contexts.mkdir()
            build_args = root / "build-args"
            archive = root / "Quartus-lite-21.1.1.850-linux.tar"
            archive.touch()
            python3 = fake_bin / "python3"
            python3.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
[[ "${2:-}" == extract ]]
mkdir -p "${4:?}"
: > "${4}/QuartusLiteSetup-21.1.1.850-linux.run"
: > "${4}/cyclonev-21.1.1.850.qdz"
"""
            )
            python3.chmod(0o755)
            docker = fake_bin / "docker"
            docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  info) ;;
  build)
    printf '%s\n' "$@" > "${FAKE_BUILD_ARGS:?}"
    exit 37
    ;;
  *) exit 98 ;;
esac
"""
            )
            docker.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                    "TMPDIR": str(contexts),
                    "QUARTUS_ACCEPT_EULA": "1",
                    "FAKE_BUILD_ARGS": str(build_args),
                }
            )
            result = subprocess.run(
                [str(HOST), "image", str(archive)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            arguments = build_args.read_text() if build_args.exists() else ""
            leftovers = list(contexts.iterdir())
            return result, arguments, leftovers

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
        '{{.Id}}') echo sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ;;
        '{{.Os}}/{{.Architecture}}') echo linux/amd64 ;;
        '{{range .RepoDigests}}{{println .}}{{end}}') ;;
        *quartus.edition*) echo Lite ;;
        *quartus.version*) echo 21.1.1.850 ;;
        *quartus.device*) echo 5CEBA4F23C8 ;;
        *quartus.archive-sha1*) echo 789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc ;;
        *) exit 91 ;;
      esac
    fi
    ;;
  create)
    [[ " $* " == *" --entrypoint /bin/true "* ]] || exit 94
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
  rm)
    ;;
  run)
    [[ " $* " == *" --entrypoint /usr/local/bin/toolchain-check "* ]] || exit 95
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

    @staticmethod
    def run_fake_failed_fit(
        output: Path, *, reserved_collision: bool = False
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            fake_bin = Path(temporary)
            marker = fake_bin / "fit-started"
            docker = fake_bin / "docker"
            docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
entrypoint_from() {
  ENTRYPOINT=""
  local previous="" argument
  for argument in "$@"; do
    if [[ "$previous" == --entrypoint ]]; then
      ENTRYPOINT="$argument"
    fi
    previous="$argument"
  done
}
case "${1:-}" in
  info)
    ;;
  image)
    [[ "${2:-}" == inspect ]] || exit 90
    if [[ "${3:-}" == --format ]]; then
      case "${4:-}" in
        '{{.Id}}') echo sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ;;
        '{{.Os}}/{{.Architecture}}') echo linux/amd64 ;;
        '{{range .RepoDigests}}{{println .}}{{end}}')
          echo private.example/internal/quartus@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
          ;;
        *quartus.edition*) echo Lite ;;
        *quartus.version*) echo 21.1.1.850 ;;
        *quartus.device*) echo 5CEBA4F23C8 ;;
        *quartus.archive-sha1*) echo 789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc ;;
        *) exit 91 ;;
      esac
    fi
    ;;
  create)
    shift
    entrypoint_from "$@"
    [[ "$ENTRYPOINT" == /bin/true ]] || exit 92
    echo fake-container
    ;;
  cp)
    case "${2:-}" in
      *:/usr/local/bin/container-build-core) source="$FAKE_CONTAINER_BUILD" ;;
      *:/usr/local/bin/toolchain-check) source="$FAKE_TOOLCHAIN_CHECK" ;;
      *:/usr/local/share/swan-song/verify-toolchain.tcl) source="$FAKE_VERIFY_TCL" ;;
      *) exit 93 ;;
    esac
    /bin/cp "$source" "${3:-}"
    ;;
  rm)
    ;;
  run)
    shift
    entrypoint_from "$@"
    case "$ENTRYPOINT" in
      /usr/local/bin/toolchain-check)
        ;;
      /usr/bin/dpkg-query)
        printf 'bash\t5.0-6ubuntu1.2\tamd64\n'
        ;;
      /usr/local/bin/container-build-core)
        artifact_volume=""
        previous=""
        for argument in "$@"; do
          if [[ "$previous" == --volume && "$argument" == *:/artifacts:rw ]]; then
            artifact_volume="$argument"
          fi
          previous="$argument"
        done
        [[ -n "$artifact_volume" ]] || exit 96
        artifacts="${artifact_volume%:/artifacts:rw}"
        for reserved in container-packages.tsv container-provenance.json; do
          [[ ! -e "$artifacts/$reserved" && ! -L "$artifacts/$reserved" ]] || exit 97
        done
        : > "$FAKE_FIT_MARKER"
        if [[ "${FAKE_RESERVED_COLLISION:-0}" == 1 ]]; then
          printf 'forged by container\n' > "$artifacts/container-provenance.json"
        fi
        exit 42
        ;;
      *)
        exit 98
        ;;
    esac
    ;;
  *)
    exit 99
    ;;
esac
"""
            )
            docker.chmod(0o755)
            git = fake_bin / "git"
            git.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
case " $* " in
  *" diff "*) ;;
  *" rev-parse --short=12 HEAD "*) echo 0123456789ab ;;
  *) exit 89 ;;
esac
"""
            )
            git.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                    "FAKE_CONTAINER_BUILD": str(CONTAINER_BUILD),
                    "FAKE_TOOLCHAIN_CHECK": str(TOOLCHAIN_CHECK),
                    "FAKE_VERIFY_TCL": str(
                        ROOT / "toolchains/quartus-21.1.1/verify-toolchain.tcl"
                    ),
                    "FAKE_FIT_MARKER": str(marker),
                    "FAKE_RESERVED_COLLISION": "1" if reserved_collision else "0",
                }
            )
            result = subprocess.run(
                [str(HOST), "build", str(output)],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            if not marker.exists():
                raise AssertionError(
                    f"fake fit did not start: stdout={result.stdout!r} stderr={result.stderr!r}"
                )
            return result

    @staticmethod
    def workflow_preflight_script() -> str:
        workflow = WORKFLOW.read_text()
        step = workflow.index(
            "      - name: Require capable x86_64 guest and local Docker daemon"
        )
        block = workflow.index("        run: |\n", step) + len("        run: |\n")
        end = workflow.index("      - name:", block)
        return textwrap.dedent(workflow[block:end])

    @classmethod
    def run_fake_preflight(
        cls,
        *,
        endpoint: str = "unix:///var/run/docker.sock",
        docker_free_kib: int = 90000000,
        docker_context: str | None = None,
        docker_host: str | None = None,
        missing_command: str | None = None,
        lab_nonce: str | None = "a" * 32,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            runner_temp = root / "runner-temp"
            runner_temp.mkdir()
            commands = {
                "uname": """#!/bin/bash
[[ "${1:-}" == -s ]] && { echo Linux; exit; }
[[ "${1:-}" == -m ]] && { echo x86_64; exit; }
exit 1
""",
                "nproc": "#!/bin/bash\necho 8\n",
                "awk": """#!/bin/bash
if [[ "${2:-}" == /proc/meminfo ]]; then
  echo 33554432
else
  /usr/bin/awk "$@"
fi
""",
                "df": """#!/bin/bash
last="${!#}"
if [[ "$last" == "$RUNNER_TEMP" ]]; then
  free=90000000
else
  exit 1
fi
printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
printf 'fake 100000000 1 %s 1%% /fake\n' "$free"
""",
                "docker": """#!/bin/bash
case "${1:-}" in
  info)
    if [[ "${2:-}" == --format ]]; then
      case "${3:-}" in
        '{{.OSType}}') echo linux ;;
        '{{.Architecture}}') echo x86_64 ;;
        '{{.Driver}}') echo overlay2 ;;
        *) exit 1 ;;
      esac
    fi
    ;;
  image)
    [[ "${2:-}" == inspect && "${3:-}" == --format && "${4:-}" == '{{.Id}}' ]] || exit 1
    echo sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    ;;
  run)
    [[ " $* " == *" --entrypoint /bin/df "* ]] || exit 1
    printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
    printf 'overlay 100000000 1 %s 1%% /\n' "$FAKE_DOCKER_FREE_KIB"
    ;;
  context)
    case "${2:-}" in
      show) echo default ;;
      inspect) echo "$FAKE_DOCKER_ENDPOINT" ;;
      *) exit 1 ;;
    esac
    ;;
  *) exit 1 ;;
esac
""",
            }
            for name in (
                "make",
                "python3",
                "tclsh",
                "perl",
                "cmp",
                "find",
                "sed",
                "grep",
                "sha256sum",
            ):
                commands[name] = "#!/bin/bash\nexit 0\n"
            if missing_command is not None:
                commands.pop(missing_command, None)
            for name, payload in commands.items():
                command = fake_bin / name
                command.write_text(payload)
                command.chmod(0o755)
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": str(fake_bin),
                    "RUNNER_TEMP": str(runner_temp),
                    "QUARTUS_IMAGE": "swan-song-quartus:21.1.1-850-cyclonev",
                    "FAKE_DOCKER_ENDPOINT": endpoint,
                    "FAKE_DOCKER_FREE_KIB": str(docker_free_kib),
                }
            )
            if lab_nonce is not None:
                environment["SWAN_SONG_JOB_NONCE"] = lab_nonce
            else:
                environment.pop("SWAN_SONG_JOB_NONCE", None)
            environment.pop("DOCKER_HOST", None)
            environment.pop("DOCKER_CONTEXT", None)
            if docker_context is not None:
                environment["DOCKER_CONTEXT"] = docker_context
            if docker_host is not None:
                environment["DOCKER_HOST"] = docker_host
            return subprocess.run(
                ["/bin/bash", "-c", cls.workflow_preflight_script()],
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

    def test_image_build_pins_platform_args_and_cleans_context_on_failure(self) -> None:
        result, arguments, leftovers = self.run_fake_failed_image_build()
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertNotIn("unbound variable", result.stderr)
        self.assertIn("--platform\nlinux/amd64\n", arguments)
        self.assertIn("--build-arg\nTARGETOS=linux\n", arguments)
        self.assertIn("--build-arg\nTARGETARCH=amd64\n", arguments)
        self.assertEqual(leftovers, [])

    def test_runtime_is_offline_and_source_is_read_only(self) -> None:
        host = HOST.read_text()
        self.assertIn("--platform linux/amd64", host)
        self.assertIn("--network none", host)
        self.assertIn('"$ROOT:/source:ro"', host)
        self.assertIn('"$output:/artifacts:rw"', host)

    def test_all_image_commands_force_reviewed_entrypoints(self) -> None:
        host = HOST.read_text()
        for entrypoint in (
            "/usr/bin/uname",
            "/bin/true",
            "/usr/local/bin/toolchain-check",
            "/usr/bin/dpkg-query",
            "/usr/local/bin/container-build-core",
        ):
            self.assertIn(f"--entrypoint {entrypoint}", host)
        result = self.run_fake_image_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fit_resolves_and_runs_an_immutable_image_id(self) -> None:
        host = HOST.read_text()
        self.assertIn("docker image inspect --format '{{.Id}}' \"$IMAGE\"", host)
        self.assertIn("^sha256:[0-9a-f]{64}$", host)
        self.assertIn('inspect_image "$image_id"', host)
        self.assertIn('verify_container_toolchain_payload "$image_id"', host)
        self.assertIn("--entrypoint /usr/local/bin/toolchain-check", host)
        fit_run = host.rindex('/usr/local/bin/container-build-core')
        self.assertIn('"$image_id"', host[fit_run : fit_run + 120])

    def test_fit_records_bounded_container_and_package_provenance(self) -> None:
        host = HOST.read_text()
        container = CONTAINER_BUILD.read_text()
        self.assertIn("container-packages.tsv", host)
        self.assertIn("--entrypoint /usr/bin/dpkg-query", host)
        self.assertIn('"$image_id" -W', host)
        self.assertIn("container-provenance.json", host)
        self.assertIn("quartus_container_provenance.py", host)
        self.assertIn("--repo-digests", host)
        self.assertIn("LC_ALL=C sort -u", host)
        self.assertIn('artifact directory must be empty', container)
        self.assertNotIn("container-packages.tsv", container)
        self.assertNotIn("container-provenance.json", container)
        self.assertIn('merge_container_evidence "$provenance_root" "$output"', host)

    def test_failed_fit_cannot_see_or_mutate_host_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifacts"
            output.mkdir()
            result = self.run_fake_failed_fit(output)
            self.assertEqual(result.returncode, 42, result.stderr)
            packages = output / "container-packages.tsv"
            provenance = output / "container-provenance.json"
            self.assertEqual(packages.read_text(), "bash\t5.0-6ubuntu1.2\tamd64\n")
            self.assertTrue(provenance.is_file())
            self.assertNotIn("private.example", provenance.read_text())

    def test_container_reserved_provenance_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifacts"
            output.mkdir()
            result = self.run_fake_failed_fit(output, reserved_collision=True)
            self.assertNotEqual(result.returncode, 42)
            self.assertIn("container created reserved provenance path", result.stderr)
            self.assertEqual(
                (output / "container-provenance.json").read_text(),
                "forged by container\n",
            )
            self.assertFalse((output / "container-packages.tsv").exists())

    def test_host_returns_container_artifacts_to_runner_ownership(self) -> None:
        host = HOST.read_text()
        container = CONTAINER_BUILD.read_text()
        self.assertIn('[[ -O "$ROOT" ]]', host)
        self.assertIn('--env "ARTIFACT_UID=$(id -u)"', host)
        self.assertIn('--env "SUDO_UID=$(id -u)"', host)
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

    def test_device_family_gate_normalizes_one_element_quartus_list(self) -> None:
        verify = VERIFY_TCL.read_text()
        accepted = subprocess.run(
            ["tclsh"],
            input=(
                'proc get_part_info {flag part} { return [list "Cyclone V"] }\n'
                + verify
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("5CEBA4F23C8 -> Cyclone V", accepted.stdout)

        scalar = subprocess.run(
            ["tclsh"],
            input=(
                'proc get_part_info {flag part} { return "Cyclone V" }\n'
                + verify
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(scalar.returncode, 0, scalar.stderr)
        self.assertIn("5CEBA4F23C8 -> Cyclone V", scalar.stdout)

        rejected = subprocess.run(
            ["tclsh"],
            input=(
                'proc get_part_info {flag part} { return [list "Cyclone 10"] }\n'
                + verify
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(rejected.returncode, 70)
        self.assertIn("unexpected family: Cyclone 10", rejected.stderr)

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
        for runner_label in (
            "- self-hosted",
            "- linux",
            "- x64",
            "- swan-song-quartus-21-1-1",
            '- "swan-song-job-${{ inputs.lab_nonce }}"',
        ):
            self.assertIn(runner_label, workflow)
        lab_nonce = workflow.index("      lab_nonce:")
        lab_nonce_end = workflow.index("\npermissions:", lab_nonce)
        lab_nonce_input = workflow[lab_nonce:lab_nonce_end]
        self.assertIn("required: true", lab_nonce_input)
        self.assertNotIn("default:", lab_nonce_input)
        self.assertIn("inputs.lab_nonce != ''", workflow)
        self.assertIn("SWAN_SONG_JOB_NONCE: ${{ inputs.lab_nonce }}", workflow)
        self.assertIn(
            '[[ ! "$SWAN_SONG_JOB_NONCE" =~ ^[0-9a-f]{32}$ ]]',
            workflow,
        )
        self.assertIn("default: candidate", workflow)
        self.assertIn("- connectivity-refresh", workflow)
        self.assertIn(
            "environment: ${{ inputs.profile == 'candidate' && "
            "'quartus-fit' || 'quartus-connectivity-refresh' }}",
            workflow,
        )
        self.assertIn("persist-credentials: false", workflow)

    def test_connectivity_refresh_profile_is_exactly_guarded(self) -> None:
        workflow = WORKFLOW.read_text()
        for guard in (
            "github.repository == 'RegionallyFamous/swan-song'",
            "github.event_name == 'workflow_dispatch'",
            "github.ref_type == 'branch'",
            "github.workflow_sha == github.sha",
            "github.actor_id == '158918'",
            "github.triggering_actor == 'nickhamze'",
        ):
            self.assertIn(guard, workflow)
        self.assertIn("inputs.profile == 'candidate'", workflow)
        self.assertIn("inputs.connectivity_refresh_sha == ''", workflow)
        self.assertIn(
            "github.ref == format('refs/heads/{0}', "
            "github.event.repository.default_branch)",
            workflow,
        )
        self.assertIn("inputs.profile == 'connectivity-refresh'", workflow)
        self.assertIn(
            "startsWith(github.ref, "
            "'refs/heads/codex/connectivity-refresh-')",
            workflow,
        )
        self.assertIn(
            "github.sha == inputs.connectivity_refresh_sha",
            workflow,
        )
        hosted_step = workflow.index(
            "- name: Verify exact-commit hosted regression success"
        )
        hosted_body = workflow[hosted_step : workflow.index("      - name:", hosted_step + 8)]
        self.assertIn("if: ${{ inputs.profile == 'candidate' }}", hosted_body)
        self.assertIn('--profile "${{ inputs.profile }}"', workflow)

        fit_start = workflow.index("      - name: Fit and audit exact commit")
        fit_end = workflow.index("      - name:", fit_start + 8)
        fit_body = workflow[fit_start:fit_end]
        self.assertIn("id: fit", fit_body)
        self.assertIn(
            "continue-on-error: ${{ inputs.profile == 'connectivity-refresh' }}",
            fit_body,
        )
        self.assertEqual(workflow.count("continue-on-error:"), 1)

        audit_start = workflow.index(
            "      - name: Audit refresh build except exact connectivity policy drift"
        )
        audit_end = workflow.index("      - name:", audit_start + 8)
        refresh_audit = workflow[audit_start:audit_end]
        for required in (
            "scripts/quartus_connectivity_refresh_gate.py",
            '--artifacts "$ARTIFACT_DIR"',
            '--source-root "$GITHUB_WORKSPACE"',
            "toolchains/quartus-21.1.1/connectivity-warning-12241.json",
        ):
            self.assertIn(required, refresh_audit)

        draft_start = workflow.index(
            "      - name: Prepare connectivity policy refresh drafts"
        )
        draft_end = workflow.index("      - name:", draft_start + 8)
        draft = workflow[draft_start:draft_end]
        for required in (
            "steps.collect.outcome == 'success'",
            "steps.refresh_audit.outcome == 'success'",
            "build-metadata.txt",
            "output_files/ap_core.map.rpt",
            'grep -Fx "source_commit=$GITHUB_SHA"',
            'baseline_sha256="$(sha256sum "$baseline"',
            'map_sha256="$(sha256sum "$map_report"',
            "scripts/quartus_connectivity_policy_refresh.py",
            '--reviewed-source-commit "$GITHUB_SHA"',
            '--reviewed-workflow-run-id "$GITHUB_RUN_ID"',
            '--reviewed-map-report-sha256 "$map_sha256"',
            'connectivity-warning-12241.draft.json',
            'connectivity-warning-12241.draft.tsv',
        ):
            self.assertIn(required, draft)
        self.assertNotIn("--output-summary", draft)

        bundle_start = workflow.index(
            "      - name: Validate exact bounded connectivity refresh bundle"
        )
        bundle_end = workflow.index("      - name:", bundle_start + 8)
        bundle = workflow[bundle_start:bundle_end]
        self.assertIn("steps.refresh_draft.outcome == 'success'", bundle)
        self.assertIn("--validate-connectivity-refresh-bundle", bundle)
        self.assertIn('"$EVIDENCE_DIR"', bundle)

        upload_start = workflow.index(
            "      - name: Preserve bounded Quartus evidence"
        )
        upload = workflow[upload_start:]
        self.assertIn("steps.refresh_bundle.outcome == 'success'", upload)
        self.assertIn("path: ${{ env.EVIDENCE_DIR }}", upload)
        self.assertNotIn("path: ${{ env.ARTIFACT_DIR }}", upload)
        self.assertIn(
            "name: quartus-${{ inputs.profile == 'candidate' && 'fit' || "
            "'connectivity-refresh' }}-${{ github.sha }}-${{ github.run_attempt }}",
            upload,
        )

        evidence_source = (ROOT / "scripts/quartus_evidence.py").read_text()
        refresh_start = evidence_source.index(
            "CONNECTIVITY_REFRESH_EVIDENCE_FILES = ("
        )
        refresh_end = evidence_source.index("\n)\n", refresh_start)
        refresh_allowlist = evidence_source[refresh_start:refresh_end]
        self.assertIn("output_files/ap_core.map.rpt", refresh_allowlist)
        for forbidden in (
            "quartus.log",
            "ap_core.rbf",
            "ap_core.fit.rpt",
            "ap_core.sta.rpt",
            "build_id.mif",
        ):
            self.assertNotIn(forbidden, refresh_allowlist)

    def test_vm_fit_workflow_checks_x86_guest_before_checkout(self) -> None:
        workflow = WORKFLOW.read_text()
        host_check = workflow.index('operating_system="$(uname -s)"')
        self.assertIn('architecture="$(uname -m)"', workflow)
        self.assertIn('[[ "$operating_system" != Linux ]]', workflow)
        self.assertIn('[[ "$architecture" != x86_64 ]]', workflow)
        self.assertLess(host_check, workflow.index("uses: actions/checkout@"))

    def test_vm_fit_workflow_fails_fast_on_capacity_and_docker(self) -> None:
        workflow = WORKFLOW.read_text()
        checkout = workflow.index("uses: actions/checkout@")
        for contract in (
            "minimum_cpus=8",
            "minimum_memory_kib=$((30 * 1024 * 1024))",
            "minimum_free_disk_kib=$((80 * 1024 * 1024))",
            "for command in docker nproc awk df make python3 tclsh perl cmp find sed grep sha256sum",
            "docker info >/dev/null",
            "docker info --format '{{.OSType}}'",
            "docker info --format '{{.Architecture}}'",
            "docker info --format '{{.Driver}}'",
            "docker context inspect",
            '"$docker_endpoint" != unix:///*',
            "docker image inspect --format '{{.Id}}'",
            "--entrypoint /bin/df",
        ):
            self.assertIn(contract, workflow)
            self.assertLess(workflow.index(contract), checkout)

    def test_vm_fit_preflight_executes_local_endpoint_and_storage_contracts(self) -> None:
        accepted = self.run_fake_preflight()
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("container-layer free (overlay2, sha256:", accepted.stdout)

        for nonce in (None, "", "A" * 32, "a" * 31, "a" * 33):
            with self.subTest(lab_nonce=nonce):
                rejected = self.run_fake_preflight(lab_nonce=nonce)
                self.assertNotEqual(rejected.returncode, 0)

        remote = self.run_fake_preflight(endpoint="tcp://builder.example:2376")
        self.assertNotEqual(remote.returncode, 0)
        self.assertIn("local Unix-socket endpoint", remote.stderr)

        context_overrides_host = self.run_fake_preflight(
            endpoint="tcp://builder.example:2376",
            docker_context="remote-builder",
            docker_host="unix:///var/run/docker.sock",
        )
        self.assertNotEqual(context_overrides_host.returncode, 0)
        self.assertIn("local Unix-socket endpoint", context_overrides_host.stderr)

        starved = self.run_fake_preflight(docker_free_kib=1024)
        self.assertNotEqual(starved.returncode, 0)
        self.assertIn("at least 80 GiB free for the Docker container layer", starved.stderr)

        for command in (
            "make",
            "python3",
            "tclsh",
            "perl",
            "cmp",
            "find",
            "sed",
            "grep",
            "sha256sum",
        ):
            with self.subTest(missing_command=command):
                missing = self.run_fake_preflight(missing_command=command)
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn(f"missing required command: {command}", missing.stderr)

    def test_vm_fit_workflow_proves_exact_hosted_regression_before_quartus(self) -> None:
        workflow = WORKFLOW.read_text()
        regression_proof = workflow.index("scripts/verify_hosted_regression.py")
        image = workflow.index("quartus_docker.sh check-image")
        fit = workflow.index('quartus_docker.sh build "$ARTIFACT_DIR"')
        self.assertIn("  actions: read\n", workflow)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", workflow)
        self.assertIn('--repository "$GITHUB_REPOSITORY"', workflow)
        self.assertIn('--sha "$GITHUB_SHA"', workflow)
        self.assertIn('--branch "$GITHUB_REF_NAME"', workflow)
        self.assertNotIn("run: make regression", workflow)
        self.assertNotIn(".github/toolchain/verify.sh", workflow)
        self.assertLess(regression_proof, image)
        self.assertLess(image, fit)

    def test_container_build_rejects_quartus_log_write_failure(self) -> None:
        script = CONTAINER_BUILD.read_text()
        capture = 'pipeline_status=("${PIPESTATUS[@]}")'
        self.assertIn(capture, script)
        self.assertIn("build_status=${pipeline_status[0]}", script)
        self.assertIn("log_status=${pipeline_status[1]}", script)
        self.assertIn("could not write the complete Quartus log", script)
        self.assertIn('exit "$build_status"', script)
        self.assertIn(
            "for required in ap_core.rbf ap_core.map.rpt ap_core.fit.rpt "
            "ap_core.asm.rpt ap_core.sta.rpt ap_core.flow.rpt; do",
            script,
        )
        self.assertLess(
            script.index(capture), script.index("set -e", script.index(capture))
        )

    def test_container_build_snapshots_both_pipeline_statuses_atomically(self) -> None:
        script = CONTAINER_BUILD.read_text()
        start = script.index("set +e\n", script.index("/usr/local/bin/toolchain-check"))
        end = script.index("\noutput_dir=", start)
        fragment = script[start:end]
        fragment = fragment.replace(
            './scripts/build_core.sh 2>&1 | tee "$artifact_root/quartus.log"',
            'bash -c "exit 37" 2>&1 | tee "$artifact_root/quartus.log"',
        )
        self.assertNotIn("./scripts/build_core.sh", fragment)
        decision_start = script.index("if (( log_status != 0 ));", end)
        decision_end = script.index("\nfor required", decision_start)
        decision = script[decision_start:decision_end]

        with tempfile.TemporaryDirectory() as temporary_string:
            temporary = Path(temporary_string)
            command = (
                "set -uo pipefail\n"
                'artifact_root="$1"\n'
                + fragment
                + '\nprintf "%s %s\\n" "$build_status" "$log_status"\n'
            )
            successful_log = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "pipeline-status-probe",
                    str(temporary),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_tee = fake_bin / "tee"
            fake_tee.write_text(
                "#!/usr/bin/env bash\n"
                "cat >/dev/null\n"
                "exit 23\n"
            )
            fake_tee.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            failed_log = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "pipeline-status-probe",
                    str(temporary),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            quartus_exit = subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -uo pipefail\n"
                    'artifact_root="$1"\n'
                    + fragment
                    + "\n"
                    + decision,
                    "pipeline-status-probe",
                    str(temporary),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            log_exit = subprocess.run(
                [
                    "bash",
                    "-c",
                    "set -uo pipefail\n"
                    'artifact_root="$1"\n'
                    + fragment
                    + "\n"
                    + decision,
                    "pipeline-status-probe",
                    str(temporary),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

        self.assertEqual(successful_log.returncode, 0, successful_log.stderr)
        self.assertEqual(successful_log.stdout, "37 0\n")
        self.assertEqual(failed_log.returncode, 0, failed_log.stderr)
        self.assertEqual(failed_log.stdout, "37 23\n")
        self.assertEqual(quartus_exit.returncode, 37, quartus_exit.stderr)
        self.assertIn("Quartus compile failed with status 37", quartus_exit.stderr)
        self.assertEqual(log_exit.returncode, 83, log_exit.stderr)
        self.assertIn("tee status 23", log_exit.stderr)

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
                "uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0",
                "uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1",
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

    def test_regression_workflow_pins_node24_checkout(self) -> None:
        workflow = REGRESSION_WORKFLOW.read_text()
        uses = [
            line.strip()
            for line in workflow.splitlines()
            if line.strip().startswith("uses:")
        ]
        self.assertEqual(
            uses,
            [
                "uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0"
            ],
        )
        self.assertIn("jobs:\n  verilator:\n    runs-on: ubuntu-24.04\n", workflow)
        self.assertEqual(workflow.count("    timeout-minutes: 30\n"), 1)
        self.assertNotIn("    if:", workflow)
        toolchain = workflow.index(".github/toolchain/verify.sh")
        regression_command = workflow.index("run: make regression")
        self.assertLess(toolchain, regression_command)
        for step_name in (
            "Check out source",
            "Verify immutable HDL toolchain",
            "Run open-ROM framebuffer regressions",
        ):
            self.assertEqual(workflow.count(f"- name: {step_name}"), 1)
        regression = (ROOT / "scripts/regression.sh").read_text()
        self.assertIn('python3 "$ROOT/scripts/verify_hosted_regression_test.py"', regression)

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
