#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import build_chip32_pending_diagnostic as diagnostic


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/build_chip32_pending_diagnostic.py"
ASSEMBLY = ROOT / "src/support/chip32.asm"
ENCODED = ROOT / "src/support/chip32.bin.hex"


class Chip32PendingDiagnosticTest(unittest.TestCase):
    def payloads(self) -> tuple[dict[str, bytes], dict[str, object]]:
        return diagnostic.build_payloads(ASSEMBLY.read_bytes(), ENCODED.read_bytes())

    def test_exact_source_and_machine_delta_are_bound(self) -> None:
        payloads, manifest = self.payloads()
        release = bytes.fromhex(ENCODED.read_text(encoding="ascii"))
        image = payloads["chip32-pending.bin"]
        source = payloads["chip32-pending.asm"]

        self.assertEqual(len(image), len(release))
        self.assertEqual(
            [i for i, pair in enumerate(zip(release, image, strict=True)) if pair[0] != pair[1]],
            [84, 85],
        )
        self.assertEqual(image[84:86], bytes.fromhex("222b"))
        self.assertNotIn(diagnostic.RELEASE_SOURCE_INSTRUCTION, source)
        self.assertEqual(source.count(diagnostic.DIAGNOSTIC_SOURCE_INSTRUCTION), 1)
        self.assertEqual(source.count(diagnostic.TIMEOUT_LITERAL), 1)
        self.assertEqual(
            hashlib.sha256(source).hexdigest(),
            diagnostic.EXPECTED_DIAGNOSTIC_ASM_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(image).hexdigest(),
            diagnostic.EXPECTED_DIAGNOSTIC_IMAGE_SHA256,
        )
        self.assertTrue(manifest["invariants"]["qa_only_never_release"])
        self.assertTrue(manifest["invariants"]["timeout_preserved"])

    def test_materialize_is_private_complete_and_no_clobber(self) -> None:
        payloads, _manifest = self.payloads()
        with tempfile.TemporaryDirectory(prefix="swan-chip32-diagnostic-") as raw:
            output = Path(raw) / "diagnostic"
            self.assertEqual(diagnostic.materialize(output, payloads), output.resolve())
            self.assertEqual(
                {path.name for path in output.iterdir()},
                set(payloads),
            )
            for name, payload in payloads.items():
                self.assertEqual((output / name).read_bytes(), payload)
                self.assertEqual((output / name).stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            document = json.loads((output / "manifest.json").read_text())
            self.assertEqual(document["magic"], diagnostic.MAGIC)
            with self.assertRaisesRegex(diagnostic.DiagnosticError, "already exists"):
                diagnostic.materialize(output, payloads)

    def test_rejects_mutated_release_pair_and_ambiguous_poll(self) -> None:
        assembly = ASSEMBLY.read_bytes()
        encoded = ENCODED.read_bytes()
        with self.assertRaisesRegex(diagnostic.DiagnosticError, "does not match"):
            diagnostic.build_payloads(assembly + b"\n", encoded)
        with self.assertRaisesRegex(diagnostic.DiagnosticError, "identity mismatch"):
            diagnostic.build_payloads(assembly, encoded.replace(b"00", b"01", 1))

    def test_output_must_be_new_external_real_directory(self) -> None:
        payloads, _manifest = self.payloads()
        with self.assertRaisesRegex(diagnostic.DiagnosticError, "outside the repository"):
            diagnostic.materialize(ROOT / "diagnostic-do-not-create", payloads)
        with tempfile.TemporaryDirectory(prefix="swan-chip32-parent-") as raw:
            root = Path(raw)
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(diagnostic.DiagnosticError, "non-symlink"):
                diagnostic.materialize(linked / "diagnostic", payloads)

    def test_cli_defaults_to_read_only_plan_and_apply_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-chip32-cli-") as raw:
            output = Path(raw) / "diagnostic"
            plan = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)
            self.assertIn("Would create QA-only diagnostic directory", plan.stdout)
            self.assertFalse(output.exists())
            applied = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output), "--apply"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertTrue((output / "chip32-pending.bin").is_file())
            repeated = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output), "--apply"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("already exists", repeated.stderr)


if __name__ == "__main__":
    unittest.main()
