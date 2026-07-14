#!/usr/bin/env python3
"""Mutation tests for the otherwise-clean connectivity refresh audit gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import quartus_connectivity_policy as connectivity
import quartus_connectivity_refresh_gate as gate
import quartus_fit_audit as fit_audit
import quartus_fit_audit_test as fit_fixture


class RefreshGateFixture:
    def __init__(self, root: Path) -> None:
        self.source_root = root / "repo"
        self.artifacts = root / "artifacts"
        self.policy = self.source_root / connectivity.POLICY_RELATIVE
        self.allowlist = self.policy.with_suffix(".tsv")
        self.source = self.source_root / "src/fpga/ap_core.qsf"
        self.artifacts.mkdir()
        self.source.parent.mkdir(parents=True)
        self.policy.parent.mkdir(parents=True)
        self.source.write_text("set_global_assignment -name FAMILY old\n")
        baseline_source_sha256 = hashlib.sha256(self.source.read_bytes()).hexdigest()

        self.allowlist.write_text(
            "provenance\thierarchy\tport\ttype\tdetails\n"
            "fixture\tfixture:core\tdata\tOutput\tDeclared but not connected\n"
        )
        allowlist_sha256 = hashlib.sha256(self.allowlist.read_bytes()).hexdigest()
        document = {
            "allowlist": {
                "path": self.allowlist.relative_to(self.source_root).as_posix(),
                "rows": 1,
                "sha256": allowlist_sha256,
            },
            "magic": connectivity.MAGIC,
            "quartus_version": "21.1.1 Build 850 Lite Edition",
            "reviewed_inventory": {
                "allowed_rows": 1,
                "excluded_defects": [],
                "sha256": "a" * 64,
                "warning_rows": 1,
            },
            "reviewed_map_report_sha256": "b" * 64,
            "reviewed_source_commit": "c" * 40,
            "reviewed_workflow_run_id": 100,
            "source_bindings": {
                self.source.relative_to(self.source_root).as_posix(): (
                    baseline_source_sha256
                )
            },
            "warning_id": 12241,
        }
        self.policy.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
        self.source.write_text("set_global_assignment -name FAMILY reviewed\n")

        fit_fixture.Fixture(self.artifacts)
        map_report = (
            fit_fixture.map_report()
            + "Warning (12241): 1 hierarchy have connectivity warnings - "
            "see the Connectivity Checks report folder\n"
            + '; Port Connectivity Checks: "fixture:core" ;\n'
            + "+ fixture +\n"
            + "; Port ; Type ; Severity ; Details ;\n"
            + "+ fixture +\n"
            + "; data ; Output ; Warning ; Declared but not connected ;\n"
            + "+ fixture +\n"
        )
        (self.artifacts / "output_files/ap_core.map.rpt").write_text(map_report)

    def arguments(self) -> tuple[Path, Path, Path]:
        return self.artifacts, self.source_root, self.policy


class QuartusConnectivityRefreshGateTest(unittest.TestCase):
    def test_exact_source_drift_with_clean_candidate_gates_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = RefreshGateFixture(Path(temporary))
            payload = gate.audit_refresh(*fixture.arguments())
            audit = payload["quartus_audit"]
            self.assertTrue(audit["audit_pass"])
            exact = audit["connectivity_warnings"]["exact_review"]
            self.assertEqual(exact["status"], "deferred_exact_source_drift")
            self.assertEqual(
                exact["deferred_source_drift"]["status"],
                "bound_source_changed",
            )

    def test_current_or_malformed_policy_cannot_use_refresh_gate(self) -> None:
        for mutation in ("current", "malformed", "allowlist_hash"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                fixture = RefreshGateFixture(Path(temporary))
                document = json.loads(fixture.policy.read_text())
                if mutation == "current":
                    relative = fixture.source.relative_to(
                        fixture.source_root
                    ).as_posix()
                    document["source_bindings"][relative] = hashlib.sha256(
                        fixture.source.read_bytes()
                    ).hexdigest()
                elif mutation == "malformed":
                    document["magic"] = "UNREVIEWED_POLICY"
                else:
                    document["allowlist"]["sha256"] = "0" * 64
                fixture.policy.write_text(
                    json.dumps(document, indent=2, sort_keys=True) + "\n"
                )

                with self.assertRaises(
                    (
                        gate.RefreshGateError,
                        connectivity.PolicyError,
                        fit_audit.AuditError,
                    )
                ):
                    gate.audit_refresh(*fixture.arguments())

    def test_non_connectivity_candidate_failures_cannot_mint_draft(self) -> None:
        mutations = ("critical_warning", "failed_flow", "timing_report", "missing_fit")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                fixture = RefreshGateFixture(Path(temporary))
                if mutation == "critical_warning":
                    (fixture.artifacts / "quartus.log").write_text(
                        "Critical Warning: unrelated assignment failure\n"
                    )
                elif mutation == "failed_flow":
                    report = fixture.artifacts / "output_files/ap_core.flow.rpt"
                    report.write_bytes(
                        report.read_bytes().replace(b"Successful", b"Failed", 1)
                    )
                elif mutation == "timing_report":
                    report = fixture.artifacts / "output_files/ap_core.sta.rpt"
                    report.write_bytes(
                        report.read_bytes().replace(b"0.100", b"-0.100", 1)
                    )
                else:
                    (fixture.artifacts / "output_files/ap_core.fit.rpt").unlink()

                with self.assertRaises(
                    (
                        gate.RefreshGateError,
                        connectivity.PolicyError,
                        fit_audit.AuditError,
                    )
                ):
                    gate.audit_refresh(*fixture.arguments())

    def test_malformed_connectivity_report_cannot_be_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = RefreshGateFixture(Path(temporary))
            report = fixture.artifacts / "output_files/ap_core.map.rpt"
            report.write_bytes(
                report.read_bytes().replace(
                    b"Warning (12241): 1 hierarchy",
                    b"Warning (12241): 2 hierarchies",
                    1,
                )
            )
            with self.assertRaises(
                (
                    gate.RefreshGateError,
                    connectivity.PolicyError,
                    fit_audit.AuditError,
                )
            ):
                gate.audit_refresh(*fixture.arguments())


if __name__ == "__main__":
    unittest.main()
