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

import quartus_container_provenance as container_provenance
import quartus_connectivity_policy as connectivity_policy
from quartus_report_text import decode_quartus_report


MAGIC = "SWAN_SONG_QUARTUS_AUDIT_V1"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(
    r"^(?:Version )?(21[.]1[.]1 Build 850 "
    r"[0-9]{2}/[0-9]{2}/[0-9]{4} [A-Za-z0-9]+ Lite Edition)$"
)
EXPECTED = {
    "revision": "ap_core",
    "top_level": "apf_top",
    "family": "Cyclone V",
    "device": "5CEBA4F23C8",
}
REQUIRED_CLOCKS = ("clk_74a", "clk_74b", "bridge_spiclk")
TIMING_PATH_ANALYSES = ("setup", "hold", "recovery", "removal")
ANALYSES = (*TIMING_PATH_ANALYSES, "minimum_pulse_width")
EXPECTED_TIMING_CORNERS = (
    "Slow 1100mV 85C Model",
    "Slow 1100mV 0C Model",
    "Fast 1100mV 85C Model",
    "Fast 1100mV 0C Model",
)
IDENTITY_REPORT_KINDS = ("flow", "fit", "assembly")
UNCONSTRAINED_PROPERTIES = (
    "illegal clocks",
    "unconstrained clocks",
    "unconstrained input ports",
    "unconstrained input port paths",
    "unconstrained output ports",
    "unconstrained output port paths",
)
CHECK_TIMING_ROWS = (
    "reference_pin",
    "generated_io_delay",
    "partial_input_delay",
    "partial_output_delay",
    "io_min_max_delay_consistency",
    "partial_min_max_delay",
    "partial_multicycle",
    "multicycle_consistency",
)
CHECK_TIMING_MARKER = "SWAN_SONG_CHECK_TIMING_V2 checks 8 findings 0"
TIMING_GATE_MARKER = (
    "SWAN_SONG_TIMING_GATE_V1 corners 4 analyses 4 negative_paths 0"
)
MIN_PULSE_GATE_MARKER = (
    "SWAN_SONG_MIN_PULSE_GATE_V1 corners 4 worst_checks 4 negative_checks 0"
)
SDRAM_DQ_MARKER_RE = re.compile(
    r"^SWAN_SONG_SDRAM_DQ_V1 corner "
    r"(slow|fast)\|(85|0)\|(1100) setup_paths 16 setup_worst "
    r"([^ ]+) hold_paths 16 hold_worst ([^ ]+)$"
)
# The compile-time-disabled Pocket Memories controller consumed sixteen M10Ks
# in the current 305-block fit even though APF could not request it.  Require
# the exact 289-block result after removing that transport.  The source
# contract separately checks the capability gate itself; this remains a fitted
# resource gate, not an estimate derived from logical memory-bit utilization.
MAX_CANDIDATE_RAM_BLOCKS = 289
WORKFLOW_REPOSITORY = "RegionallyFamous/swansong-core"
WORKFLOW_PATH = ".github/workflows/quartus-fit.yml"
WORKFLOW_JOB = "fit"
WORKFLOW_METADATA_FIELDS = {
    "workflow_repository",
    "workflow_path",
    "workflow_sha",
    "workflow_run_id",
    "workflow_run_attempt",
    "workflow_job",
    "workflow_job_nonce",
}
IP_LICENSE_HEADER = (
    "vendor",
    "ip core name",
    "version",
    "release date",
    "license type",
    "entity instance",
    "ip include file",
)
EVALUATION_WARNING_IDS = (
    12188,
    12189,
    12190,
    210039,
    210042,
    265069,
    265072,
    265073,
    265074,
)
TIME_LIMITED_INFO_IDS = (115017,)
REPORTS = {
    "synthesis": (
        "output_files/ap_core.map.rpt",
        ("analysis & synthesis status", "analysis and synthesis status"),
    ),
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
    "container-provenance.json",
    "container-packages.tsv",
)
REQUIRED_ARTIFACTS = (
    *OTHER_INPUTS,
    *(relative for relative, _ in REPORTS.values()),
)
VENDOR_REPORTS = frozenset(relative for relative, _ in REPORTS.values())


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


def read_text(path: Path, *, vendor_report: bool = False) -> str:
    try:
        data = path.read_bytes()
        if b"\0" in data:
            raise AuditError(f"NUL byte in text artifact: {path.name}")
        if vendor_report:
            return decode_quartus_report(data)
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


def validate_version(value: str, label: str) -> str:
    versions = set()
    for line in value.splitlines():
        match = VERSION_RE.fullmatch(" ".join(line.split()))
        if match is not None:
            versions.add(f"Version {match.group(1)}")
    versions = sorted(versions)
    if len(versions) != 1:
        raise AuditError(f"{label}: expected Quartus 21.1.1 Build 850 Lite Edition")
    return versions[0]


