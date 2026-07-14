#!/usr/bin/env python3
"""Mutation tests for the exact Quartus connectivity-warning policy."""

from __future__ import annotations

import csv
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import quartus_connectivity_policy as policy
from quartus_connectivity_policy_refresh_test import (  # noqa: F401
    ConnectivityPolicyRefreshTest,
    ConnectivitySourceClosureSchemaTest,
)
from quartus_connectivity_source_closure_test import (  # noqa: F401
    QuartusConnectivitySourceClosureTest,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / policy.POLICY_RELATIVE


def allowed_items(root: Path = ROOT) -> list[dict[str, str]]:
    document = json.loads((root / policy.POLICY_RELATIVE).read_text(encoding="utf-8"))
    with (root / document["allowlist"]["path"]).open(encoding="utf-8") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def fixture_report(items: list[dict[str, str]]) -> str:
    groups: dict[str, list[dict[str, str]]] = {}
    for item in items:
        groups.setdefault(item["hierarchy"], []).append(item)
    lines = [
        f"Warning (12241): {len(groups)} hierarchies have connectivity warnings - "
        "see the Connectivity Checks report folder"
    ]
    for hierarchy, rows in groups.items():
        lines.extend(
            (
                f'; Port Connectivity Checks: "{hierarchy}" ;',
                "+----------------+",
                "; Port ; Type ; Severity ; Details ;",
                "+----------------+",
            )
        )
        for item in rows:
            lines.append(
                f'; {item["port"]} ; {item["type"]} ; Warning ; '
                f'{item["details"]} ;'
            )
        lines.append("+----------------+")
    return "\n".join(lines) + "\n"


class ConnectivityPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = allowed_items()
        self.report = fixture_report(self.items)

    def review(self, report: str | None = None) -> dict:
        return policy.review_report(report or self.report, ROOT, POLICY)

    def test_exact_reviewed_set_is_accepted_and_bound(self) -> None:
        result = self.review()
        self.assertTrue(result["accepted"])
        self.assertEqual(result["status"], "accepted_exact_set")
        self.assertEqual(result["allowlist"]["rows"], 122)
        self.assertEqual(result["observed"]["warning_rows"], 122)
        self.assertEqual(result["observed"]["warning_hierarchies"], 30)
        self.assertEqual(
            result["observed"]["summary_message"],
            "Warning (12241): 30 hierarchies have connectivity warnings - "
            "see the Connectivity Checks report folder",
        )
        self.assertEqual(result["differences"]["missing"], [])
        self.assertEqual(result["differences"]["unexpected"], [])
        self.assertEqual(len(result["source_bindings"]), 23)

    def _mutated_item(self, field: str, value: str) -> str:
        items = [dict(item) for item in self.items]
        items[0][field] = value
        return fixture_report(items)

    def test_exact_tuple_mutations_are_rejected(self) -> None:
        for field, value in (
            ("hierarchy", "core_top:ic|unexpected:instance"),
            ("port", "unexpected_port"),
            ("type", "Input"),
            ("details", "Declared but intentionally changed."),
        ):
            with self.subTest(field=field):
                result = self.review(self._mutated_item(field, value))
                self.assertFalse(result["accepted"])
                self.assertEqual(result["differences"]["missing_count"], 1)
                self.assertEqual(result["differences"]["unexpected_count"], 1)

    def test_same_count_substitution_is_not_a_count_waiver(self) -> None:
        items = [dict(item) for item in self.items]
        items[-1]["port"] = "same_count_unreviewed_port"
        result = self.review(fixture_report(items))
        self.assertFalse(result["accepted"])
        self.assertEqual(result["observed"]["warning_rows"], 122)
        self.assertEqual(result["differences"]["missing_count"], 1)
        self.assertEqual(result["differences"]["unexpected_count"], 1)

    def test_reviewed_pll_defect_is_explicitly_excluded(self) -> None:
        manifest = json.loads(POLICY.read_text(encoding="utf-8"))
        defect = dict(manifest["reviewed_inventory"]["excluded_defects"][0])
        defect["provenance"] = "reviewed-defect"
        defect.pop("resolution")
        result = self.review(fixture_report([*self.items, defect]))
        self.assertFalse(result["accepted"])
        self.assertEqual(result["observed"]["warning_rows"], 123)
        self.assertEqual(result["observed"]["warning_hierarchies"], 31)
        self.assertEqual(result["differences"]["unexpected_count"], 1)
        self.assertEqual(
            result["differences"]["unexpected"][0]["hierarchy"],
            "core_top:ic|mf_pllbase:mp1",
        )

    def test_missing_and_extra_rows_are_rejected(self) -> None:
        missing = self.review(fixture_report(self.items[:-1]))
        self.assertFalse(missing["accepted"])
        self.assertEqual(missing["differences"]["missing_count"], 1)

        items = [dict(item) for item in self.items]
        extra = dict(items[-1])
        extra["port"] = "new_unreviewed_warning"
        items.append(extra)
        added = self.review(fixture_report(items))
        self.assertFalse(added["accepted"])
        self.assertEqual(added["differences"]["unexpected_count"], 1)

    def test_summary_and_duplicate_invariants_fail_closed(self) -> None:
        broken_summary = self.report.replace(
            "Warning (12241): 30 hierarchies",
            "Warning (12241): 31 hierarchies",
            1,
        )
        with self.assertRaisesRegex(policy.PolicyError, "hierarchy count"):
            self.review(broken_summary)

        items = [dict(item) for item in self.items]
        items.append(dict(items[-1]))
        with self.assertRaisesRegex(policy.PolicyError, "duplicate exact Warning"):
            self.review(fixture_report(items))

    def test_malformed_extra_connectivity_panel_is_not_ignored(self) -> None:
        # Reusing a reviewed hierarchy keeps the 12241 hierarchy count stable;
        # the near-native title must still fail instead of hiding its new row.
        hierarchy = self.items[0]["hierarchy"]
        injected = self.report + "\n".join(
            (
                f'; Port Connectivity Checks: "{hierarchy}" ; unexpected',
                "+----------------+",
                "; Port ; Type ; Severity ; Details ;",
                "+----------------+",
                "; injected ; Output ; Warning ; Unreviewed extra row. ;",
                "+----------------+",
                "",
            )
        )
        with self.assertRaisesRegex(
            policy.PolicyError, "malformed Port Connectivity Checks title"
        ):
            self.review(injected)

    def test_policy_cli_uses_strict_quartus_report_decoding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="connectivity-policy-cli-") as temporary:
            report = Path(temporary) / "ap_core.map.rpt"
            arguments = [
                "--report",
                str(report),
                "--source-root",
                str(ROOT),
                "--policy",
                str(POLICY),
            ]
            report.write_bytes(self.report.encode("utf-8") + b"85 \xb0C\n")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(policy.main(arguments), 0)

            for mutation in (b"\xff", b"\0"):
                with self.subTest(rejected_bytes=mutation.hex()):
                    report.write_bytes(self.report.encode("utf-8") + mutation)
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(policy.main(arguments), 1)

    def _copy_policy_tree(self, destination: Path) -> dict:
        document = json.loads(POLICY.read_text(encoding="utf-8"))
        paths = [policy.POLICY_RELATIVE, Path(document["allowlist"]["path"])]
        paths.extend(Path(relative) for relative in document["source_bindings"])
        for relative in paths:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        return document

    def test_any_bound_source_change_requires_fresh_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="connectivity-policy-source-") as temporary:
            root = Path(temporary)
            document = self._copy_policy_tree(root)
            relative = next(iter(document["source_bindings"]))
            path = root / relative
            path.write_bytes(path.read_bytes() + b"\n// mutation\n")
            with self.assertRaisesRegex(policy.PolicyError, "changed without review"):
                policy.review_report(self.report, root, root / policy.POLICY_RELATIVE)

    def test_allowlist_and_policy_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="connectivity-policy-file-") as temporary:
            root = Path(temporary)
            document = self._copy_policy_tree(root)
            allowlist = root / document["allowlist"]["path"]
            allowlist.write_bytes(allowlist.read_bytes() + b"\n")
            with self.assertRaisesRegex(policy.PolicyError, "SHA-256"):
                policy.review_report(self.report, root, root / policy.POLICY_RELATIVE)

        with tempfile.TemporaryDirectory(prefix="connectivity-policy-schema-") as temporary:
            root = Path(temporary)
            self._copy_policy_tree(root)
            manifest = root / policy.POLICY_RELATIVE
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["broad_waiver"] = 12241
            manifest.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(policy.PolicyError, "unknown or missing"):
                policy.review_report(self.report, root, manifest)

        with tempfile.TemporaryDirectory(prefix="connectivity-policy-duplicate-") as temporary:
            root = Path(temporary)
            self._copy_policy_tree(root)
            manifest = root / policy.POLICY_RELATIVE
            text = manifest.read_text(encoding="utf-8")
            manifest.write_text(
                text.replace(
                    '"warning_id": 12241',
                    '"warning_id": 12241, "warning_id": 12241',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(policy.PolicyError, "duplicate.*warning_id"):
                policy.review_report(self.report, root, manifest)


if __name__ == "__main__":
    unittest.main()
