#!/usr/bin/env python3
"""Mutation tests for reviewed Quartus connectivity-policy refresh drafts."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import quartus_connectivity_policy as policy
import quartus_connectivity_policy_refresh as refresh
import quartus_connectivity_source_closure as source_closure


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _row(name: str, provenance: str = "reviewed-existing") -> dict[str, str]:
    return {
        "provenance": provenance,
        "hierarchy": f"core_top:ic|fixture:{name}",
        "port": f"port_{name}",
        "type": "Output",
        "details": "Declared by entity but not connected by instance.",
    }


def _tsv(items: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=policy.ROW_FIELDS,
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(items)
    return stream.getvalue().encode("utf-8")


def _map_report(items: list[dict[str, str]]) -> bytes:
    groups: dict[str, list[dict[str, str]]] = {}
    for item in items:
        groups.setdefault(item["hierarchy"], []).append(item)
    lines = [
        "Analysis & Synthesis report for ap_core",
        "Quartus Prime Version 21.1.1 Build 850 06/23/2022 SJ Lite Edition",
        "",
        "+-------------------------------------------------------------------------------+",
        "; Analysis & Synthesis Summary                                                  ;",
        "+---------------------------------+---------------------------------------------+",
        "; Analysis & Synthesis Status     ; Successful - fixture                        ;",
        "; Quartus Prime Version           ; 21.1.1 Build 850 06/23/2022 SJ Lite Edition ;",
        "; Revision Name                   ; ap_core                                     ;",
        "; Top-level Entity Name           ; apf_top                                     ;",
        "; Family                          ; Cyclone V                                   ;",
        "+---------------------------------+---------------------------------------------+",
        "",
        "+---------------------------------------------------------------------------------------------------------------------------+",
        "; Analysis & Synthesis Settings                                                                                             ;",
        "+---------------------------------------------------------------------------------+--------------------+--------------------+",
        "; Option                                                                          ; Setting            ; Default Value      ;",
        "+---------------------------------------------------------------------------------+--------------------+--------------------+",
        "; Device                                                                          ; 5CEBA4F23C8        ;                    ;",
        "; Top-level entity name                                                           ; apf_top            ; ap_core            ;",
        "; Family name                                                                     ; Cyclone V          ; Cyclone V          ;",
        "+---------------------------------------------------------------------------------+--------------------+--------------------+",
        "",
        f"Warning (12241): {len(groups)} "
        f"{'hierarchy' if len(groups) == 1 else 'hierarchies'} have connectivity "
        "warnings - see the Connectivity Checks report folder",
    ]
    for hierarchy in sorted(groups):
        lines.extend(
            (
                f'; Port Connectivity Checks: "{hierarchy}" ;',
                "+----------------+",
                "; Port ; Type ; Severity ; Details ;",
                "+----------------+",
            )
        )
        for item in groups[hierarchy]:
            lines.append(
                f'; {item["port"]} ; {item["type"]} ; Warning ; '
                f'{item["details"]} ;'
            )
        lines.append("+----------------+")
    return ("\n".join(lines) + "\n").encode("utf-8")


class RefreshFixture:
    def __init__(self, root: Path, baseline_items: list[dict[str, str]]) -> None:
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        self.allowlist = self.repo / "review/connectivity.tsv"
        self.policy = self.repo / "review/connectivity.json"
        self.fpga = self.repo / "src/fpga"
        self.source = self.fpga / "top.v"
        self.source.parent.mkdir(parents=True)
        self.allowlist.parent.mkdir(parents=True)
        (self.fpga / "ap_core.qpf").write_text(
            'PROJECT_REVISION = "ap_core"\n', encoding="utf-8"
        )
        (self.fpga / "ap_core_assignment_defaults.qdf").write_text(
            "# fixture defaults\n", encoding="utf-8"
        )
        (self.fpga / "ap_core.qsf").write_text(
            "set_global_assignment -name VERILOG_FILE top.v\n",
            encoding="utf-8",
        )
        self.source.write_text("module top; endmodule\n", encoding="utf-8")
        allowlist_bytes = _tsv(baseline_items)
        self.allowlist.write_bytes(allowlist_bytes)
        binding_paths = (
            "src/fpga/ap_core.qpf",
            "src/fpga/ap_core.qsf",
            "src/fpga/ap_core_assignment_defaults.qdf",
            "src/fpga/top.v",
        )
        source_bindings = {
            relative: hashlib.sha256((self.repo / relative).read_bytes()).hexdigest()
            for relative in binding_paths
        }
        defect = {
            "details": "Previously reviewed defect.",
            "hierarchy": "core_top:ic|fixture:old_defect",
            "port": "rst",
            "resolution": "removed before the next reviewed build",
            "type": "Input",
        }
        document = {
            "allowlist": {
                "path": "review/connectivity.tsv",
                "rows": len(baseline_items),
                "sha256": hashlib.sha256(allowlist_bytes).hexdigest(),
            },
            "magic": policy.MAGIC,
            "quartus_version": "21.1.1 Build 850 Lite Edition",
            "reviewed_inventory": {
                "allowed_rows": len(baseline_items),
                "excluded_defects": [defect],
                "sha256": "a" * 64,
                "warning_rows": len(baseline_items) + 1,
            },
            "reviewed_map_report_sha256": "b" * 64,
            "reviewed_source_commit": "c" * 40,
            "reviewed_workflow_run_id": 100,
            "source_bindings": source_bindings,
            "warning_id": 12241,
        }
        self.policy.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _git(self.repo, "init")
        _git(self.repo, "add", ".")
        _git(
            self.repo,
            "-c",
            "user.name=Swan Song Test",
            "-c",
            "user.email=swan-song@example.invalid",
            "commit",
            "-m",
            "baseline",
        )
        self.artifacts = root / "artifacts"
        self.output_files = self.artifacts / "output_files"
        self.output_files.mkdir(parents=True)
        self.report = self.output_files / "ap_core.map.rpt"
        self.metadata = self.artifacts / "build-metadata.txt"

    @property
    def commit(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD")

    @property
    def epoch(self) -> str:
        return _git(self.repo, "show", "-s", "--format=%ct", self.commit)

    @property
    def policy_sha256(self) -> str:
        return hashlib.sha256(self.policy.read_bytes()).hexdigest()

    @property
    def report_sha256(self) -> str:
        return hashlib.sha256(self.report.read_bytes()).hexdigest()

    def commit_source_change(self) -> None:
        self.source.write_text("module top; wire reviewed; endmodule\n", encoding="utf-8")
        _git(self.repo, "add", "src/fpga/top.v")
        _git(
            self.repo,
            "-c",
            "user.name=Swan Song Test",
            "-c",
            "user.email=swan-song@example.invalid",
            "commit",
            "-m",
            "reviewed source change",
        )

    def write_build(self, items: list[dict[str, str]]) -> None:
        self.report.write_bytes(_map_report(items))
        self.metadata.write_text(
            "\n".join(
                (
                    f"source_commit={self.commit}",
                    f"source_date_epoch={self.epoch}",
                    "platform=linux/amd64",
                    "quartus=21.1.1.850 Lite",
                    "device=5CEBA4F23C8",
                    "",
                )
            ),
            encoding="utf-8",
        )

    def arguments(self, **overrides: object) -> dict[str, object]:
        result: dict[str, object] = {
            "source_root": self.repo,
            "policy_path": self.policy,
            "baseline_policy_sha256": self.policy_sha256,
            "report_path": self.report,
            "build_metadata_path": self.metadata,
            "reviewed_source_commit": self.commit,
            "reviewed_workflow_run_id": 200,
            "reviewed_map_report_sha256": self.report_sha256,
            "additions_review_path": None,
        }
        result.update(overrides)
        return result


class ConnectivityPolicyRefreshTest(unittest.TestCase):
    def test_removal_refresh_is_deterministic_and_preserves_provenance(self) -> None:
        # Deliberately not lexical: retained review rows must not be reordered.
        baseline = [
            _row("b", "origin-b"),
            _row("a", "origin-a"),
            _row("c", "origin-c"),
        ]
        with tempfile.TemporaryDirectory(prefix="connectivity-refresh-") as temporary:
            fixture = RefreshFixture(Path(temporary), baseline)
            fixture.commit_source_change()
            fixture.write_build([baseline[0], baseline[2]])

            first = refresh.prepare_refresh(**fixture.arguments())
            second = refresh.prepare_refresh(**fixture.arguments())

            self.assertTrue(first.approved)
            self.assertEqual(first.policy_bytes, second.policy_bytes)
            self.assertEqual(first.allowlist_bytes, second.allowlist_bytes)
            differences = first.summary["differences"]
            self.assertEqual(differences["removed_count"], 1)
            self.assertEqual(differences["removed"][0]["provenance"], "origin-a")
            self.assertEqual(differences["added_count"], 0)
            self.assertEqual(first.summary["source_binding_changes"]["count"], 1)
            self.assertEqual(first.summary["cleared_excluded_defects"], 1)

            rows = list(
                csv.DictReader(
                    io.StringIO(first.allowlist_bytes.decode("utf-8")), delimiter="\t"
                )
            )
            self.assertEqual(rows, [baseline[0], baseline[2]])
            document = json.loads(first.policy_bytes)
            self.assertEqual(document["reviewed_source_commit"], fixture.commit)
            self.assertEqual(document["reviewed_workflow_run_id"], 200)
            self.assertEqual(
                document["reviewed_map_report_sha256"], fixture.report_sha256
            )
            self.assertEqual(document["allowlist"]["rows"], 2)
            self.assertEqual(document["reviewed_inventory"]["warning_rows"], 2)
            self.assertEqual(document["reviewed_inventory"]["excluded_defects"], [])
            self.assertEqual(
                document["source_bindings"]["src/fpga/top.v"],
                hashlib.sha256(fixture.source.read_bytes()).hexdigest(),
            )
            self.assertEqual(document["magic"], policy.UPGRADED_MAGIC)
            self.assertEqual(
                document["source_closure"]["algorithm"], source_closure.MAGIC
            )
            self.assertEqual(document["source_closure"]["paths"], 4)

    def test_unreviewed_addition_reports_diff_and_writes_nothing(self) -> None:
        baseline = [_row("a")]
        addition = _row("new")
        with tempfile.TemporaryDirectory(prefix="connectivity-addition-") as temporary:
            fixture = RefreshFixture(Path(temporary), baseline)
            fixture.write_build([*baseline, addition])
            proposal = refresh.prepare_refresh(**fixture.arguments())
            self.assertFalse(proposal.approved)
            self.assertIsNone(proposal.policy_bytes)
            self.assertEqual(proposal.summary["differences"]["added_count"], 1)
            self.assertEqual(
                proposal.summary["differences"]["added"][0]["port"], "port_new"
            )

            output_policy = Path(temporary) / "draft.json"
            output_allowlist = Path(temporary) / "draft.tsv"
            arguments = [
                "--source-root",
                str(fixture.repo),
                "--policy",
                str(fixture.policy),
                "--baseline-policy-sha256",
                fixture.policy_sha256,
                "--report",
                str(fixture.report),
                "--build-metadata",
                str(fixture.metadata),
                "--reviewed-source-commit",
                fixture.commit,
                "--reviewed-workflow-run-id",
                "200",
                "--reviewed-map-report-sha256",
                fixture.report_sha256,
                "--output-policy",
                str(output_policy),
                "--output-allowlist",
                str(output_allowlist),
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(refresh.main(arguments), 1)
            self.assertIn('"added_count": 1', stdout.getvalue())
            self.assertIn("require --additions-review", stderr.getvalue())
            self.assertFalse(output_policy.exists())
            self.assertFalse(output_allowlist.exists())

    def test_exact_additions_review_is_required_and_deterministic(self) -> None:
        baseline = [_row("a")]
        addition = _row("new", "newly-reviewed")
        with tempfile.TemporaryDirectory(prefix="connectivity-review-tsv-") as temporary:
            fixture = RefreshFixture(Path(temporary), baseline)
            fixture.write_build([*baseline, addition])
            review = Path(temporary) / "additions.tsv"
            review.write_bytes(_tsv([addition]))
            proposal = refresh.prepare_refresh(
                **fixture.arguments(additions_review_path=review)
            )
            self.assertTrue(proposal.approved)
            rows = list(
                csv.DictReader(
                    io.StringIO(proposal.allowlist_bytes.decode("utf-8")), delimiter="\t"
                )
            )
            self.assertEqual(
                [(item["port"], item["provenance"]) for item in rows],
                [("port_a", "reviewed-existing"), ("port_new", "newly-reviewed")],
            )

            review.write_bytes(_tsv([_row("wrong", "newly-reviewed")]))
            with self.assertRaisesRegex(
                policy.PolicyError, "not the exact added Warning 12241 set"
            ):
                refresh.prepare_refresh(
                    **fixture.arguments(additions_review_path=review)
                )

            review.write_bytes(_tsv([addition, addition]))
            with self.assertRaisesRegex(policy.PolicyError, "duplicate exact row"):
                refresh.prepare_refresh(
                    **fixture.arguments(additions_review_path=review)
                )

            unstable = dict(addition)
            unstable["provenance"] = "Reviewed by whoever"
            review.write_bytes(_tsv([unstable]))
            with self.assertRaisesRegex(policy.PolicyError, "stable lowercase"):
                refresh.prepare_refresh(
                    **fixture.arguments(additions_review_path=review)
                )

    def test_source_commit_metadata_and_worktree_drift_fail_closed(self) -> None:
        baseline = [_row("a")]
        with tempfile.TemporaryDirectory(prefix="connectivity-source-drift-") as temporary:
            fixture = RefreshFixture(Path(temporary), baseline)
            fixture.write_build(baseline)
            with self.assertRaisesRegex(policy.PolicyError, "does not match Git HEAD"):
                refresh.prepare_refresh(
                    **fixture.arguments(reviewed_source_commit="0" * 40)
                )

            fixture.source.write_bytes(fixture.source.read_bytes() + b"// dirty\n")
            with self.assertRaisesRegex(policy.PolicyError, "unstaged drift"):
                refresh.prepare_refresh(**fixture.arguments())
            _git(fixture.repo, "checkout", "--", "src/fpga/top.v")

            metadata = fixture.metadata.read_text(encoding="utf-8")
            fixture.metadata.write_text(
                metadata.replace(fixture.commit, "1" * 40), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                policy.PolicyError, "metadata source commit does not match"
            ):
                refresh.prepare_refresh(**fixture.arguments())

            fixture.write_build(baseline)
            fixture.metadata.write_text(
                fixture.metadata.read_text(encoding="utf-8").replace(
                    f"source_date_epoch={fixture.epoch}",
                    f"source_date_epoch={int(fixture.epoch) + 1}",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                policy.PolicyError, "epoch does not match reviewed source commit"
            ):
                refresh.prepare_refresh(**fixture.arguments())

    def test_report_policy_and_identity_mutations_fail_closed(self) -> None:
        baseline = [_row("a")]
        with tempfile.TemporaryDirectory(prefix="connectivity-report-id-") as temporary:
            fixture = RefreshFixture(Path(temporary), baseline)
            fixture.write_build(baseline)
            with self.assertRaisesRegex(policy.PolicyError, "baseline policy SHA-256"):
                refresh.prepare_refresh(
                    **fixture.arguments(baseline_policy_sha256="0" * 64)
                )
            with self.assertRaisesRegex(policy.PolicyError, "map report SHA-256"):
                refresh.prepare_refresh(
                    **fixture.arguments(reviewed_map_report_sha256="0" * 64)
                )

            report = fixture.report.read_bytes().replace(
                b"5CEBA4F23C8", b"5CEBA5F23C8"
            )
            fixture.report.write_bytes(report)
            with self.assertRaisesRegex(policy.PolicyError, "report identity is invalid"):
                refresh.prepare_refresh(**fixture.arguments())

            fixture.write_build(baseline)
            original = fixture.report
            target = original.with_name("real.map.rpt")
            original.rename(target)
            original.symlink_to(target.name)
            with self.assertRaisesRegex(policy.PolicyError, "regular nonsymlink"):
                refresh.prepare_refresh(**fixture.arguments())

    def test_draft_writer_refuses_live_paths_and_clobber(self) -> None:
        baseline = [_row("a")]
        with tempfile.TemporaryDirectory(prefix="connectivity-output-") as temporary:
            fixture = RefreshFixture(Path(temporary), baseline)
            fixture.write_build(baseline)
            proposal = refresh.prepare_refresh(**fixture.arguments())
            output_policy = Path(temporary) / "draft.json"
            output_allowlist = Path(temporary) / "draft.tsv"

            with self.assertRaisesRegex(policy.PolicyError, "refuses to overwrite"):
                refresh.write_proposal(
                    proposal,
                    output_policy=fixture.policy,
                    output_allowlist=output_allowlist,
                    protected_policy=fixture.policy,
                    protected_allowlist=fixture.allowlist,
                )
            output_allowlist.write_text("stale", encoding="utf-8")
            with self.assertRaisesRegex(policy.PolicyError, "already exists"):
                refresh.write_proposal(
                    proposal,
                    output_policy=output_policy,
                    output_allowlist=output_allowlist,
                    protected_policy=fixture.policy,
                    protected_allowlist=fixture.allowlist,
                )
            self.assertFalse(output_policy.exists())

            output_allowlist.unlink()
            refresh.write_proposal(
                proposal,
                output_policy=output_policy,
                output_allowlist=output_allowlist,
                protected_policy=fixture.policy,
                protected_allowlist=fixture.allowlist,
            )
            self.assertEqual(output_policy.read_bytes(), proposal.policy_bytes)
            self.assertEqual(output_allowlist.read_bytes(), proposal.allowlist_bytes)


class ConnectivitySourceClosureSchemaTest(unittest.TestCase):
    def test_legacy_policy_remains_hash_bound_without_claiming_complete_closure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="connectivity-legacy-closure-") as temporary:
            fixture = RefreshFixture(Path(temporary), [_row("a")])
            document = json.loads(fixture.policy.read_text(encoding="utf-8"))
            document["source_bindings"] = {
                "src/fpga/top.v": hashlib.sha256(
                    fixture.source.read_bytes()
                ).hexdigest()
            }

            validated = policy._validate_source_bindings(  # noqa: SLF001
                document, fixture.repo
            )
            self.assertEqual(set(validated), {"src/fpga/top.v"})

            fixture.source.write_text(
                "module top; wire changed; endmodule\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(policy.PolicyError, "changed without review"):
                policy._validate_source_bindings(document, fixture.repo)  # noqa: SLF001

    def test_refreshed_v2_policy_requires_the_exact_complete_closure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="connectivity-v2-closure-") as temporary:
            fixture = RefreshFixture(Path(temporary), [_row("a")])
            fixture.write_build([_row("a")])
            proposal = refresh.prepare_refresh(**fixture.arguments())
            document = json.loads(proposal.policy_bytes)
            draft = Path(temporary) / "draft-policy.json"
            draft.write_bytes(proposal.policy_bytes)
            reread, _, _ = policy._read_policy(  # noqa: SLF001
                draft, fixture.repo
            )
            self.assertEqual(reread["magic"], policy.UPGRADED_MAGIC)
            reviewed = policy.review_report(
                fixture.report.read_text(encoding="utf-8"), fixture.repo, draft
            )
            self.assertTrue(reviewed["accepted"])
            self.assertEqual(reviewed["policy_magic"], policy.UPGRADED_MAGIC)

            validated = policy._validate_source_bindings(  # noqa: SLF001
                document, fixture.repo
            )
            self.assertEqual(len(validated), 4)

            missing = json.loads(json.dumps(document))
            missing["source_bindings"].pop("src/fpga/top.v")
            with self.assertRaisesRegex(policy.PolicyError, "complete Quartus closure"):
                policy._validate_source_bindings(missing, fixture.repo)  # noqa: SLF001

            extra = json.loads(json.dumps(document))
            extra["source_bindings"]["review/connectivity.tsv"] = hashlib.sha256(
                fixture.allowlist.read_bytes()
            ).hexdigest()
            extra["source_bindings"] = dict(sorted(extra["source_bindings"].items()))
            with self.assertRaisesRegex(policy.PolicyError, "complete Quartus closure"):
                policy._validate_source_bindings(extra, fixture.repo)  # noqa: SLF001

            wrong_identity = json.loads(json.dumps(document))
            wrong_identity["source_closure"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(policy.PolicyError, "identity is not current"):
                policy._validate_source_bindings(  # noqa: SLF001
                    wrong_identity, fixture.repo
                )

    def test_explicit_refresh_upgrades_an_incomplete_legacy_binding_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="connectivity-legacy-upgrade-") as temporary:
            fixture = RefreshFixture(Path(temporary), [_row("a")])
            document = json.loads(fixture.policy.read_text(encoding="utf-8"))
            document["source_bindings"] = {
                "src/fpga/top.v": document["source_bindings"]["src/fpga/top.v"]
            }
            fixture.policy.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _git(fixture.repo, "add", "review/connectivity.json")
            _git(
                fixture.repo,
                "-c",
                "user.name=Swan Song Test",
                "-c",
                "user.email=swan-song@example.invalid",
                "commit",
                "-m",
                "legacy subset fixture",
            )
            fixture.write_build([_row("a")])

            proposal = refresh.prepare_refresh(**fixture.arguments())
            upgraded = json.loads(proposal.policy_bytes)
            self.assertEqual(upgraded["magic"], policy.UPGRADED_MAGIC)
            self.assertEqual(upgraded["source_closure"]["paths"], 4)
            self.assertEqual(len(upgraded["source_bindings"]), 4)
            changes = proposal.summary["source_binding_changes"]["entries"]
            self.assertEqual(
                [item["path"] for item in changes if item["change"] == "added"],
                [
                    "src/fpga/ap_core.qpf",
                    "src/fpga/ap_core.qsf",
                    "src/fpga/ap_core_assignment_defaults.qdf",
                ],
            )

    def test_refresh_adds_newly_assigned_hdl_to_v2_bindings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="connectivity-new-hdl-") as temporary:
            fixture = RefreshFixture(Path(temporary), [_row("a")])
            new_source = fixture.fpga / "new_feature.sv"
            new_source.write_text("module new_feature; endmodule\n", encoding="utf-8")
            qsf = fixture.fpga / "ap_core.qsf"
            qsf.write_text(
                qsf.read_text(encoding="utf-8")
                + "set_global_assignment -name SYSTEMVERILOG_FILE new_feature.sv\n",
                encoding="utf-8",
            )
            _git(fixture.repo, "add", "src/fpga/ap_core.qsf", "src/fpga/new_feature.sv")
            _git(
                fixture.repo,
                "-c",
                "user.name=Swan Song Test",
                "-c",
                "user.email=swan-song@example.invalid",
                "commit",
                "-m",
                "add reviewed HDL",
            )
            fixture.write_build([_row("a")])

            proposal = refresh.prepare_refresh(**fixture.arguments())
            document = json.loads(proposal.policy_bytes)
            self.assertIn("src/fpga/new_feature.sv", document["source_bindings"])
            changes = proposal.summary["source_binding_changes"]["entries"]
            self.assertIn(
                ("src/fpga/new_feature.sv", "added"),
                [(item["path"], item["change"]) for item in changes],
            )
            self.assertEqual(document["source_closure"]["paths"], 5)


if __name__ == "__main__":
    unittest.main()