def validate_assembler_version(lines: Sequence[str]) -> str:
    """Read the version from native Assembler header and/or summary rows."""

    raw_versions: List[str] = []
    for line in lines:
        row = cells(line)
        if (
            row is not None
            and len(row) == 2
            and norm(row[0]) in ("quartus prime version", "quartus version")
        ):
            raw_versions.append(row[1].strip())
        header = re.fullmatch(r"\s*Quartus Prime Version\s+(.+?)\s*", line)
        if header is not None:
            raw_versions.append(header.group(1))

    if not raw_versions:
        raise AuditError(
            "assembly version: expected one unambiguous Quartus version line"
        )
    versions = sorted(
        {validate_version(value, "assembly version") for value in raw_versions}
    )
    if len(versions) != 1:
        raise AuditError(
            "assembly version: expected one unambiguous Quartus version line"
        )
    return versions[0]


def unique_title(lines: Sequence[str], aliases: Iterable[str], label: str) -> int:
    wanted = {norm(alias) for alias in aliases}
    found = []
    for index, line in enumerate(lines):
        row = cells(line)
        if row is not None and len(row) == 1 and norm(row[0]) in wanted:
            found.append(index)
    if len(found) != 1:
        raise AuditError(f"{label}: expected exactly one report section")
    return found[0]


def key_value_section(
    lines: Sequence[str], aliases: Iterable[str], label: str
) -> List[List[str]]:
    title_index = unique_title(lines, aliases, label)
    rows: List[List[str]] = []
    for line in lines[title_index + 1 :]:
        row = cells(line)
        if row is None:
            continue
        if len(row) == 1:
            if rows:
                break
            continue
        if len(row) != 2:
            if rows:
                break
            continue
        rows.append(row)
    if not rows:
        raise AuditError(f"{label}: report section is empty")
    return rows


def row_scalar(rows: Sequence[Sequence[str]], aliases: Iterable[str], label: str) -> str:
    wanted = {norm(alias) for alias in aliases}
    found = [row[1].strip() for row in rows if len(row) == 2 and norm(row[0]) in wanted]
    unique = sorted(set(found))
    if len(unique) != 1 or not unique[0]:
        raise AuditError(f"{label}: expected one unambiguous value, found {unique!r}")
    return unique[0]


def validate_expected_identity(identity: Dict[str, str], kind: str) -> None:
    for field, expected in EXPECTED.items():
        if identity[field] != expected:
            raise AuditError(f"{kind} {field} is {identity[field]!r}, expected {expected!r}")


def validate_synthesis_report(text: str) -> Dict[str, str]:
    """Validate the genuine map.rpt summary and 3-column Settings device row."""

    lines = text.splitlines()
    summary = key_value_section(
        lines, ("Analysis & Synthesis Summary",), "synthesis summary"
    )
    status = row_scalar(
        summary, ("Analysis & Synthesis Status",), "synthesis status"
    )
    if re.match(r"^Successful(?:\s|$|-)", status) is None:
        raise AuditError(f"synthesis status is not successful: {status}")
    version = validate_version(
        row_scalar(summary, ("Quartus Prime Version",), "synthesis version"),
        "synthesis version",
    )
    identity = {
        "revision": row_scalar(summary, ("Revision Name",), "synthesis revision"),
        "top_level": row_scalar(
            summary,
            ("Top-level Entity Name", "Top Level Entity Name"),
            "synthesis top level",
        ),
        "family": row_scalar(summary, ("Family",), "synthesis family"),
    }

    settings_index = unique_title(
        lines, ("Analysis & Synthesis Settings",), "synthesis settings"
    )
    header, rows, _ = table_after(lines, settings_index)
    if [norm(value) for value in header] != ["option", "setting", "default value"]:
        raise AuditError("synthesis settings: unknown table format")
    devices = sorted(
        {row[1].strip() for row in rows if len(row) == 3 and norm(row[0]) == "device"}
    )
    if len(devices) != 1 or not devices[0]:
        raise AuditError(f"synthesis device: expected one Settings value, found {devices!r}")
    identity["device"] = devices[0]
    validate_expected_identity(identity, "synthesis")
    return {"status": status, "version": version, **identity}


