#!/usr/bin/env python3
"""Synthetic, offline tests for the private WonderSwan corpus runner."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import textwrap
import unittest

import run_private_corpus as corpus


def synthetic_rom(*, color: bool, marker: int = 0x41, valid_checksum: bool = True) -> bytes:
    image = bytearray(64 * 1024)
    image[0x100] = marker
    footer = len(image) - 16
    image[footer + 0] = 0xEA
    image[footer + 5] = 0x00
    image[footer + 7] = int(color)
    image[footer + 10] = 0x00
    image[footer + 11] = 0x00
    image[footer + 12] = 0x04
    image[footer + 13] = 0x00
    checksum = sum(image[:-2]) & 0xFFFF
    image[-2:] = checksum.to_bytes(2, "little")
    if not valid_checksum:
        image[0x100] ^= 1
    return bytes(image)


class PrivateCorpusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-private-corpus-test-")
        self.base = Path(self.temporary.name)
        self.lab_root = self.base / "Private Lab With Spaces"
        self.lab, _warnings = corpus.initialize_lab(self.lab_root)
        (self.lab.bios / "bw.rom").write_bytes(bytes([0xB0]) * 4096)
        (self.lab.bios / "color.rom").write_bytes(bytes([0xC0]) * 8192)
        (self.lab.bios / "bw.rom").chmod(0o600)
        (self.lab.bios / "color.rom").chmod(0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_rom(self, name: str, data: bytes) -> Path:
        path = self.lab.roms / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def mock_simulator(self, mode: str = "deterministic") -> Path:
        path = self.base / f"mock-{mode}.py"
        source = f"""\
            #!{sys.executable}
            import pathlib
            import sys
            import time

            def value(name):
                index = sys.argv.index(name)
                return sys.argv[index + 1]

            rom = pathlib.Path(value("--rom")).read_bytes()
            bios = pathlib.Path(value("--bios")).read_bytes()
            frames = int(value("--frames"))
            int(value("--max-cycles"))
            output = pathlib.Path(value("--out"))
            expected_bios = 8192 if rom[-9] == 1 else 4096
            if len(bios) != expected_bios:
                raise SystemExit(21)
            counter_path = pathlib.Path(__file__).with_suffix(".count")
            count = int(counter_path.read_text()) + 1 if counter_path.exists() else 1
            counter_path.write_text(str(count))
            mode = {mode!r}
            if mode == "timeout":
                time.sleep(2)
            if mode == "exit":
                raise SystemExit(22)
            output.mkdir(parents=True, exist_ok=True)
            written = frames - 1 if mode == "missing-frame" else frames
            seed = count if mode == "nondeterministic" else rom[0x100]
            for index in range(written):
                (output / f"frame-{{index}}.rgb").write_bytes(
                    bytes([(seed + index) & 0xff]) * {corpus.FRAME_SIZE}
                )
        """
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        path.chmod(0o700)
        return path

    def invoke(self, arguments: list[str]) -> tuple[int, dict, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status_code = corpus.main(arguments)
        output = stdout.getvalue()
        return status_code, json.loads(output), output, stderr.getvalue()

    def run_arguments(self, simulator: Path, *extra: str) -> list[str]:
        return [
            "run",
            "--lab-root",
            str(self.lab_root),
            "--simulator",
            str(simulator),
            "--workers",
            "2",
            "--frames",
            "2",
            "--max-cycles",
            "1000",
            "--wall-timeout",
            "1",
            *extra,
        ]

    def test_inventory_creates_private_state_and_exposes_only_opaque_identity(self) -> None:
        title = "Extremely Secret Title.wsc"
        rom = synthetic_rom(color=True)
        self.write_rom(title, rom)

        status_code, document, output, _stderr = self.invoke(
            ["inventory", "--lab-root", str(self.lab_root)]
        )

        self.assertEqual(status_code, 0)
        self.assertTrue(document["bios_ready"])
        self.assertEqual(document["counts"]["valid_unique_cases"], 1)
        self.assertEqual(document["model_counts"], {"mono": 0, "color": 1})
        self.assertRegex(document["cases"][0]["case_id"], r"^rom-[0-9a-f]{64}$")
        self.assertNotIn(title, output)
        self.assertNotIn(str(self.lab_root), output)
        self.assertNotIn(hashlib.sha256(rom).hexdigest(), output)
        self.assertEqual(stat.S_IMODE(self.lab.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.lab.private.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.lab.key.stat().st_mode), 0o600)
        report_mode = (self.lab.reports / "corpus-inventory.json").stat().st_mode
        self.assertEqual(stat.S_IMODE(report_mode), 0o600)

    def test_color_footer_selects_color_bios_even_with_ws_extension(self) -> None:
        self.write_rom("Misleading Mono Extension.ws", synthetic_rom(color=True))
        simulator = self.mock_simulator()

        status_code, document, output, _stderr = self.invoke(
            self.run_arguments(simulator)
        )

        self.assertEqual(status_code, 0)
        self.assertEqual(document["counts"]["passed"], 1)
        self.assertNotIn("Misleading Mono Extension", output)
        self.assertNotIn(str(self.lab_root), output)

    def test_repeat_is_deterministic_and_second_invocation_resumes(self) -> None:
        rom = synthetic_rom(color=False, marker=0x52)
        self.write_rom("Private Mono.ws", rom)
        simulator = self.mock_simulator()
        arguments = self.run_arguments(simulator, "--repeat")

        first_status, first, first_output, _stderr = self.invoke(arguments)
        second_status, second, second_output, _stderr = self.invoke(arguments)

        self.assertEqual(first_status, 0)
        self.assertEqual(second_status, 0)
        self.assertEqual((simulator.with_suffix(".count")).read_text(), "2")
        self.assertTrue(first["cases"][0]["deterministic_pair"])
        self.assertFalse(first["cases"][0]["resumed"])
        self.assertTrue(second["cases"][0]["resumed"])
        self.assertRegex(first["cases"][0]["frame_chain_hmac"], r"^[0-9a-f]{64}$")
        for output in (first_output, second_output):
            self.assertNotIn("Private Mono", output)
            self.assertNotIn(str(self.lab_root), output)
            self.assertNotIn(hashlib.sha256(rom).hexdigest(), output)

    def test_nondeterministic_repeat_fails_closed(self) -> None:
        self.write_rom("Nondeterministic.wsc", synthetic_rom(color=True))
        simulator = self.mock_simulator("nondeterministic")

        status_code, document, _output, _stderr = self.invoke(
            self.run_arguments(simulator, "--repeat")
        )

        self.assertEqual(status_code, 1)
        self.assertEqual(document["counts"], {
            "duplicates_not_rerun": 0,
            "failed": 1,
            "ignored_filesystem_metadata": 0,
            "passed": 0,
            "permission_warnings": 0,
        })
        self.assertEqual(document["cases"][0]["reason"], "frame_output_nondeterministic")
        self.assertFalse(document["cases"][0]["deterministic_pair"])
        self.assertIsNone(document["cases"][0]["frame_chain_hmac"])

    def test_timeout_and_invalid_frame_set_fail_without_logs(self) -> None:
        self.write_rom("Timeout.ws", synthetic_rom(color=False))
        timeout_simulator = self.mock_simulator("timeout")
        status_code, timed_out, output, _stderr = self.invoke(
            [
                *self.run_arguments(timeout_simulator),
                "--wall-timeout",
                "0.1",
            ]
        )
        self.assertEqual(status_code, 1)
        self.assertEqual(timed_out["cases"][0]["reason"], "simulator_timeout")
        self.assertNotIn("Traceback", output)

        second_lab = self.base / "Second Private Lab"
        second_paths, _warnings = corpus.initialize_lab(second_lab)
        (second_paths.bios / "bw.rom").write_bytes(bytes(4096))
        (second_paths.bios / "color.rom").write_bytes(bytes(8192))
        (second_paths.bios / "bw.rom").chmod(0o600)
        (second_paths.bios / "color.rom").chmod(0o600)
        rom_path = second_paths.roms / "Missing Frame.wsc"
        rom_path.write_bytes(synthetic_rom(color=True))
        rom_path.chmod(0o600)
        missing_simulator = self.mock_simulator("missing-frame")
        status_code, missing, output, _stderr = self.invoke(
            [
                "run",
                "--lab-root",
                str(second_lab),
                "--simulator",
                str(missing_simulator),
                "--frames",
                "2",
            ]
        )
        self.assertEqual(status_code, 1)
        self.assertEqual(missing["cases"][0]["reason"], "frame_output_set_invalid")
        self.assertNotIn("Missing Frame", output)

    def test_archive_symlink_and_bad_checksum_are_rejected_without_paths(self) -> None:
        archive_name = "Secret Collection.zip"
        bad_name = "Bad Dump.ws"
        symlink_name = "Alias.wsc"
        (self.lab.roms / archive_name).write_bytes(b"not an accepted archive")
        bad = synthetic_rom(color=False, valid_checksum=False)
        self.write_rom(bad_name, bad)
        os.symlink(self.lab.roms / bad_name, self.lab.roms / symlink_name)

        status_code, document, output, _stderr = self.invoke(
            ["inventory", "--lab-root", str(self.lab_root)]
        )

        self.assertEqual(status_code, 1)
        self.assertEqual(document["counts"]["valid_unique_cases"], 0)
        self.assertEqual(document["counts"]["rejected"], 3)
        reasons = {item["reason"] for item in document["cases"]}
        self.assertEqual(
            reasons,
            {
                "rom_extension_unsupported",
                "rom_footer_checksum_invalid",
                "rom_symlink_forbidden",
            },
        )
        for secret in (archive_name, bad_name, symlink_name, str(self.lab_root)):
            self.assertNotIn(secret, output)
        self.assertNotIn(hashlib.sha256(bad).hexdigest(), output)

    def test_finder_metadata_and_appledouble_subtrees_are_ignored(self) -> None:
        self.write_rom("Actual Game.ws", synthetic_rom(color=False))
        (self.lab.roms / ".DS_Store").write_bytes(b"Finder metadata")
        (self.lab.roms / "._Actual Game.ws").write_bytes(b"AppleDouble metadata")
        nested = self.lab.roms / "nested"
        nested.mkdir(mode=0o700)
        (nested / ".DS_Store").write_bytes(b"nested Finder metadata")
        ignored_subtree = self.lab.roms / "._metadata-subtree"
        ignored_subtree.mkdir(mode=0o700)
        (ignored_subtree / "would-otherwise-fail.zip").write_bytes(b"ignored metadata")
        (ignored_subtree / "malformed.ws").write_bytes(b"ignored metadata")

        status_code, inventory, output, _stderr = self.invoke(
            ["inventory", "--lab-root", str(self.lab_root)]
        )

        self.assertEqual(status_code, 0)
        self.assertEqual(inventory["counts"]["files_seen"], 1)
        self.assertEqual(inventory["counts"]["valid_unique_cases"], 1)
        self.assertEqual(inventory["counts"]["rejected"], 0)
        self.assertEqual(inventory["counts"]["ignored_filesystem_metadata"], 4)
        for secret in (
            ".DS_Store",
            "._Actual Game.ws",
            "._metadata-subtree",
            "would-otherwise-fail.zip",
        ):
            self.assertNotIn(secret, output)

        simulator = self.mock_simulator()
        run_status, summary, run_output, _stderr = self.invoke(
            self.run_arguments(simulator)
        )
        self.assertEqual(run_status, 0)
        self.assertEqual(summary["counts"]["passed"], 1)
        self.assertEqual(summary["counts"]["ignored_filesystem_metadata"], 4)
        self.assertNotIn(".DS_Store", run_output)

    def test_duplicate_content_runs_once_and_dry_run_does_not_require_simulator(self) -> None:
        rom = synthetic_rom(color=False)
        self.write_rom("Copy A.ws", rom)
        self.write_rom("Copy B.WS", rom)

        dry_status, inventory, _output, _stderr = self.invoke(
            [
                "run",
                "--lab-root",
                str(self.lab_root),
                "--simulator",
                str(self.base / "does-not-exist"),
                "--dry-run",
            ]
        )
        self.assertEqual(dry_status, 0)
        self.assertEqual(inventory["counts"]["duplicates"], 1)

        simulator = self.mock_simulator()
        run_status, summary, _output, _stderr = self.invoke(
            self.run_arguments(simulator)
        )
        self.assertEqual(run_status, 0)
        self.assertEqual(summary["counts"]["duplicates_not_rerun"], 1)
        self.assertEqual((simulator.with_suffix(".count")).read_text(), "1")

    def test_broad_existing_modes_warn_but_are_not_silently_changed(self) -> None:
        self.write_rom("Mode Warning.ws", synthetic_rom(color=False))
        self.lab.roms.chmod(0o755)
        status_code, document, output, stderr = self.invoke(
            ["inventory", "--lab-root", str(self.lab_root)]
        )
        self.assertEqual(status_code, 0)
        self.assertGreater(document["counts"]["permission_warnings"], 0)
        self.assertIn("permit group/other access", stderr)
        self.assertNotIn(str(self.lab_root), stderr)
        self.assertNotIn(str(self.lab_root), output)
        self.assertEqual(stat.S_IMODE(self.lab.roms.stat().st_mode), 0o755)

    def test_malformed_resume_certificate_is_not_overwritten_or_accepted(self) -> None:
        rom_path = self.write_rom("Resume Guard.ws", synthetic_rom(color=False))
        key, _warning = corpus.load_or_create_key(self.lab.key)
        case, _data = corpus.inspect_rom(rom_path, key)
        result_path = self.lab.results / f"{case.case_id}.json"
        result_path.write_text("not json", encoding="utf-8")
        simulator = self.mock_simulator()

        status_code, document, _output, _stderr = self.invoke(
            self.run_arguments(simulator)
        )

        self.assertEqual(status_code, 1)
        self.assertEqual(document["cases"][0]["reason"], "resume_invalid")
        self.assertEqual(result_path.read_text(encoding="utf-8"), "not json")
        self.assertFalse(simulator.with_suffix(".count").exists())

    def test_tampered_pass_resume_cannot_inject_text_into_summary(self) -> None:
        self.write_rom("Resume Injection Guard.ws", synthetic_rom(color=False))
        simulator = self.mock_simulator()
        arguments = self.run_arguments(simulator)
        first_status, first, _output, _stderr = self.invoke(arguments)
        self.assertEqual(first_status, 0)
        case_id = first["cases"][0]["case_id"]
        result_path = self.lab.results / f"{case_id}.json"
        document = json.loads(result_path.read_text(encoding="utf-8"))
        document["frame_chain_hmac"] = "PRIVATE TITLE AND PATH"
        result_path.write_text(json.dumps(document), encoding="utf-8")

        status_code, summary, output, _stderr = self.invoke(arguments)

        self.assertEqual(status_code, 1)
        self.assertEqual(summary["cases"][0]["reason"], "resume_invalid")
        self.assertNotIn("PRIVATE TITLE AND PATH", output)
        self.assertEqual((simulator.with_suffix(".count")).read_text(), "1")

    def test_custom_lab_root_inside_repository_is_rejected_before_creation(self) -> None:
        forbidden = corpus.ROOT / "private-corpus-must-not-exist"
        self.assertFalse(forbidden.exists())
        status_code, _document, output, stderr = self.invoke_no_json(
            ["inventory", "--lab-root", str(forbidden)]
        )
        self.assertEqual(status_code, 2)
        self.assertEqual(output, "")
        self.assertIn("lab_root_inside_repository", stderr)
        self.assertFalse(forbidden.exists())

    def invoke_no_json(self, arguments: list[str]) -> tuple[int, None, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status_code = corpus.main(arguments)
        return status_code, None, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
