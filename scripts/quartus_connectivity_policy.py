#!/usr/bin/env python3
"""Fail-closed review of Quartus 12241 connectivity rows against an exact policy."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from typing import Optional, Sequence

import quartus_connectivity_source_closure as source_closure
from quartus_report_text import decode_quartus_report


MAGIC = "SWAN_SONG_QUARTUS_CONNECTIVITY_POLICY_V1"
UPGRADED_MAGIC = "SWAN_SONG_QUARTUS_CONNECTIVITY_POLICY_V2"
POLICY_RELATIVE = Path(
    "toolchains/quartus-21.1.1/connectivity-warning-12241.json"
)
LEGACY_POLICY_KEYS = {
    "allowlist",
    "magic",
    "quartus_version",
    "reviewed_inventory",
    "reviewed_map_report_sha256",
    "reviewed_source_commit",
    "reviewed_workflow_run_id",
    "source_bindings",
    "warning_id",
}
POLICY_KEYS = LEGACY_POLICY_KEYS
UPGRADED_POLICY_KEYS = LEGACY_POLICY_KEYS | {"source_closure"}
SOURCE_CLOSURE_KEYS = {"algorithm", "paths", "sha256"}
ALLOWLIST_KEYS = {"path", "rows", "sha256"}
REVIEWED_INVENTORY_KEYS = {
    "allowed_rows",
    "excluded_defects",
    "sha256",
    "warning_rows",
}
EXCLUDED_DEFECT_KEYS = {"details", "hierarchy", "port", "resolution", "type"}
ROW_FIELDS = ("provenance", "hierarchy", "port", "type", "details")
HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
PANEL_TITLE = re.compile(
    r'^;\s*Port Connectivity Checks:\s*"([^"]+)"\s*;\s*$'
)
PANEL_TITLE_PREFIX = re.compile(r"^;\s*Port Connectivity Checks\b", re.IGNORECASE)
SUMMARY = re.compile(
    r"^Warning \(12241\): ([0-9]+) hierarch(?:y|ies) have connectivity "
    r"warnings - see the Connectivity Checks report folder\s*$"
)


class PolicyError(ValueError):
    """The policy, its source bindings, or the report shape is invalid."""


@dataclass(frozen=True, order=True)
class ConnectivityRow:
    hierarchy: str
    port: str
    type: str
    details: str

    def document(self) -> dict[str, str]:
        return {
            "hierarchy": self.hierarchy,
            "port": self.port,
            "type": self.type,
            "details": self.details,
        }


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError(f"duplicate connectivity policy JSON field: {key}")
        result[key] = value
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_regular(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or candidate.as_posix() != relative
    ):
        raise PolicyError(f"{label} must be a normalized relative path: {relative!r}")
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise PolicyError(f"{label} must not traverse a symlink: {relative}")
    if not current.is_file():
        raise PolicyError(f"{label} is not a regular file: {relative}")
    return current


def _read_policy(policy_path: Path, source_root: Path) -> tuple[dict, Path, str]:
    if policy_path.is_symlink() or not policy_path.is_file():
        raise PolicyError(f"policy is not a regular nonsymlink file: {policy_path}")
    try:
        policy = json.loads(
            policy_path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyError(f"invalid UTF-8 policy JSON: {error}") from error
    if not isinstance(policy, dict) or set(policy) not in (
        LEGACY_POLICY_KEYS,
        UPGRADED_POLICY_KEYS,
    ):
        keys = sorted(policy) if isinstance(policy, dict) else type(policy).__name__
        raise PolicyError(f"policy has unknown or missing fields: {keys!r}")
    upgraded = set(policy) == UPGRADED_POLICY_KEYS
    expected_magic = UPGRADED_MAGIC if upgraded else MAGIC
    if policy["magic"] != expected_magic or policy["warning_id"] != 12241:
        raise PolicyError("policy magic or warning ID is not the reviewed contract")
    if upgraded:
        closure = policy["source_closure"]
        if (
            not isinstance(closure, dict)
            or set(closure) != SOURCE_CLOSURE_KEYS
            or closure.get("algorithm") != source_closure.MAGIC
            or not isinstance(closure.get("paths"), int)
            or isinstance(closure.get("paths"), bool)
            or closure["paths"] <= 0
            or not isinstance(closure.get("sha256"), str)
            or HEX_64.fullmatch(closure["sha256"]) is None
        ):
            raise PolicyError("policy source-closure metadata is malformed")
    if policy["quartus_version"] != "21.1.1 Build 850 Lite Edition":
        raise PolicyError("policy is not scoped to Quartus 21.1.1 Build 850 Lite")
    if (
        not isinstance(policy["reviewed_workflow_run_id"], int)
        or policy["reviewed_workflow_run_id"] <= 0
        or not isinstance(policy["reviewed_source_commit"], str)
        or HEX_40.fullmatch(policy["reviewed_source_commit"]) is None
        or not isinstance(policy["reviewed_map_report_sha256"], str)
        or HEX_64.fullmatch(policy["reviewed_map_report_sha256"]) is None
    ):
        raise PolicyError("policy review provenance is malformed")
    allowlist = policy["allowlist"]
    if not isinstance(allowlist, dict) or set(allowlist) != ALLOWLIST_KEYS:
        raise PolicyError("policy allowlist fields are not exact")
    if (
        not isinstance(allowlist["path"], str)
        or not isinstance(allowlist["rows"], int)
        or allowlist["rows"] <= 0
        or not isinstance(allowlist["sha256"], str)
        or HEX_64.fullmatch(allowlist["sha256"]) is None
    ):
        raise PolicyError("policy allowlist metadata is malformed")
    allowlist_path = _safe_regular(
        source_root, allowlist["path"], "connectivity allowlist"
    )
    if _sha256(allowlist_path) != allowlist["sha256"]:
        raise PolicyError("connectivity allowlist SHA-256 does not match policy")
    inventory = policy["reviewed_inventory"]
    if not isinstance(inventory, dict) or set(inventory) != REVIEWED_INVENTORY_KEYS:
        raise PolicyError("reviewed connectivity inventory fields are not exact")
    defects = inventory["excluded_defects"]
    if (
        not isinstance(inventory["sha256"], str)
        or HEX_64.fullmatch(inventory["sha256"]) is None
        or not isinstance(inventory["warning_rows"], int)
        or not isinstance(inventory["allowed_rows"], int)
        or inventory["allowed_rows"] != allowlist["rows"]
        or not isinstance(defects, list)
        or inventory["warning_rows"] != inventory["allowed_rows"] + len(defects)
    ):
        raise PolicyError("reviewed connectivity inventory metadata is malformed")
    for defect in defects:
        if (
            not isinstance(defect, dict)
            or set(defect) != EXCLUDED_DEFECT_KEYS
            or any(not isinstance(value, str) or not value for value in defect.values())
            or defect["type"] not in {"Input", "Output", "Bidir"}
        ):
            raise PolicyError("reviewed excluded connectivity defect is malformed")
    return policy, allowlist_path, _sha256(policy_path)


def _validate_source_bindings(policy: dict, source_root: Path) -> dict[str, str]:
    bindings = policy["source_bindings"]
    if not isinstance(bindings, dict) or not bindings:
        raise PolicyError("policy source_bindings must be a nonempty object")
    if list(bindings) != sorted(bindings):
        raise PolicyError("policy source_bindings must use deterministic path order")
    validated: dict[str, str] = {}
    for relative, expected in bindings.items():
        if (
            not isinstance(relative, str)
            or not isinstance(expected, str)
            or HEX_64.fullmatch(expected) is None
        ):
            raise PolicyError("policy contains a malformed source binding")
        path = _safe_regular(source_root, relative, "bound connectivity source")
        actual = _sha256(path)
        if actual != expected:
            raise PolicyError(
                f"bound connectivity source changed without review: {relative}"
            )
        validated[relative] = actual
    if policy["magic"] == UPGRADED_MAGIC:
        try:
            complete_bindings, complete_identity = source_closure.current_bindings(
                source_root
            )
        except source_closure.ClosureError as error:
            raise PolicyError(f"invalid Quartus source closure: {error}") from error
        if policy["source_closure"] != complete_identity:
            raise PolicyError("policy source-closure identity is not current and exact")
        expected_paths = set(bindings)
        complete_paths = set(complete_bindings)
        if expected_paths != complete_paths:
            missing = sorted(complete_paths - expected_paths)
            unexpected = sorted(expected_paths - complete_paths)
            raise PolicyError(
                "policy source bindings are not the complete Quartus closure: "
                f"missing={missing!r} unexpected={unexpected!r}"
            )
        if validated != complete_bindings:
            raise PolicyError("policy source bindings do not match the complete closure")
    return validated


def _load_allowlist(path: Path, expected_rows: int) -> tuple[list[ConnectivityRow], dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise PolicyError("connectivity allowlist is not UTF-8") from error
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if tuple(reader.fieldnames or ()) != ROW_FIELDS:
        raise PolicyError("connectivity allowlist header is not exact")
    expected: list[ConnectivityRow] = []
    provenance: dict[str, int] = {}
    for number, item in enumerate(reader, start=2):
        if None in item or set(item) != set(ROW_FIELDS):
            raise PolicyError(f"malformed connectivity allowlist row {number}")
        if any(not isinstance(item[field], str) or not item[field] for field in ROW_FIELDS):
            raise PolicyError(f"empty connectivity allowlist field on row {number}")
        if item["type"] not in {"Input", "Output", "Bidir"}:
            raise PolicyError(f"unknown connectivity type on allowlist row {number}")
        expected.append(
            ConnectivityRow(
                hierarchy=item["hierarchy"],
                port=item["port"],
                type=item["type"],
                details=item["details"],
            )
        )
        provenance[item["provenance"]] = provenance.get(item["provenance"], 0) + 1
    if len(expected) != expected_rows:
        raise PolicyError(
            f"connectivity allowlist has {len(expected)} rows, expected {expected_rows}"
        )
    if len(set(expected)) != len(expected):
        raise PolicyError("connectivity allowlist contains duplicate exact rows")
    return sorted(expected), dict(sorted(provenance.items()))


def _panel_cells(line: str, hierarchy: str, line_number: int) -> tuple[str, str, str, str]:
    stripped = line.strip()
    if not stripped.startswith(";") or not stripped.endswith(";"):
        raise PolicyError(
            f"malformed connectivity table row at report line {line_number}"
        )
    fields = [field.strip() for field in stripped[1:-1].split(";", 3)]
    if len(fields) != 4 or any(not field for field in fields):
        raise PolicyError(
            f"malformed connectivity table cells at report line {line_number}"
        )
    return tuple(fields)  # type: ignore[return-value]


def _panel_row(line: str, hierarchy: str, line_number: int) -> tuple[str, str, str, str]:
    port, port_type, severity, details = _panel_cells(
        line, hierarchy, line_number
    )
    if port_type not in {"Input", "Output", "Bidir"}:
        raise PolicyError(
            f"unknown connectivity port type {port_type!r} in {hierarchy!r}"
        )
    if severity not in {"Info", "Warning"}:
        raise PolicyError(
            f"unknown connectivity severity {severity!r} in {hierarchy!r}"
        )
    return port, port_type, severity, details


def extract_warning_rows(report_text: str) -> tuple[list[ConnectivityRow], int, int]:
    """Extract every native Warning row and cross-check the 12241 summary."""

    lines = report_text.splitlines()
    warnings: list[ConnectivityRow] = []
    index = 0
    panels = 0
    while index < len(lines):
        title = PANEL_TITLE.fullmatch(lines[index])
        if title is None:
            if PANEL_TITLE_PREFIX.match(lines[index].lstrip()) is not None:
                raise PolicyError(
                    "malformed Port Connectivity Checks title at report line "
                    f"{index + 1}"
                )
            index += 1
            continue
        hierarchy = title.group(1)
        panels += 1
        if index + 3 >= len(lines):
            raise PolicyError(f"truncated connectivity panel {hierarchy!r}")
        if not lines[index + 1].lstrip().startswith("+"):
            raise PolicyError(f"missing connectivity panel border for {hierarchy!r}")
        header = _panel_cells(lines[index + 2], hierarchy, index + 3)
        if header != ("Port", "Type", "Severity", "Details"):
            raise PolicyError(f"unknown connectivity table header for {hierarchy!r}")
        if not lines[index + 3].lstrip().startswith("+"):
            raise PolicyError(f"missing connectivity header border for {hierarchy!r}")
        index += 4
        row_count = 0
        while index < len(lines) and not lines[index].lstrip().startswith("+"):
            port, port_type, severity, details = _panel_row(
                lines[index], hierarchy, index + 1
            )
            row_count += 1
            if severity == "Warning":
                warnings.append(
                    ConnectivityRow(hierarchy, port, port_type, details)
                )
            index += 1
        if row_count == 0 or index >= len(lines):
            raise PolicyError(f"empty or unterminated connectivity panel {hierarchy!r}")
        index += 1

    summaries = []
    for line in lines:
        match = SUMMARY.fullmatch(line.strip())
        if match is not None:
            summaries.append(int(match.group(1)))
    if len(summaries) != 1:
        raise PolicyError(
            f"expected one exact Warning 12241 summary, found {len(summaries)}"
        )
    warning_panels = len({row.hierarchy for row in warnings})
    if summaries[0] != warning_panels:
        raise PolicyError(
            "Warning 12241 hierarchy count does not match detailed warning panels: "
            f"summary={summaries[0]} details={warning_panels}"
        )
    if len(set(warnings)) != len(warnings):
        raise PolicyError("connectivity report contains duplicate exact Warning rows")
    return sorted(warnings), panels, warning_panels


def review_report(
    report_text: str,
    source_root: Path,
    policy_path: Optional[Path] = None,
) -> dict:
    source_root = source_root.resolve(strict=True)
    selected_policy = policy_path or source_root / POLICY_RELATIVE
    policy, allowlist_path, policy_sha256 = _read_policy(
        selected_policy, source_root
    )
    bindings = _validate_source_bindings(policy, source_root)
    expected, provenance = _load_allowlist(
        allowlist_path, policy["allowlist"]["rows"]
    )
    observed, total_panels, warning_panels = extract_warning_rows(report_text)
    expected_set = set(expected)
    observed_set = set(observed)
    missing = sorted(expected_set - observed_set)
    unexpected = sorted(observed_set - expected_set)
    accepted = not missing and not unexpected
    return {
        "accepted": accepted,
        "status": "accepted_exact_set" if accepted else "rejected_exact_set",
        "policy_magic": policy["magic"],
        "policy_sha256": policy_sha256,
        "warning_id": 12241,
        "reviewed_workflow_run_id": policy["reviewed_workflow_run_id"],
        "reviewed_source_commit": policy["reviewed_source_commit"],
        "reviewed_map_report_sha256": policy["reviewed_map_report_sha256"],
        "reviewed_inventory": policy["reviewed_inventory"],
        "allowlist": {
            "path": policy["allowlist"]["path"],
            "sha256": policy["allowlist"]["sha256"],
            "rows": len(expected),
            "provenance": provenance,
        },
        "source_bindings": bindings,
        "observed": {
            "warning_rows": len(observed),
            "warning_hierarchies": warning_panels,
            "all_connectivity_panels": total_panels,
            "summary_message": (
                f"Warning (12241): {warning_panels} "
                f"{'hierarchy' if warning_panels == 1 else 'hierarchies'} "
                "have connectivity "
                "warnings - see the Connectivity Checks report folder"
            ),
        },
        "differences": {
            "missing_count": len(missing),
            "missing": [row.document() for row in missing],
            "unexpected_count": len(unexpected),
            "unexpected": [row.document() for row in unexpected],
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args(argv)
    try:
        report_bytes = args.report.read_bytes()
        if b"\0" in report_bytes:
            raise PolicyError("NUL byte in Quartus connectivity report")
        report = decode_quartus_report(report_bytes)
        result = review_report(report, args.source_root, args.policy)
    except (OSError, UnicodeError, PolicyError) as error:
        print(f"quartus_connectivity_policy.py: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