def validate_timing_report(text: str) -> Dict[str, str]:
    """Validate the genuine sta.rpt summary and successful completion message."""

    lines = text.splitlines()
    summary = key_value_section(
        lines,
        ("Timing Analyzer Summary", "TimeQuest Timing Analyzer Summary"),
        "timing analysis summary",
    )
    version = validate_version(
        row_scalar(summary, ("Quartus Prime Version",), "timing analysis version"),
        "timing analysis version",
    )
    identity = {
        "revision": row_scalar(summary, ("Revision Name",), "timing analysis revision"),
        "family": row_scalar(summary, ("Device Family",), "timing analysis family"),
        "device": row_scalar(summary, ("Device Name",), "timing analysis device"),
    }
    for field, expected in EXPECTED.items():
        if field == "top_level":
            continue
        if identity[field] != expected:
            raise AuditError(
                f"timing analysis {field} is {identity[field]!r}, expected {expected!r}"
            )
    completion_re = re.compile(
        r"^Info:\s+Quartus Prime Timing Analyzer was successful[.]\s+"
        r"0 errors,\s+[0-9]+ warnings?\s*$"
    )
    completions = sorted(
        {" ".join(line.split()) for line in lines if completion_re.fullmatch(line.strip())}
    )
    if len(completions) != 1:
        raise AuditError("timing analysis completion: expected one successful 0-error message")
    return {"status": completions[0], "version": version, **identity}


def validate_report(text: str, kind: str, status_aliases: Sequence[str]) -> Dict[str, str]:
    lines = text.splitlines()
    status = scalar(lines, status_aliases, f"{kind} status")
    if re.match(r"^Successful(?:\s|$|-)", status) is None:
        raise AuditError(f"{kind} status is not successful: {status}")
    if kind == "assembly":
        version = validate_assembler_version(lines)
    else:
        version = scalar(
            lines,
            ("Quartus Prime Version", "Quartus Version"),
            f"{kind} version",
        )
        version = validate_version(version, f"{kind} version")
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
        "ram_blocks": (("Total RAM Blocks",), True),
        "plls": (("Total PLLs",), True),
    }
    result = {}
    for label, (aliases, require_available) in specs.items():
        result[label] = parse_used_available(
            scalar(lines, aliases, f"fit {label}"), label, require_available
        )
    return result


def ip_license_summary(synthesis_text: str) -> Dict[str, object]:
    """Parse Quartus' native IP inventory and its evaluation-mode setting.

    Intel documents the Analysis & Synthesis IP Cores Summary as the report
    that exposes each discovered IP core's License Type.  Swan Song uses only
    built-in RAM, PLL, and DDIO functions whose expected candidate report rows
    say ``N/A``.  Any other license value is retained as a failed candidate gate;
    it is never silently interpreted as a production grant.
    """

    lines = synthesis_text.splitlines()
    settings_index = unique_title(
        lines, ("Analysis & Synthesis Settings",), "synthesis settings"
    )
    settings_header, settings_rows, _ = table_after(lines, settings_index)
    if [norm(value) for value in settings_header] != [
        "option",
        "setting",
        "default value",
    ]:
        raise AuditError("synthesis settings: unknown table format")
    evaluation_settings = [
        row[1].strip()
        for row in settings_rows
        if len(row) == 3 and norm(row[0]) == "intel fpga ip evaluation mode"
    ]
    if len(evaluation_settings) != 1 or evaluation_settings[0] not in (
        "Disable",
        "Enable",
    ):
        raise AuditError(
            "Intel FPGA IP Evaluation Mode: expected one Enable/Disable setting"
        )

    title_index = unique_title(
        lines,
        ("Analysis & Synthesis IP Cores Summary",),
        "synthesis IP cores summary",
    )
    header, rows, _ = table_after(lines, title_index)
    if tuple(norm(value) for value in header) != IP_LICENSE_HEADER or not rows:
        raise AuditError("synthesis IP cores summary: unknown or empty table")

    entries: List[Dict[str, str]] = []
    for row in rows:
        if len(row) != len(IP_LICENSE_HEADER) or any(not value.strip() for value in row):
            raise AuditError("synthesis IP cores summary contains a ragged or empty row")
        entries.append(
            {
                field.replace(" ", "_"): value.strip()
                for field, value in zip(IP_LICENSE_HEADER, row)
            }
        )
    non_n_a = [entry for entry in entries if entry["license_type"] != "N/A"]
    return {
        "evaluation_mode_setting": evaluation_settings[0],
        "ip_cores": entries,
        "non_n_a_license_count": len(non_n_a),
        "non_n_a_license_entries": non_n_a,
    }


