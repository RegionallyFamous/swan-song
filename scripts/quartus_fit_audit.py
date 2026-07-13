#!/usr/bin/env python3
"""Fail-closed audit of Swan Song's Quartus 21.1.1 build artifacts."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


MAGIC = "SWAN_SONG_QUARTUS_AUDIT_V1"
VERSION_RE = re.compile(r"\bVersion 21\.1\.1 Build 850\b")
EXPECTED = {
    "revision": "ap_core",
    "top_level": "apf_top",
    "family": "Cyclone V",
    "device": "5CEBA4F23C8",
}
REQUIRED_CLOCKS = ("clk_74a", "clk_74b", "bridge_spiclk")
ANALYSES = ("setup", "hold", "recovery", "removal")
REPORTS = {
    "flow": ("output_files/ap_core.flow.rpt", ("flow status",)),
    "fit": ("output_files/ap_core.fit.rpt", ("fitter status",)),
    "assembly": ("output_files/ap_core.asm.rpt", ("assembler status",)),
    "timing_analysis": (
        "output_files/ap_core.sta.rpt",
        ("timequest timing analyzer status", "timing analyzer status"),
    ),
}
OTHER_INPUTS = (
    "output_files/ap_core.rbf",
    "toolchain-version.txt",
    "build-metadata.txt",
    "build_id.mif",
    "ap_core.rbf.sha256",
    "quartus.log",
)


class AuditError(RuntimeError):
    pass


def norm(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def cells(line: str) -> Optional[List[str]]:
    if ";" not in line:
        return None
    parts = line.strip().split(";")
    if parts and not parts[0].strip():
        parts.pop(0)
    if parts and not parts[-1].strip():
        parts.pop()
    return [part.strip() for part in parts]


def read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
        if b"\0" in data:
            raise AuditError(f"NUL byte in text artifact: {path.name}")
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuditError(f"non-UTF-8 text artifact: {path.name}") from exc


def safe_input(root: Path, relative: str) -> Path:
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise AuditError(f"symlink artifact is forbidden: {relative}")
    if not current.is_file():
        raise AuditError(f"missing regular artifact: {relative}")
    if current.stat().st_size == 0:
        raise AuditError(f"empty artifact: {relative}")
    return current


def digest(path: Path) -> Dict[str, object]:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return {"sha256": h.hexdigest(), "size": path.stat().st_size}


def scalar(lines: Sequence[str], aliases: Iterable[str], label: str) -> str:
    wanted = {norm(alias) for alias in aliases}
    found: List[str] = []
    for line in lines:
        row = cells(line)
        if row is not None and len(row) == 2 and norm(row[0]) in wanted:
            found.append(row[1].strip())
    unique = sorted(set(found))
    if len(unique) != 1 or not unique[0]:
        raise AuditError(f"{label}: expected one unambiguous value, found {unique!r}")
    return unique[0]


def validate_version(value: str, label: str) -> None:
    if not VERSION_RE.search(value) or "Lite Edition" not in value:
        raise AuditError(f"{label}: expected Quartus 21.1.1 Build 850 Lite Edition")


def validate_report(text: str, kind: str, status_aliases: Sequence[str]) -> Dict[str, str]:
    lines = text.splitlines()
    status = scalar(lines, status_aliases, f"{kind} status")
    if re.match(r"^Successful(?:\s|$|-)", status) is None:
        raise AuditError(f"{kind} status is not successful: {status}")
    version = scalar(lines, ("Quartus Prime Version", "Quartus Version"), f"{kind} version")
    validate_version(version, f"{kind} version")
    identity = {
        "revision": scalar(lines, ("Revision Name",), f"{kind} revision"),
        "top_level": scalar(
            lines, ("Top-level Entity Name", "Top Level Entity Name"), f"{kind} top level"
        ),
        "family": scalar(lines, ("Family",), f"{kind} family"),
        "device": scalar(lines, ("Device",), f"{kind} device"),
    }
    for field, expected in EXPECTED.items():
        if identity[field] != expected:
            raise AuditError(f"{kind} {field} is {identity[field]!r}, expected {expected!r}")
    return {"status": status, "version": version, **identity}


def parse_used_available(value: str, label: str, require_available: bool) -> Dict[str, Optional[int]]:
    match = re.fullmatch(
        r"\s*([0-9][0-9,]*)\s*"
        r"(?:/\s*([0-9][0-9,]*)\s*"
        r"(?:\(\s*(?:<\s*)?[0-9]+(?:\.[0-9]+)?\s*%\s*\))?)?\s*",
        value,
    )
    if match is None:
        raise AuditError(f"malformed {label} resource value: {value!r}")
    used = int(match.group(1).replace(",", ""))
    available = int(match.group(2).replace(",", "")) if match.group(2) else None
    if require_available and available is None:
        raise AuditError(f"{label} resource capacity is missing")
    if available is not None and (available <= 0 or used > available):
        raise AuditError(f"invalid {label} resource utilization: {value!r}")
    return {"used": used, "available": available}


def resource_summary(fit_text: str) -> Dict[str, Dict[str, Optional[int]]]:
    lines = fit_text.splitlines()
    specs = {
        "logic": (("Logic utilization (in ALMs)", "Total ALMs", "Total logic elements"), True),
        "registers": (("Total registers",), False),
        "memory_bits": (("Total block memory bits", "Total memory bits"), True),
        "plls": (("Total PLLs",), True),
    }
    result = {}
    for label, (aliases, require_available) in specs.items():
        result[label] = parse_used_available(
            scalar(lines, aliases, f"fit {label}"), label, require_available
        )
    return result


def table_after(lines: Sequence[str], title_index: int) -> Tuple[List[str], List[List[str]], bool]:
    header: Optional[List[str]] = None
    rows: List[List[str]] = []
    no_paths = False
    for line in lines[title_index + 1 :]:
        row = cells(line)
        if row is None:
            continue
        if len(row) == 1:
            if norm(row[0]) == "no paths to report":
                no_paths = True
                continue
            if header is not None or rows or no_paths:
                break
            continue
        if header is None:
            header = row
        else:
            rows.append(row)
    if header is None:
        return [], [], no_paths
    return header, rows, no_paths


def decimal_value(value: str, label: str) -> Decimal:
    match = re.fullmatch(r"\s*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))\s*(?:ns)?\s*", value)
    cleaned = match.group(1) if match is not None else ""
    try:
        parsed = Decimal(cleaned)
    except (InvalidOperation, IndexError) as exc:
        raise AuditError(f"malformed {label}: {value!r}") from exc
    if not parsed.is_finite():
        raise AuditError(f"non-finite {label}: {value!r}")
    return parsed


def timing_summary(sta_text: str) -> Dict[str, object]:
    lines = sta_text.splitlines()
    per_analysis: Dict[str, List[Dict[str, object]]] = {name: [] for name in ANALYSES}
    title_re = re.compile(r"^(.+ Model) (Setup|Hold|Recovery|Removal) Summary$", re.I)
    for index, line in enumerate(lines):
        row = cells(line)
        if row is None or len(row) != 1:
            continue
        match = title_re.match(row[0].strip())
        if match is None:
            continue
        corner, analysis = match.group(1), match.group(2).lower()
        if any(entry["corner"] == corner for entry in per_analysis[analysis]):
            raise AuditError(f"duplicate {analysis} summary for {corner}")
        header, rows, no_paths = table_after(lines, index)
        normalized = [norm(item) for item in header]
        slack_indexes = [i for i, item in enumerate(normalized) if item in ("slack", "worst case slack")]
        if no_paths:
            if rows or analysis in ("setup", "hold"):
                raise AuditError(f"invalid no-paths {analysis} summary for {corner}")
            per_analysis[analysis].append({"corner": corner, "path_count": 0, "worst_slack": None})
            continue
        if len(slack_indexes) != 1 or not rows:
            raise AuditError(f"unknown {analysis} timing table format for {corner}")
        slack_index = slack_indexes[0]
        tns_indexes = [
            i for i, item in enumerate(normalized)
            if item in ("tns", "end point tns", "total negative slack", "design wide tns")
        ]
        slacks: List[Decimal] = []
        tns_values: List[Decimal] = []
        for data in rows:
            if len(data) != len(header):
                raise AuditError(f"ragged {analysis} timing row for {corner}")
            slacks.append(decimal_value(data[slack_index], f"{analysis} slack"))
            for tns_index in tns_indexes:
                tns_values.append(decimal_value(data[tns_index], f"{analysis} TNS"))
        if min(slacks) < 0 or (tns_values and min(tns_values) < 0):
            raise AuditError(f"negative {analysis} slack or TNS for {corner}")
        per_analysis[analysis].append(
            {
                "corner": corner,
                "path_count": len(rows),
                "worst_slack": str(min(slacks)),
                "worst_tns": str(min(tns_values)) if tns_values else None,
            }
        )
    for analysis in ANALYSES:
        if not per_analysis[analysis]:
            raise AuditError(f"missing {analysis} timing summary")

    clock_titles = [
        i for i, line in enumerate(lines)
        if (cells(line) is not None and cells(line) == ["Clock Summary"])
    ]
    if len(clock_titles) != 1:
        raise AuditError("expected exactly one Clock Summary")
    header, rows, _ = table_after(lines, clock_titles[0])
    normalized = [norm(item) for item in header]
    indexes = [i for i, item in enumerate(normalized) if item in ("clock", "clock name")]
    if len(indexes) != 1 or not rows:
        raise AuditError("unknown Clock Summary format")
    clock_names = sorted({row[indexes[0]] for row in rows if len(row) == len(header)})
    missing_clocks = sorted(set(REQUIRED_CLOCKS) - set(clock_names))
    if missing_clocks:
        raise AuditError(f"missing required clocks: {', '.join(missing_clocks)}")

    unconstrained_titles = [
        i for i, line in enumerate(lines)
        if (cells(line) is not None and cells(line) == ["Unconstrained Paths Summary"])
    ]
    if len(unconstrained_titles) != 1:
        raise AuditError("expected exactly one Unconstrained Paths Summary")
    header, rows, _ = table_after(lines, unconstrained_titles[0])
    normalized = [norm(item) for item in header]
    type_indexes = [i for i, item in enumerate(normalized) if item in ("analysis", "analysis type")]
    count_indexes = [i for i, item in enumerate(normalized) if item in ("count", "unconstrained paths")]
    if len(type_indexes) != 1 or len(count_indexes) != 1 or not rows:
        raise AuditError("unknown Unconstrained Paths Summary format")
    counts: Dict[str, int] = {}
    for row in rows:
        if len(row) != len(header):
            raise AuditError("ragged Unconstrained Paths Summary row")
        analysis = norm(row[type_indexes[0]]).removesuffix(" analysis")
        if analysis not in ANALYSES or analysis in counts:
            raise AuditError(f"unknown or duplicate unconstrained analysis: {analysis!r}")
        raw_count = row[count_indexes[0]].replace(",", "").strip()
        if not raw_count.isdigit():
            raise AuditError(f"malformed unconstrained path count: {raw_count!r}")
        counts[analysis] = int(raw_count)
    if set(counts) != set(ANALYSES) or any(counts.values()):
        raise AuditError(f"missing or nonzero unconstrained path counts: {counts}")

    return {
        "analyses": per_analysis,
        "clocks": {"observed": clock_names, "required": list(REQUIRED_CLOCKS)},
        "unconstrained_paths": counts,
    }


def critical_warnings(texts: Dict[str, str]) -> List[Dict[str, object]]:
    inventory = []
    for relative in sorted(texts):
        for line_number, line in enumerate(texts[relative].splitlines(), 1):
            if re.search(r"\bCritical Warning\b", line, re.I):
                inventory.append(
                    {"artifact": relative, "line": line_number, "message": " ".join(line.split())}
                )
    return inventory


def parse_metadata(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in text.splitlines():
        if not line or "=" not in line:
            raise AuditError("malformed build-metadata.txt")
        key, value = line.split("=", 1)
        if key in result or not key or not value:
            raise AuditError("duplicate or empty build metadata")
        result[key] = value
    expected = {"platform": "linux/amd64", "quartus": "21.1.1.850 Lite", "device": EXPECTED["device"]}
    for key, value in expected.items():
        if result.get(key) != value:
            raise AuditError(f"build metadata {key} mismatch")
    if re.fullmatch(r"[0-9a-f]{40}", result.get("source_commit", "")) is None:
        raise AuditError("invalid source_commit metadata")
    if not result.get("source_date_epoch", "").isdigit():
        raise AuditError("invalid source_date_epoch metadata")
    if set(result) != {"source_commit", "source_date_epoch", *expected}:
        raise AuditError("unknown or missing build metadata fields")
    return result


def audit(artifact_directory: Path) -> Dict[str, object]:
    root = artifact_directory.resolve(strict=True)
    if not root.is_dir():
        raise AuditError(f"not an artifact directory: {root}")
    paths = {relative: safe_input(root, relative) for relative in OTHER_INPUTS}
    for relative, _ in REPORTS.values():
        paths[relative] = safe_input(root, relative)
    artifacts = {relative: digest(path) for relative, path in sorted(paths.items())}
    texts = {
        relative: read_text(path)
        for relative, path in paths.items()
        if relative != "output_files/ap_core.rbf"
    }

    validate_version(texts["toolchain-version.txt"], "toolchain-version.txt")
    metadata = parse_metadata(texts["build-metadata.txt"])
    rbf_hash = artifacts["output_files/ap_core.rbf"]["sha256"]
    expected_hash_line = f"{rbf_hash}  /artifacts/output_files/ap_core.rbf"
    if texts["ap_core.rbf.sha256"].strip() != expected_hash_line:
        raise AuditError("ap_core.rbf.sha256 does not match the RBF")

    flow = {}
    report_identity = None
    for kind, (relative, status_aliases) in REPORTS.items():
        parsed = validate_report(texts[relative], kind, status_aliases)
        identity = {key: parsed[key] for key in EXPECTED}
        if report_identity is not None and identity != report_identity:
            raise AuditError("report identities disagree")
        report_identity = identity
        flow[kind] = {"status": parsed["status"], "version": parsed["version"]}

    resources = resource_summary(texts[REPORTS["fit"][0]])
    timing = timing_summary(texts[REPORTS["timing_analysis"][0]])
    warnings = critical_warnings(texts)
    no_critical = not warnings
    gates = {
        "assembly_success": True,
        "compressed_bitstream": None,
        "dock_hardware": False,
        "fit_success": True,
        "flow_success": True,
        "hold_timing": True,
        "no_critical_warnings": no_critical,
        "no_unconstrained_paths": True,
        "pocket_hardware": False,
        "recovery_timing": True,
        "removal_timing": True,
        "setup_timing": True,
        "timing_analysis_success": True,
    }
    return {
        "quartus_audit": {
            "magic": MAGIC,
            "audit_pass": no_critical,
            "release_eligible": False,
            "identity": report_identity,
            "provenance": metadata,
            "artifacts": artifacts,
            "flow": flow,
            "resources": resources,
            "timing": timing,
            "critical_warnings": {"count": len(warnings), "entries": warnings},
            "candidate_gates": gates,
            "limitations": [
                "Candidate evidence only; this schema is not SWAN_SONG_RELEASE_EVIDENCE_V1.",
                "Pocket and Dock hardware gates are always false and require physical testing.",
                "Compressed-bitstream acceptance is not inferred from an RBF filename.",
                "Report parsing remains provisional until genuine Quartus 21.1.1 reports are audited.",
            ],
        }
    }


def write_json(path: Path, payload: Dict[str, object]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output or args.artifacts / "quartus-audit-candidate.json"
    try:
        if output.exists():
            output.unlink()
        payload = audit(args.artifacts)
        write_json(output, payload)
    except (AuditError, OSError) as exc:
        print(f"quartus_fit_audit.py: {exc}", file=sys.stderr)
        return 1
    result = payload["quartus_audit"]
    if not result["audit_pass"]:
        print(f"quartus_fit_audit.py: critical warnings found; candidate written to {output}", file=sys.stderr)
        return 1
    print(f"Quartus candidate audit passed (non-release evidence): {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
