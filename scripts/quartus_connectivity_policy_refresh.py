#!/usr/bin/env python3
"""Prepare, but never install, an exact Quartus Warning 12241 policy refresh."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Optional, Sequence

import quartus_connectivity_policy as connectivity
import quartus_connectivity_source_closure as source_closure
import quartus_fit_audit as fit_audit
from quartus_report_text import decode_quartus_report


MAGIC = "SWAN_SONG_QUARTUS_CONNECTIVITY_REFRESH_V1"
MAX_MAP_REPORT_BYTES = 64 * 1024 * 1024
PROVENANCE_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,62})?\Z")


@dataclass(frozen=True)
class RefreshProposal:
    """A deterministic draft plus the review diff that authorized it."""

    approved: bool
    summary: dict[str, object]
    policy_bytes: Optional[bytes]
    allowlist_bytes: Optional[bytes]


def _identity_bytes(value: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}


def _read_plain_file(path: Path, label: str, maximum: int) -> bytes:
    path = path.absolute()
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise connectivity.PolicyError(f"{label} does not exist: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise connectivity.PolicyError(
            f"{label} must be a regular nonsymlink file: {path}"
        )
    if metadata.st_size > maximum:
        raise connectivity.PolicyError(f"{label} exceeds {maximum} bytes: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_dev != metadata.st_dev
        or opened.st_ino != metadata.st_ino
    ):
        os.close(descriptor)
        raise connectivity.PolicyError(f"{label} changed while opening: {path}")
    with os.fdopen(descriptor, "rb", closefd=True) as source:
        value = source.read(maximum + 1)
    if len(value) > maximum:
        raise connectivity.PolicyError(f"{label} grew beyond {maximum} bytes: {path}")
    return value


def _git(source_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ("git", "-C", str(source_root), *arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise connectivity.PolicyError(f"could not execute Git: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise connectivity.PolicyError(
            f"Git {' '.join(arguments)} failed"
            + (f": {detail}" if detail else "")
        )
    return completed.stdout


def _require_clean_checkout(
    source_root: Path, reviewed_source_commit: str
) -> tuple[dict[str, str], dict[str, object]]:
    if connectivity.HEX_40.fullmatch(reviewed_source_commit) is None:
        raise connectivity.PolicyError(
            "reviewed source commit must be a lowercase full 40-hex commit"
        )
    source_root = source_root.resolve(strict=True)
    git_root = Path(
        _git(source_root, "rev-parse", "--show-toplevel")
        .decode("utf-8")
        .strip()
    ).resolve(strict=True)
    if git_root != source_root:
        raise connectivity.PolicyError(
            f"source root {source_root} is not the Git worktree root {git_root}"
        )
    head = _git(source_root, "rev-parse", "--verify", "HEAD").decode().strip()
    if head != reviewed_source_commit:
        raise connectivity.PolicyError(
            "reviewed source commit does not match Git HEAD: "
            f"reviewed={reviewed_source_commit} head={head}"
        )

    # The generated APF build ID is intentionally excluded, matching the clean
    # build contract. Every other tracked change is source drift.
    exclude_mif = ":(exclude)src/fpga/apf/build_id.mif"
    for staged in (False, True):
        arguments = ["diff", "--quiet"]
        if staged:
            arguments.append("--cached")
        arguments.extend(("--", ".", exclude_mif))
        try:
            completed = subprocess.run(
                ("git", "-C", str(source_root), *arguments),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as error:
            raise connectivity.PolicyError(f"could not execute Git: {error}") from error
        if completed.returncode not in (0, 1):
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise connectivity.PolicyError(
                "could not inspect tracked source drift"
                + (f": {detail}" if detail else "")
            )
        if completed.returncode == 1:
            kind = "staged" if staged else "unstaged"
            raise connectivity.PolicyError(
                f"tracked source has {kind} drift from reviewed commit"
            )

    try:
        return source_closure.committed_bindings(
            source_root, reviewed_source_commit
        )
    except source_closure.ClosureError as error:
        raise connectivity.PolicyError(f"invalid Quartus source closure: {error}") from error


def _row_from_item(item: dict[str, str], label: str) -> connectivity.ConnectivityRow:
    for field in connectivity.ROW_FIELDS:
        value = item.get(field)
        if not isinstance(value, str) or not value or any(
            character in value for character in "\0\t\r\n"
        ):
            raise connectivity.PolicyError(f"{label} has an invalid {field} field")
    if PROVENANCE_RE.fullmatch(item["provenance"]) is None:
        raise connectivity.PolicyError(
            f"{label} provenance must be a stable lowercase review label"
        )
    if item["type"] not in {"Input", "Output", "Bidir"}:
        raise connectivity.PolicyError(f"{label} has an unknown port type")
    return connectivity.ConnectivityRow(
        hierarchy=item["hierarchy"],
        port=item["port"],
        type=item["type"],
        details=item["details"],
    )


def _load_review_rows(
    data: bytes, label: str
) -> dict[connectivity.ConnectivityRow, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise connectivity.PolicyError(f"{label} is not UTF-8") from error
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if tuple(reader.fieldnames or ()) != connectivity.ROW_FIELDS:
        raise connectivity.PolicyError(f"{label} header is not exact")
    records: dict[connectivity.ConnectivityRow, str] = {}
    for number, item in enumerate(reader, 2):
        if None in item or set(item) != set(connectivity.ROW_FIELDS):
            raise connectivity.PolicyError(f"malformed {label} row {number}")
        row = _row_from_item(item, f"{label} row {number}")
        if row in records:
            raise connectivity.PolicyError(f"{label} contains a duplicate exact row")
        records[row] = item["provenance"]
    return records


def _encode_allowlist(
    records: dict[connectivity.ConnectivityRow, str]
) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=connectivity.ROW_FIELDS,
        delimiter="\t",
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    # Dict insertion order is intentional: retained rows keep their exact
    # baseline order, while the caller appends newly reviewed rows in sorted
    # tuple order. A refresh therefore remains deterministic without creating
    # an unrelated whole-file reorder.
    for row, provenance in records.items():
        writer.writerow({"provenance": provenance, **row.document()})
    return stream.getvalue().encode("utf-8")


def _inventory_bytes(rows: Sequence[connectivity.ConnectivityRow]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=("hierarchy", "port", "type", "details"),
        delimiter="\t",
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in sorted(rows):
        writer.writerow(row.document())
    return stream.getvalue().encode("utf-8")


def _row_with_provenance(
    row: connectivity.ConnectivityRow, provenance: str
) -> dict[str, str]:
    return {"provenance": provenance, **row.document()}


def prepare_refresh(
    *,
    source_root: Path,
    policy_path: Path,
    baseline_policy_sha256: str,
    report_path: Path,
    build_metadata_path: Path,
    reviewed_source_commit: str,
    reviewed_workflow_run_id: int,
    reviewed_map_report_sha256: str,
    additions_review_path: Optional[Path] = None,
) -> RefreshProposal:
    """Validate provenance and create an in-memory, reviewable policy draft."""

    if connectivity.HEX_64.fullmatch(baseline_policy_sha256) is None:
        raise connectivity.PolicyError(
            "baseline policy SHA-256 must be a lowercase 64-hex digest"
        )
    if connectivity.HEX_64.fullmatch(reviewed_map_report_sha256) is None:
        raise connectivity.PolicyError(
            "reviewed map report SHA-256 must be a lowercase 64-hex digest"
        )
    if (
        isinstance(reviewed_workflow_run_id, bool)
        or not isinstance(reviewed_workflow_run_id, int)
        or reviewed_workflow_run_id <= 0
    ):
        raise connectivity.PolicyError(
            "reviewed workflow run ID must be an explicit positive integer"
        )

    source_root = source_root.resolve(strict=True)
    selected_policy = policy_path.absolute()
    baseline, allowlist_path, actual_policy_sha256 = connectivity._read_policy(  # noqa: SLF001
        selected_policy, source_root
    )
    if actual_policy_sha256 != baseline_policy_sha256:
        raise connectivity.PolicyError(
            "baseline policy SHA-256 does not match the explicitly reviewed policy"
        )
    baseline_rows, _ = connectivity._load_allowlist(  # noqa: SLF001
        allowlist_path, baseline["allowlist"]["rows"]
    )
    baseline_records = _load_review_rows(
        _read_plain_file(allowlist_path, "baseline connectivity allowlist", 8 * 1024 * 1024),
        "baseline connectivity allowlist",
    )
    if set(baseline_rows) != set(baseline_records):
        raise connectivity.PolicyError(
            "baseline allowlist provenance rows do not match its exact warning rows"
        )

    raw_bindings = baseline["source_bindings"]
    if (
        not isinstance(raw_bindings, dict)
        or not raw_bindings
        or list(raw_bindings) != sorted(raw_bindings)
    ):
        raise connectivity.PolicyError("baseline source bindings must be an object")
    for relative, digest in raw_bindings.items():
        if (
            not isinstance(relative, str)
            or not isinstance(digest, str)
            or connectivity.HEX_64.fullmatch(digest) is None
        ):
            raise connectivity.PolicyError("baseline source binding is malformed")
    new_bindings, new_source_closure = _require_clean_checkout(
        source_root, reviewed_source_commit
    )

    report_path = report_path.absolute()
    build_metadata_path = build_metadata_path.absolute()
    if (
        report_path.name != "ap_core.map.rpt"
        or report_path.parent.name != "output_files"
        or build_metadata_path.name != "build-metadata.txt"
        or build_metadata_path.parent.resolve(strict=True)
        != report_path.parent.parent.resolve(strict=True)
    ):
        raise connectivity.PolicyError(
            "map report and build metadata must use one exact Quartus artifact layout"
        )
    report_bytes = _read_plain_file(
        report_path, "reviewed Quartus map report", MAX_MAP_REPORT_BYTES
    )
    report_identity = _identity_bytes(report_bytes)
    if report_identity["sha256"] != reviewed_map_report_sha256:
        raise connectivity.PolicyError(
            "reviewed map report SHA-256 does not match the selected report"
        )
    if b"\0" in report_bytes:
        raise connectivity.PolicyError("NUL byte in reviewed Quartus map report")
    try:
        report_text = decode_quartus_report(report_bytes)
        synthesis = fit_audit.validate_synthesis_report(report_text)
    except (UnicodeError, fit_audit.AuditError) as error:
        raise connectivity.PolicyError(
            f"reviewed map report identity is invalid: {error}"
        ) from error

    metadata_bytes = _read_plain_file(
        build_metadata_path, "reviewed build metadata", 1024 * 1024
    )
    try:
        metadata_text = metadata_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise connectivity.PolicyError("reviewed build metadata is not UTF-8") from error
    try:
        metadata = fit_audit.parse_metadata(metadata_text)
    except fit_audit.AuditError as error:
        raise connectivity.PolicyError(
            f"reviewed build metadata is invalid: {error}"
        ) from error
    if metadata["source_commit"] != reviewed_source_commit:
        raise connectivity.PolicyError(
            "reviewed build metadata source commit does not match explicit review"
        )
    commit_epoch = _git(
        source_root, "show", "-s", "--format=%ct", reviewed_source_commit
    ).decode().strip()
    if metadata["source_date_epoch"] != commit_epoch:
        raise connectivity.PolicyError(
            "reviewed build metadata epoch does not match reviewed source commit"
        )

    observed, total_panels, warning_panels = connectivity.extract_warning_rows(
        report_text
    )
    baseline_set = set(baseline_rows)
    observed_set = set(observed)
    removed = sorted(baseline_set - observed_set)
    added = sorted(observed_set - baseline_set)

    additions_records: dict[connectivity.ConnectivityRow, str] = {}
    if additions_review_path is not None:
        additions_records = _load_review_rows(
            _read_plain_file(
                additions_review_path,
                "reviewed connectivity additions",
                8 * 1024 * 1024,
            ),
            "reviewed connectivity additions",
        )
        if set(additions_records) != set(added):
            missing = sorted(set(added) - set(additions_records))
            extra = sorted(set(additions_records) - set(added))
            raise connectivity.PolicyError(
                "reviewed additions TSV is not the exact added Warning 12241 set: "
                f"missing={len(missing)} extra={len(extra)}"
            )

    approved = not added or additions_review_path is not None
    source_changes = []
    for relative in sorted(set(raw_bindings) | set(new_bindings)):
        before = raw_bindings.get(relative)
        after = new_bindings.get(relative)
        if before == after:
            continue
        if before is None:
            change = "added"
        elif after is None:
            change = "removed"
        else:
            change = "changed"
        source_changes.append(
            {
                "path": relative,
                "change": change,
                "before_sha256": before,
                "after_sha256": after,
            }
        )
    summary: dict[str, object] = {
        "magic": MAGIC,
        "approved_for_draft": approved,
        "baseline": {
            "policy_sha256": actual_policy_sha256,
            "reviewed_source_commit": baseline["reviewed_source_commit"],
            "reviewed_workflow_run_id": baseline["reviewed_workflow_run_id"],
            "reviewed_map_report_sha256": baseline["reviewed_map_report_sha256"],
        },
        "reviewed_build": {
            "source_commit": reviewed_source_commit,
            "source_date_epoch": int(metadata["source_date_epoch"]),
            "workflow_run_id": reviewed_workflow_run_id,
            "map_report": report_identity,
            "build_metadata": _identity_bytes(metadata_bytes),
            "quartus_version": synthesis["version"],
            "revision": synthesis["revision"],
            "top_level": synthesis["top_level"],
            "family": synthesis["family"],
            "device": synthesis["device"],
        },
        "observed": {
            "warning_rows": len(observed),
            "warning_hierarchies": warning_panels,
            "all_connectivity_panels": total_panels,
        },
        "differences": {
            "removed_count": len(removed),
            "removed": [
                _row_with_provenance(row, baseline_records[row]) for row in removed
            ],
            "added_count": len(added),
            "added": [row.document() for row in added],
            "additions_review_supplied": additions_review_path is not None,
        },
        "source_binding_changes": {
            "count": len(source_changes),
            "entries": source_changes,
        },
        "source_closure": new_source_closure,
        "cleared_excluded_defects": len(
            baseline["reviewed_inventory"]["excluded_defects"]
        ),
    }
    if not approved:
        return RefreshProposal(False, summary, None, None)

    new_records = {
        row: provenance
        for row, provenance in baseline_records.items()
        if row in observed_set
    }
    for row in sorted(additions_records):
        new_records[row] = additions_records[row]
    if set(new_records) != observed_set:
        raise connectivity.PolicyError(
            "internal refresh error: output allowlist is not the observed exact set"
        )
    allowlist_bytes = _encode_allowlist(new_records)
    inventory_bytes = _inventory_bytes(observed)
    refreshed = json.loads(json.dumps(baseline))
    refreshed["magic"] = connectivity.UPGRADED_MAGIC
    refreshed["reviewed_source_commit"] = reviewed_source_commit
    refreshed["reviewed_workflow_run_id"] = reviewed_workflow_run_id
    refreshed["reviewed_map_report_sha256"] = reviewed_map_report_sha256
    refreshed["source_bindings"] = new_bindings
    refreshed["source_closure"] = new_source_closure
    refreshed["allowlist"] = {
        "path": baseline["allowlist"]["path"],
        "rows": len(new_records),
        "sha256": hashlib.sha256(allowlist_bytes).hexdigest(),
    }
    refreshed["reviewed_inventory"] = {
        "allowed_rows": len(new_records),
        "excluded_defects": [],
        "sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "warning_rows": len(observed),
    }
    policy_bytes = (
        json.dumps(refreshed, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    summary["draft"] = {
        "policy": _identity_bytes(policy_bytes),
        "allowlist": _identity_bytes(allowlist_bytes),
    }
    return RefreshProposal(True, summary, policy_bytes, allowlist_bytes)


def write_proposal(
    proposal: RefreshProposal,
    *,
    output_policy: Path,
    output_allowlist: Path,
    protected_policy: Path,
    protected_allowlist: Path,
) -> None:
    """Write both draft files with no-clobber semantics and rollback on failure."""

    if (
        not proposal.approved
        or proposal.policy_bytes is None
        or proposal.allowlist_bytes is None
    ):
        raise connectivity.PolicyError(
            "unexpected Warning 12241 additions require an exact additions review TSV"
        )
    try:
        output_policy = (
            output_policy.absolute().parent.resolve(strict=True)
            / output_policy.name
        )
        output_allowlist = (
            output_allowlist.absolute().parent.resolve(strict=True)
            / output_allowlist.name
        )
        protected_policy = protected_policy.resolve(strict=True)
        protected_allowlist = protected_allowlist.resolve(strict=True)
    except OSError as error:
        raise connectivity.PolicyError(
            f"could not resolve draft/protected output identity: {error}"
        ) from error
    protected = {
        protected_policy,
        protected_allowlist,
    }
    if output_policy == output_allowlist:
        raise connectivity.PolicyError("draft policy and allowlist outputs must differ")
    if output_policy in protected or output_allowlist in protected:
        raise connectivity.PolicyError(
            "refresh tool prepares drafts and refuses to overwrite the live policy"
        )
    for path in (output_policy, output_allowlist):
        if path.exists() or path.is_symlink():
            raise connectivity.PolicyError(f"draft output already exists: {path}")
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise connectivity.PolicyError(
                f"draft output parent must be a nonsymlink directory: {path.parent}"
            )

    created: list[Path] = []
    try:
        for path, value in (
            (output_allowlist, proposal.allowlist_bytes),
            (output_policy, proposal.policy_bytes),
        ):
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags, 0o644)
            created.append(path)
            with os.fdopen(descriptor, "wb", closefd=True) as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--baseline-policy-sha256", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--build-metadata", required=True, type=Path)
    parser.add_argument("--reviewed-source-commit", required=True)
    parser.add_argument("--reviewed-workflow-run-id", required=True, type=int)
    parser.add_argument("--reviewed-map-report-sha256", required=True)
    parser.add_argument("--additions-review", type=Path)
    parser.add_argument("--output-policy", required=True, type=Path)
    parser.add_argument("--output-allowlist", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        proposal = prepare_refresh(
            source_root=args.source_root,
            policy_path=args.policy,
            baseline_policy_sha256=args.baseline_policy_sha256,
            report_path=args.report,
            build_metadata_path=args.build_metadata,
            reviewed_source_commit=args.reviewed_source_commit,
            reviewed_workflow_run_id=args.reviewed_workflow_run_id,
            reviewed_map_report_sha256=args.reviewed_map_report_sha256,
            additions_review_path=args.additions_review,
        )
        if not proposal.approved:
            print(json.dumps(proposal.summary, indent=2, sort_keys=True))
            print(
                "quartus_connectivity_policy_refresh.py: unexpected additions "
                "require --additions-review; no draft written",
                file=sys.stderr,
            )
            return 1
        baseline, allowlist, _ = connectivity._read_policy(  # noqa: SLF001
            args.policy.absolute(), args.source_root.resolve(strict=True)
        )
        del baseline
        write_proposal(
            proposal,
            output_policy=args.output_policy,
            output_allowlist=args.output_allowlist,
            protected_policy=args.policy,
            protected_allowlist=allowlist,
        )
    except (OSError, connectivity.PolicyError) as error:
        print(f"quartus_connectivity_policy_refresh.py: {error}", file=sys.stderr)
        return 1
    print(json.dumps(proposal.summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