def assembler_generated_files(assembly_text: str) -> List[str]:
    """Require the normal SOF/RBF names from the native Assembler report."""

    lines = assembly_text.splitlines()
    title_index = unique_title(
        lines, ("Assembler Generated Files",), "assembler generated files"
    )
    found: List[str] = []
    saw_header = False
    for line in lines[title_index + 1 :]:
        row = cells(line)
        if row is None:
            if found and line.strip().startswith("+"):
                break
            continue
        if len(row) != 1:
            if found:
                raise AuditError("assembler generated files contains a ragged row")
            continue
        value = row[0].strip()
        if norm(value) == "file name":
            if saw_header or found:
                raise AuditError("assembler generated files has a duplicate header")
            saw_header = True
            continue
        if not saw_header:
            continue
        found.append(Path(value).name)
    if found != ["ap_core.sof", "ap_core.rbf"]:
        raise AuditError(
            "assembler generated files must be exactly ap_core.sof and ap_core.rbf"
        )
    return found


def table_after(lines: Sequence[str], title_index: int) -> Tuple[List[str], List[List[str]], bool]:
    header: Optional[List[str]] = None
    rows: List[List[str]] = []
    no_paths = False
    for line in lines[title_index + 1 :]:
        # Quartus emits this sentinel as plain text rather than a semicolon
        # table cell, so it must be recognized before cells() discards it.
        if norm(line.strip()) == "no paths to report":
            no_paths = True
            continue
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
    if cleaned.startswith("-"):
        raise AuditError(f"negative {label}: {value!r}")
    return parsed


def check_timing_summary(sta_text: str) -> Dict[str, object]:
    """Validate the native Quartus 21.1 check_timing table, not its exit code."""

    lines = sta_text.splitlines()
    headers = []
    for index, line in enumerate(lines):
        row = cells(line)
        if row is not None and [item.strip() for item in row] == [
            "Check",
            "Number of Issues Found",
        ]:
            headers.append(index)
    if len(headers) != 1:
        raise AuditError(
            "check_timing Summary: expected exactly one native 2-column table"
        )

    rows: List[List[str]] = []
    for line in lines[headers[0] + 1 :]:
        stripped = line.strip()
        if stripped.startswith("+"):
            if rows:
                break
            continue
        row = cells(line)
        if row is None:
            if rows:
                break
            continue
        if len(row) != 2:
            raise AuditError("check_timing Summary contains a ragged row")
        rows.append([item.strip() for item in row])

    expected = [[name, "0"] for name in CHECK_TIMING_ROWS]
    if rows != expected:
        raise AuditError(
            f"check_timing Summary rows are missing, reordered, unknown, or nonzero: {rows}"
        )
    marker_lines = [
        index for index, line in enumerate(lines) if line.strip() == CHECK_TIMING_MARKER
    ]
    if len(marker_lines) != 1 or marker_lines[0] <= headers[0]:
        raise AuditError("check_timing zero-findings marker is missing or misplaced")
    return {
        "checks": list(CHECK_TIMING_ROWS),
        "findings": 0,
        "marker": CHECK_TIMING_MARKER,
    }


