#!/usr/bin/env python3
"""Adversarial tests for the explicit native-macOS GHDL wrapper."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "with_native_macos_ghdl.sh"
IMAGE = "ghdl/ghdl:6.0.0-llvm-ubuntu-24.04"
DIGEST_IMAGE = "ghdl/ghdl@sha256:8b3ec37c3873b2eee9387759e66c50830c15ae5b7b533badaa97ce007a0f8022"


def executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class NativeMacosGhdlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / "ghdl-bundle"
        (self.bundle / "bin").mkdir(parents=True)
        (self.bundle / "lib" / "ghdl").mkdir(parents=True)
        (self.bundle / "bin" / "libgcc_s.1.1.dylib").write_bytes(b"test-runtime")
        executable(self.bundle / "bin" / "ghdl1-llvm", "#!/bin/sh\nexit 0\n")
        executable(self.bundle / "bin" / "ghwdump", "#!/bin/sh\nexit 0\n")
        self.mount = self.root / "checkout"
        for child in ("build", "lib", "inc"):
            (self.mount / child).mkdir(parents=True)
        (self.mount / "source.vhd").write_text("entity source is end entity;\n")
        self.ghdl_log = self.root / "ghdl.log"
        self.runtime_log = self.root / "runtime.log"
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        executable(
            self.fake_bin / "uname",
            "#!/bin/sh\n"
            "case \"${1-}\" in\n"
            "  -s) echo Darwin ;;\n"
            "  -m) echo arm64 ;;\n"
            "  *) exec /usr/bin/uname \"$@\" ;;\n"
            "esac\n",
        )
        self.write_ghdl()
        executable(
            self.mount / "build" / "native_tb",
            "#!/bin/sh\n"
            "{ printf 'PWD=%s\\n' \"$PWD\"; "
            "for arg in \"$@\"; do printf 'ARG=%s\\n' \"$arg\"; done; } "
            '> "$SWAN_FAKE_RUNTIME_LOG"\n',
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_ghdl(self, version: str = "6.0.0", backend: str = "llvm") -> None:
        executable(
            self.bundle / "bin" / "ghdl",
            "#!/bin/sh\n"
            "if [ \"${1-}\" = --version ]; then\n"
            f"  echo 'GHDL {version} (6.0.0.r0.ge589c698c) [Dunoon edition]'\n"
            f"  echo '{backend} code generator'\n"
            "  exit 0\n"
            "fi\n"
            "{ printf 'PWD=%s\\n' \"$PWD\"; "
            "for arg in \"$@\"; do printf 'ARG=%s\\n' \"$arg\"; done; } "
            '> "$SWAN_FAKE_GHDL_LOG"\n'
            "if [ \"${1-}\" = synth ]; then echo 'module fake; endmodule'; fi\n",
        )

    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}:{env.get('PATH', '')}",
                "TMPDIR": str(self.tmpdir),
                "SWAN_FAKE_GHDL_LOG": str(self.ghdl_log),
                "SWAN_FAKE_RUNTIME_LOG": str(self.runtime_log),
                "SWAN_TEST_MOUNT": str(self.mount),
            }
        )
        env.pop("SWAN_GHDL", None)
        env.pop("SWAN_GHDL_BUNDLE", None)
        return env

    def run_shell(
        self, command: str, *, bundle: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        selected = bundle or self.bundle
        result = subprocess.run(
            [
                str(WRAPPER),
                "--bundle",
                str(selected),
                "--",
                "/bin/bash",
                "-c",
                command,
            ],
            cwd=ROOT,
            env=self.environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            list(self.tmpdir.glob("swan-song-native-ghdl.*")),
            [],
            "the wrapper must remove its copied driver and Docker shim",
        )
        return result

    def docker(self, tail: str, *, options: str | None = None) -> str:
        opts = options or (
            '--rm --platform linux/amd64 -v "$SWAN_TEST_MOUNT:/work" '
            "-w /work/build"
        )
        return f"docker run {opts} {IMAGE} {tail}"

    def assert_rejected(self, command: str, message: str) -> None:
        result = self.run_shell(command)
        self.assertEqual(result.returncode, 125, result)
        self.assertIn(message, result.stderr)

    def test_maps_plain_equal_and_search_path_forms_and_runs_binary(self) -> None:
        command = "\n".join(
            [
                self.docker(
                    "ghdl -a --workdir=/work/build -P/work/lib -I/work/inc /work/source.vhd"
                ),
                self.docker(
                    "./native_tb --assert-level=error",
                    options=(
                        '--rm --platform=linux/amd64 '
                        '--volume="$SWAN_TEST_MOUNT:/work" --workdir=/work/build'
                    ),
                ),
            ]
        )
        result = self.run_shell(command)
        self.assertEqual(result.returncode, 0, result)
        ghdl_log = self.ghdl_log.read_text()
        mount = self.mount.resolve()
        self.assertIn(f"PWD={mount / 'build'}", ghdl_log)
        self.assertIn(f"ARG=--workdir={mount / 'build'}", ghdl_log)
        self.assertIn(f"ARG=-P{mount / 'lib'}", ghdl_log)
        self.assertIn(f"ARG=-I{mount / 'inc'}", ghdl_log)
        self.assertIn(f"ARG={mount / 'source.vhd'}", ghdl_log)
        runtime_log = self.runtime_log.read_text()
        self.assertIn(f"PWD={mount / 'build'}", runtime_log)
        self.assertIn("ARG=--assert-level=error", runtime_log)

    def test_environment_bundle_is_an_explicit_alternative(self) -> None:
        env = self.environment()
        env["SWAN_GHDL_BUNDLE"] = str(self.bundle)
        command = self.docker("ghdl -a").replace(IMAGE, DIGEST_IMAGE)
        result = subprocess.run(
            [str(WRAPPER), "--", "/bin/bash", "-c", command],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result)
        self.assertEqual(list(self.tmpdir.glob("swan-song-native-ghdl.*")), [])

    def test_wrong_version_and_backend_fail_before_child_command(self) -> None:
        self.write_ghdl(version="5.0.1")
        result = self.run_shell("exit 99")
        self.assertEqual(result.returncode, 125)
        self.assertIn("official v6.0.0", result.stderr)
        self.write_ghdl(backend="mcode")
        result = self.run_shell("exit 99")
        self.assertEqual(result.returncode, 125)
        self.assertIn("LLVM", result.stderr)

    def test_requires_complete_official_runtime_and_apple_silicon(self) -> None:
        (self.bundle / "bin" / "ghdl1-llvm").unlink()
        result = self.run_shell("exit 99")
        self.assertEqual(result.returncode, 125)
        self.assertIn("ghdl1-llvm", result.stderr)
        executable(self.bundle / "bin" / "ghdl1-llvm", "#!/bin/sh\nexit 0\n")
        executable(
            self.fake_bin / "uname",
            "#!/bin/sh\n"
            "case \"${1-}\" in\n"
            "  -s) echo Darwin ;;\n"
            "  -m) echo x86_64 ;;\n"
            "  *) exec /usr/bin/uname \"$@\" ;;\n"
            "esac\n",
        )
        result = self.run_shell("exit 99")
        self.assertEqual(result.returncode, 125)
        self.assertIn("Apple Silicon", result.stderr)

    def test_docker_shim_cannot_be_invoked_outside_wrapper(self) -> None:
        shim = self.root / "docker"
        shim.symlink_to(WRAPPER)
        result = subprocess.run(
            [str(shim), "run"],
            cwd=ROOT,
            env=self.environment(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 125)
        self.assertIn("only run inside", result.stderr)

    def test_rejects_docker_surface_outside_exact_rtl_subset(self) -> None:
        cases = (
            ("docker pull anything", "only 'docker run'"),
            (self.docker("ghdl -a", options="--rm --privileged"), "unsupported docker option"),
            (
                self.docker(
                    "ghdl -a",
                    options=(
                        '--rm --platform linux/amd64 -e "TOP_SECRET=do-not-print" '
                        '-v "$SWAN_TEST_MOUNT:/work" -w /work/build'
                    ),
                ),
                "unsupported docker option",
            ),
            (
                self.docker(
                    "ghdl -a",
                    options='--platform linux/amd64 -v "$SWAN_TEST_MOUNT:/work" -w /work/build',
                ),
                "must include --rm",
            ),
            (
                self.docker(
                    "ghdl -a",
                    options='--rm --platform linux/arm64 -v "$SWAN_TEST_MOUNT:/work" -w /work/build',
                ),
                "linux/amd64",
            ),
            (
                self.docker(
                    "ghdl -a",
                    options=(
                        '--rm --platform linux/amd64 --platform=linux/amd64 '
                        '-v "$SWAN_TEST_MOUNT:/work" -w /work/build'
                    ),
                ),
                "duplicate platform",
            ),
        )
        for command, message in cases:
            with self.subTest(command=command):
                result = self.run_shell(command)
                self.assertEqual(result.returncode, 125, result)
                self.assertIn(message, result.stderr)
                self.assertNotIn("do-not-print", result.stderr)

    def test_rejects_image_command_mount_and_path_escapes(self) -> None:
        self.assert_rejected(
            self.docker("ghdl -a").replace(IMAGE, "ghdl/ghdl:latest"),
            "unsupported GHDL image identity",
        )
        self.assert_rejected(self.docker("sh -c true"), "unsupported container command")
        self.assert_rejected(self.docker("./../native_tb"), "single safe relative filename")
        self.assert_rejected(self.docker("ghdl -a /private/outside.vhd"), "outside the declared mounts")
        self.assert_rejected(
            self.docker(
                "ghdl -a",
                options='--rm --platform linux/amd64 -v "$SWAN_TEST_MOUNT:/work:ro" -w /work/build',
            ),
            "volume options",
        )
        self.assert_rejected(
            self.docker(
                "ghdl -a",
                options='--rm --platform linux/amd64 -v "relative:/work" -w /work/build',
            ),
            "volume host must be an absolute path",
        )
        self.assert_rejected(
            self.docker(
                "ghdl -a",
                options='--rm --platform linux/amd64 -v "$SWAN_TEST_MOUNT:/work" -w /outside',
            ),
            "workdir is outside",
        )

    def test_child_failure_is_preserved_and_temporary_copy_is_removed(self) -> None:
        result = self.run_shell("exit 37")
        self.assertEqual(result.returncode, 37)

    def test_does_not_replace_docker_ci_or_contain_download_logic(self) -> None:
        source = WRAPPER.read_text()
        for forbidden in ("curl ", "wget ", "gh release download", "docker pull"):
            self.assertNotIn(forbidden, source)
        translation = (ROOT / "sim" / "verilator" / "translate_vhdl.sh").read_text()
        self.assertIn("docker run", translation)
        workflow = (ROOT / ".github" / "workflows" / "regression.yml").read_text()
        self.assertIn("make regression", workflow)
        self.assertNotIn(WRAPPER.name, workflow)
        verify = (ROOT / ".github" / "toolchain" / "verify.sh").read_text()
        self.assertIn("docker pull", verify)
        self.assertNotIn(WRAPPER.name, verify)


if __name__ == "__main__":
    unittest.main()