def timing_summary(sta_text: str) -> Dict[str, object]:
    lines = sta_text.splitlines()
    per_analysis: Dict[str, List[Dict[str, object]]] = {name: [] for name in ANALYSES}
    title_re = re.compile(
        r"^(.+ Model) (Setup|Hold|Recovery|Removal|Minimum Pulse Width) Summary$",
        re.I,
    )
    for index, line in enumerate(lines):
        row = cells(line)
        if row is None or len(row) != 1:
            continue
        match = title_re.match(row[0].strip())
        if match is None:
            continue
        corner = match.group(1)
        analysis = match.group(2).lower().replace(" ", "_")
        if any(entry["corner"] == corner for entry in per_analysis[analysis]):
            raise AuditError(f"duplicate {analysis} summary for {corner}")
        header, rows, no_paths = table_after(lines, index)
        normalized = [norm(item) for item in header]
        slack_indexes = [i for i, item in enumerate(normalized) if item in ("slack", "worst case slack")]
        if no_paths:
            if rows or analysis in ("setup", "hold", "minimum_pulse_width"):
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
        if len(tns_indexes) != 1:
            raise AuditError(f"unknown {analysis} TNS table format for {corner}")
        slacks: List[Decimal] = []
        tns_values: List[Decimal] = []
        for data in rows:
            if len(data) != len(header):
                raise AuditError(f"ragged {analysis} timing row for {corner}")
            slacks.append(decimal_value(data[slack_index], f"{analysis} slack"))
            for tns_index in tns_indexes:
                tns_values.append(decimal_value(data[tns_index], f"{analysis} TNS"))
        per_analysis[analysis].append(
            {
                "corner": corner,
                "path_count": len(rows),
                "worst_slack": str(min(slacks)),
                "worst_tns": str(min(tns_values)) if tns_values else None,
            }
        )
    for analysis in ANALYSES:
        observed_corners = {
            str(entry["corner"]) for entry in per_analysis[analysis]
        }
        if observed_corners != set(EXPECTED_TIMING_CORNERS):
            raise AuditError(
                f"missing or unexpected {analysis} timing corners: "
                f"{sorted(observed_corners)}"
            )

    clock_title = unique_title(lines, ("Clocks",), "clocks")
    header, rows, _ = table_after(lines, clock_title)
    normalized = [norm(item) for item in header]
    indexes = [i for i, item in enumerate(normalized) if item in ("clock", "clock name")]
    if len(indexes) != 1 or not rows:
        raise AuditError("unknown Clocks report format")
    clock_names = sorted({row[indexes[0]] for row in rows if len(row) == len(header)})
    missing_clocks = sorted(set(REQUIRED_CLOCKS) - set(clock_names))
    if missing_clocks:
        raise AuditError(f"missing required clocks: {', '.join(missing_clocks)}")

    # The native report contains one summary and the required detailed
    # `report_ucp` append contains a second.  Require both exact tables and
    # exact equality instead of silently selecting one and ignoring a
    # contradictory appended diagnostic.
    unconstrained_titles = []
    for index, line in enumerate(lines):
        row = cells(line)
        if row == ["Unconstrained Paths Summary"]:
            unconstrained_titles.append(index)
    if len(unconstrained_titles) != 2:
        raise AuditError(
            "unconstrained paths summary: expected exactly two report sections"
        )
    unconstrained_tables: List[Dict[str, Dict[str, int]]] = []
    for unconstrained_title in unconstrained_titles:
        header, rows, _ = table_after(lines, unconstrained_title)
        normalized = [norm(item) for item in header]
        if normalized != ["property", "setup", "hold"] or not rows:
            raise AuditError("unknown Unconstrained Paths Summary format")
        counts: Dict[str, Dict[str, int]] = {}
        for row in rows:
            if len(row) != 3:
                raise AuditError("ragged Unconstrained Paths Summary row")
            property_name = norm(row[0])
            if property_name not in UNCONSTRAINED_PROPERTIES or property_name in counts:
                raise AuditError(
                    f"unknown or duplicate unconstrained property: {property_name!r}"
                )
            values = {}
            for value_index, analysis in ((1, "setup"), (2, "hold")):
                raw_count = row[value_index].replace(",", "").strip()
                if not raw_count.isdigit():
                    raise AuditError(
                        f"malformed unconstrained {analysis} count: {raw_count!r}"
                    )
                values[analysis] = int(raw_count)
            counts[property_name] = values
        if set(counts) != set(UNCONSTRAINED_PROPERTIES) or any(
            value for properties in counts.values() for value in properties.values()
        ):
            raise AuditError(f"missing or nonzero unconstrained path counts: {counts}")
        unconstrained_tables.append(counts)
    if unconstrained_tables[0] != unconstrained_tables[1]:
        raise AuditError("native and detailed unconstrained path summaries differ")
    counts = unconstrained_tables[0]

    timing_gate_lines = [
        index
        for index, line in enumerate(lines)
        if line.strip() == TIMING_GATE_MARKER
    ]
    if len(timing_gate_lines) != 1:
        raise AuditError("four-corner timing-gate zero-findings marker is missing")
    pulse_gate_lines = [
        index
        for index, line in enumerate(lines)
        if line.strip() == MIN_PULSE_GATE_MARKER
    ]
    if len(pulse_gate_lines) != 1:
        raise AuditError("minimum-pulse-width zero-findings marker is missing")
    dq_corners: Dict[str, Dict[str, str]] = {}
    for line in lines:
        match = SDRAM_DQ_MARKER_RE.fullmatch(line.strip())
        if match is None:
            continue
        corner_key = "|".join(match.group(1, 2, 3))
        if corner_key in dq_corners:
            raise AuditError(f"duplicate SDRAM DQ timing marker: {corner_key}")
        setup = decimal_value(match.group(4), f"SDRAM DQ setup slack at {corner_key}")
        hold = decimal_value(match.group(5), f"SDRAM DQ hold slack at {corner_key}")
        dq_corners[corner_key] = {
            "setup_paths": 16,
            "setup_worst": str(setup),
            "hold_paths": 16,
            "hold_worst": str(hold),
        }
    expected_dq_corners = {
        "slow|85|1100",
        "slow|0|1100",
        "fast|85|1100",
        "fast|0|1100",
    }
    if set(dq_corners) != expected_dq_corners:
        raise AuditError(
            "missing or unexpected SDRAM DQ timing markers: "
            f"{sorted(dq_corners)}"
        )

    return {
        "analyses": per_analysis,
        "clocks": {"observed": clock_names, "required": list(REQUIRED_CLOCKS)},
        "check_timing": check_timing_summary(sta_text),
        "signoff_gate": {
            "corners": list(EXPECTED_TIMING_CORNERS),
            "analyses": list(TIMING_PATH_ANALYSES),
            "negative_paths": 0,
            "marker": TIMING_GATE_MARKER,
            "minimum_pulse_width": {
                "worst_checks": 4,
                "negative_checks": 0,
                "marker": MIN_PULSE_GATE_MARKER,
            },
        },
        "sdram_dq": {
            "corners": {key: dq_corners[key] for key in sorted(dq_corners)},
            "setup_multicycle_end": 2,
            "hold_multicycle_end": 0,
        },
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


def numbered_warnings(
    texts: Dict[str, str], warning_id: int
) -> List[Dict[str, object]]:
    """Inventory a stable Quartus warning ID without guessing at its details."""

    pattern = re.compile(rf"\bWarning\s*\(\s*{warning_id}\s*\)\s*:", re.I)
    inventory = []
    for relative in sorted(texts):
        for line_number, line in enumerate(texts[relative].splitlines(), 1):
            if pattern.search(line):
                inventory.append(
                    {
                        "artifact": relative,
                        "line": line_number,
                        "message": " ".join(line.split()),
                    }
                )
    return inventory


def numbered_infos(
    texts: Dict[str, str], info_id: int
) -> List[Dict[str, object]]:
    """Inventory a stable Quartus info ID without guessing at its details."""

    pattern = re.compile(rf"\bInfo\s*\(\s*{info_id}\s*\)\s*:", re.I)
    inventory = []
    for relative in sorted(texts):
        for line_number, line in enumerate(texts[relative].splitlines(), 1):
            if pattern.search(line):
                inventory.append(
                    {
                        "artifact": relative,
                        "line": line_number,
                        "message": " ".join(line.split()),
                    }
                )
    return inventory


def message_warnings(
    texts: Dict[str, str], phrase: str
) -> List[Dict[str, object]]:
    """Inventory an unnumbered Quartus warning by its stable message phrase."""

    pattern = re.compile(re.escape(phrase), re.I)
    inventory = []
    for relative in sorted(texts):
        for line_number, line in enumerate(texts[relative].splitlines(), 1):
            if pattern.search(line):
                inventory.append(
                    {
                        "artifact": relative,
                        "line": line_number,
                        "message": " ".join(line.split()),
                    }
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
    if result.get("workflow_repository") != WORKFLOW_REPOSITORY:
        raise AuditError("build metadata workflow_repository mismatch")
    if result.get("workflow_path") != WORKFLOW_PATH:
        raise AuditError("build metadata workflow_path mismatch")
    if result.get("workflow_sha") != result["source_commit"]:
        raise AuditError("build metadata workflow_sha mismatch")
    if re.fullmatch(r"[1-9][0-9]*", result.get("workflow_run_id", "")) is None:
        raise AuditError("invalid workflow_run_id metadata")
    if re.fullmatch(
        r"[1-9][0-9]*", result.get("workflow_run_attempt", "")
    ) is None:
        raise AuditError("invalid workflow_run_attempt metadata")
    if result.get("workflow_job") != WORKFLOW_JOB:
        raise AuditError("build metadata workflow_job mismatch")
    if re.fullmatch(
        r"[0-9a-f]{32}", result.get("workflow_job_nonce", "")
    ) is None:
        raise AuditError("invalid workflow_job_nonce metadata")
    if set(result) != {
        "source_commit",
        "source_date_epoch",
        *WORKFLOW_METADATA_FIELDS,
        *expected,
    }:
        raise AuditError("unknown or missing build metadata fields")
    return result


def audit(artifact_directory: Path) -> Dict[str, object]:
    root = artifact_directory.resolve(strict=True)
    if not root.is_dir():
        raise AuditError(f"not an artifact directory: {root}")
    paths = {
        relative: safe_input(root, relative) for relative in REQUIRED_ARTIFACTS
    }
    artifacts = {relative: digest(path) for relative, path in sorted(paths.items())}
    texts = {
        relative: read_text(path, vendor_report=relative in VENDOR_REPORTS)
        for relative, path in paths.items()
        if relative != "output_files/ap_core.rbf"
    }

    toolchain_version = validate_version(
        texts["toolchain-version.txt"], "toolchain-version.txt"
    )
    metadata = parse_metadata(texts["build-metadata.txt"])
    try:
        validated_container = container_provenance.validate_provenance(
            paths["container-provenance.json"], paths["container-packages.tsv"]
        )
    except container_provenance.ProvenanceError as error:
        raise AuditError(f"invalid container provenance: {error}") from error
    rbf_hash = artifacts["output_files/ap_core.rbf"]["sha256"]
    expected_hash_line = f"{rbf_hash}  /artifacts/output_files/ap_core.rbf"
    if texts["ap_core.rbf.sha256"].strip() != expected_hash_line:
        raise AuditError("ap_core.rbf.sha256 does not match the RBF")

    synthesis = validate_synthesis_report(texts[REPORTS["synthesis"][0]])
    timing_report = validate_timing_report(texts[REPORTS["timing_analysis"][0]])
    for parsed in (synthesis, timing_report):
        if parsed["version"] != toolchain_version:
            raise AuditError("toolchain and report Quartus version lines disagree")

    flow = {
        "synthesis": {
            "status": synthesis["status"],
            "version": synthesis["version"],
        },
        "timing_analysis": {
            "status": timing_report["status"],
            "version": timing_report["version"],
        },
    }
    report_identity = None
    for kind in IDENTITY_REPORT_KINDS:
        relative, status_aliases = REPORTS[kind]
        parsed = validate_report(texts[relative], kind, status_aliases)
        if parsed["version"] != toolchain_version:
            raise AuditError("toolchain and report Quartus version lines disagree")
        identity = {key: parsed[key] for key in EXPECTED}
        if report_identity is not None and identity != report_identity:
            raise AuditError("report identities disagree")
        report_identity = identity
        flow[kind] = {"status": parsed["status"], "version": parsed["version"]}

    resources = resource_summary(texts[REPORTS["fit"][0]])
    timing = timing_summary(texts[REPORTS["timing_analysis"][0]])
    ip_licensing = ip_license_summary(texts[REPORTS["synthesis"][0]])
    generated_files = assembler_generated_files(texts[REPORTS["assembly"][0]])
    warnings = critical_warnings(texts)
    connectivity_warnings = numbered_warnings(texts, 12241)
    pll_self_reset_warnings = numbered_warnings(texts, 15069)
    pll_reset_port_warnings = message_warnings(
        texts, "RST port on the PLL is not properly connected"
    )
    constraint_replacement_warnings = numbered_warnings(texts, 332054)
    evaluation_warnings = []
    for warning_id in EVALUATION_WARNING_IDS:
        evaluation_warnings.extend(numbered_warnings(texts, warning_id))
    evaluation_warnings.sort(
        key=lambda entry: (str(entry["artifact"]), int(entry["line"]), str(entry["message"]))
    )
    time_limited_infos = []
    for info_id in TIME_LIMITED_INFO_IDS:
        time_limited_infos.extend(numbered_infos(texts, info_id))
    time_limited_infos.sort(
        key=lambda entry: (str(entry["artifact"]), int(entry["line"]), str(entry["message"]))
    )
    no_critical = not warnings
    no_connectivity_warnings = not connectivity_warnings
    pll_self_reset_configured = not pll_self_reset_warnings
    pll_reset_port_connected = not pll_reset_port_warnings
    io_delay_constraints_preserved = not constraint_replacement_warnings
    no_evaluation_or_time_limited_ip = (
        ip_licensing["non_n_a_license_count"] == 0
        and not evaluation_warnings
        and not time_limited_infos
        and generated_files == ["ap_core.sof", "ap_core.rbf"]
    )
    ram_block_headroom = (
        resources["ram_blocks"]["used"] <= MAX_CANDIDATE_RAM_BLOCKS
    )
    if connectivity_warnings:
        try:
            connectivity_review = connectivity_policy.review_report(
                texts[REPORTS["synthesis"][0]], SOURCE_ROOT
            )
        except connectivity_policy.PolicyError as error:
            raise AuditError(f"invalid connectivity-warning policy: {error}") from error
    else:
        connectivity_review = {
            "accepted": True,
            "status": "not_required_no_warning_12241",
            "warning_id": 12241,
        }
    if connectivity_warnings:
        expected_summary = connectivity_review["observed"]["summary_message"]
        unexpected_summaries = [
            entry
            for entry in connectivity_warnings
            if entry["message"] != expected_summary
        ]
        connectivity_review["summary_entries"] = {
            "count": len(connectivity_warnings),
            "unexpected": unexpected_summaries,
        }
        if unexpected_summaries:
            connectivity_review["accepted"] = False
            connectivity_review["status"] = "rejected_summary_entries"
    connectivity_review_pass = connectivity_review["accepted"] is True
    gates = {
        "assembly_success": True,
        "compressed_bitstream": None,
        "dock_hardware": False,
        "fit_success": True,
        "flow_success": True,
        "hold_timing": True,
        "io_delay_constraints_preserved": io_delay_constraints_preserved,
        "no_critical_warnings": no_critical,
        "no_evaluation_or_time_limited_ip": no_evaluation_or_time_limited_ip,
        "no_connectivity_warnings": no_connectivity_warnings,
        "connectivity_warnings_reviewed": connectivity_review_pass,
        "no_unconstrained_paths": True,
        "pll_self_reset_configured": pll_self_reset_configured,
        "pll_reset_port_connected": pll_reset_port_connected,
        "pocket_hardware": False,
        "ram_block_headroom": ram_block_headroom,
        "recovery_timing": True,
        "removal_timing": True,
        "setup_timing": True,
        "timing_analysis_success": True,
    }
    return {
        "quartus_audit": {
            "magic": MAGIC,
            "audit_pass": no_critical
            and connectivity_review_pass
            and pll_self_reset_configured
            and pll_reset_port_connected
            and io_delay_constraints_preserved
            and no_evaluation_or_time_limited_ip
            and ram_block_headroom,
            "release_eligible": False,
            "identity": report_identity,
            "provenance": metadata,
            "container_provenance": validated_container,
            "artifacts": artifacts,
            "flow": flow,
            "resources": resources,
            "timing": timing,
            "ip_licensing": {
                **ip_licensing,
                "assembler_generated_files": generated_files,
                "evaluation_warning_ids": list(EVALUATION_WARNING_IDS),
                "evaluation_warning_count": len(evaluation_warnings),
                "evaluation_warning_entries": evaluation_warnings,
                "time_limited_info_ids": list(TIME_LIMITED_INFO_IDS),
                "time_limited_info_count": len(time_limited_infos),
                "time_limited_info_entries": time_limited_infos,
            },
            "critical_warnings": {"count": len(warnings), "entries": warnings},
            "connectivity_warnings": {
                "warning_id": 12241,
                "count": len(connectivity_warnings),
                "entries": connectivity_warnings,
                "review_required": bool(connectivity_warnings)
                and not connectivity_review_pass,
                "exact_review": connectivity_review,
            },
            "pll_self_reset_warnings": {
                "warning_id": 15069,
                "count": len(pll_self_reset_warnings),
                "entries": pll_self_reset_warnings,
            },
            "pll_reset_port_warnings": {
                "message": "RST port on the PLL is not properly connected",
                "count": len(pll_reset_port_warnings),
                "entries": pll_reset_port_warnings,
            },
            "constraint_replacement_warnings": {
                "warning_id": 332054,
                "count": len(constraint_replacement_warnings),
                "entries": constraint_replacement_warnings,
            },
            "candidate_gates": gates,
            "limitations": [
                "Candidate evidence only; this schema is not SWAN_SONG_RELEASE_EVIDENCE_V1.",
                "Pocket and Dock hardware gates are always false and require physical testing.",
                "Compressed-bitstream acceptance is not inferred from an RBF filename.",
                "Warning 12241 passes only when every detailed map-report row "
                "matches the source-bound exact reviewed set; no warning ID or "
                "count is broadly waived.",
                "Warning 15069 always fails because Quartus reports that PLL "
                "self-reset cannot function correctly without a valid gated "
                "lock counter.",
                "The unnumbered PLL RST-port warning always fails because it "
                "means the generated PLL does not see a valid deliberate reset.",
                "Warning 332054 always fails because it proves one or more "
                "SDRAM input/output delay assignments were replaced.",
                "The IP-license gate requires every native Analysis & Synthesis "
                "IP Cores Summary row to report License Type N/A, rejects known "
                "OpenCore Plus/time-limited warning and info IDs, and requires ordinary "
                "ap_core.sof plus ap_core.rbf Assembler outputs. This is build "
                "evidence, not a legal interpretation of Intel's agreements.",
                f"A candidate may use at most {MAX_CANDIDATE_RAM_BLOCKS} physical "
                "M10K blocks. The source contract separately proves the disabled "
                "Memories boundary gate; logical memory-bit percentage is not a "
                "substitute for this fitted-resource gate.",
                "Report parsing is pinned to Quartus 21.1.1 Build 850 and has "
                "been exercised against genuine engineering-fit reports; no "
                "current-source release candidate is inferred.",
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
        failed_review_gates = [
            name
            for name in (
                "no_critical_warnings",
                "connectivity_warnings_reviewed",
                "pll_self_reset_configured",
                "pll_reset_port_connected",
                "io_delay_constraints_preserved",
                "no_evaluation_or_time_limited_ip",
                "ram_block_headroom",
            )
            if result["candidate_gates"][name] is not True
        ]
        print(
            "quartus_fit_audit.py: candidate review gates failed "
            f"({', '.join(failed_review_gates)}); candidate written to {output}",
            file=sys.stderr,
        )
        return 1
    print(f"Quartus candidate audit passed (non-release evidence): {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
