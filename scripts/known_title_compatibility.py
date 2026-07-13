#!/usr/bin/env python3
"""Validate the known-title catalogue and private Pocket/Dock evidence.

The checked-in catalogue is deliberately a pending template: it contains no
commercial ROM identity and no claimed hardware result.  A tester copies it,
fills the run/result fields, and verifies the copy against the immutable
catalogue.  Verification proves schema and artifact integrity, not the truth
of a human observation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
from typing import Any


MAGIC = "SWAN_SONG_KNOWN_TITLE_COMPATIBILITY_V1"
CATALOGUE_REVISION = 1
REQUIRED_FIRMWARE = "2.6.0"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")
UTC_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z"
)

REQUIRED_COMMERCIAL_IDS = (
    "cho-denki-crash",
    "meta-communication-name-select",
    "star-hearts-trial-rain",
    "final-lap-2000-track",
    "one-piece-grand-battle-video",
    "makaimura-map-scroll",
    "romancing-saga-text-box",
    "digimon-battle-spirit-1.5-video",
    "super-robot-wars-compact-battle",
    "engacho-eeprom-persistence",
    "another-heaven-eeprom-persistence",
    "star-hearts-save-copy-protection",
)

REQUIRED_OPEN_IDS = (
    "open-80186-quirks",
    "open-interrupts",
    "open-internal-eeprom",
    "generated-shift-jis-glyphs",
    "generated-medium-sram",
)

PRIMARY_SOURCE_PREFIXES = (
    "https://github.com/MiSTer-devel/WonderSwan_MiSTer/issues/",
    "https://github.com/agg23/openfpga-wonderswan/issues/",
    "https://github.com/asiekierka/ws-test-suite/",
    "https://github.com/WonderfulToolchain/target-wswan-examples/",
    "https://github.com/OpenWitch/AthenaOS/",
    "https://codeberg.org/WonderfulToolchain/target-wswan-syslibs/",
    "https://littlelimit.net/",
)

IMMUTABLE_CASE_FIELDS = {
    "id",
    "class",
    "title",
    "system",
    "source_urls",
    "issue_signature",
    "scenarios",
    "operator_steps_required",
    "reference_requirement",
    "mode_evidence_requirements",
    "fixture_path",
    "fixture_sha256",
}

CASE_FIELDS = IMMUTABLE_CASE_FIELDS | {
    "owner_rom_sha256",
    "operator_steps",
    "reference",
    "modes",
}

RUN_FIELDS = {
    "run_id",
    "created_at",
    "operator",
    "core_commit",
    "raw_rbf_sha256",
    "firmware_version",
    "pocket_hardware_revision",
    "dock_hardware_revision",
}

ARTIFACT_FIELDS = {
    "id",
    "kind",
    "path",
    "label",
    "captured_at",
    "size",
    "sha256",
}

ARTIFACT_KINDS = {
    "pocket_screenshot",
    "photo",
    "video",
    "save",
    "log",
    "reference_photo",
    "reference_video",
}


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{where} must be an object with string keys")
    return value


def _array(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array")
    return value


def _keys(value: dict[str, Any], where: str, expected: set[str]) -> None:
    missing = expected - value.keys()
    unknown = value.keys() - expected
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise ValueError(f"{where} has invalid members ({'; '.join(details)})")


def _text(value: Any, where: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{where} must be a nonempty string of at most {maximum} characters")
    if any(ord(char) < 0x20 for char in value):
        raise ValueError(f"{where} contains a control character")
    return value


def _id(value: Any, where: str) -> str:
    result = _text(value, where, 64)
    if not ID_RE.fullmatch(result):
        raise ValueError(f"{where} must match {ID_RE.pattern}")
    return result


def _utc(value: Any, where: str) -> str:
    result = _text(value, where, 20)
    if not UTC_RE.fullmatch(result):
        raise ValueError(f"{where} must be UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        dt.datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(f"{where} is not a valid UTC timestamp") from error
    return result


def _load(path: pathlib.Path, where: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{where} must be a regular non-symlink file: {path}")
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), where)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {where}: {error}") from error


def _body(document: dict[str, Any], where: str) -> dict[str, Any]:
    _keys(document, where, {"known_title_compatibility"})
    body = _object(document["known_title_compatibility"], f"{where}.known_title_compatibility")
    _keys(
        body,
        f"{where}.known_title_compatibility",
        {
            "magic",
            "catalogue_revision",
            "research_date",
            "required_firmware_version",
            "run",
            "cases",
            "artifacts",
            "attestation",
        },
    )
    if body["magic"] != MAGIC:
        raise ValueError(f"{where} has wrong magic")
    if body["catalogue_revision"] != CATALOGUE_REVISION:
        raise ValueError(f"{where} has unsupported catalogue revision")
    if body["research_date"] != "2026-07-13":
        raise ValueError(f"{where} has unreviewed research date")
    if body["required_firmware_version"] != REQUIRED_FIRMWARE:
        raise ValueError(f"{where} has unreviewed firmware version")
    return body


def _validate_scenarios(value: Any, where: str) -> None:
    scenarios = _array(value, where)
    if not scenarios:
        raise ValueError(f"{where} must contain at least one scenario")
    scenario_ids: set[str] = set()
    for index, raw in enumerate(scenarios):
        item_where = f"{where}[{index}]"
        item = _object(raw, item_where)
        _keys(item, item_where, {"id", "preconditions", "steps", "expected"})
        scenario_id = _id(item["id"], f"{item_where}.id")
        if scenario_id in scenario_ids:
            raise ValueError(f"duplicate scenario id {scenario_id}")
        scenario_ids.add(scenario_id)
        for field in ("preconditions", "steps"):
            entries = _array(item[field], f"{item_where}.{field}")
            if not entries:
                raise ValueError(f"{item_where}.{field} must not be empty")
            for entry_index, entry in enumerate(entries):
                _text(entry, f"{item_where}.{field}[{entry_index}]")
        _text(item["expected"], f"{item_where}.expected")


def _validate_requirements(value: Any, where: str) -> None:
    requirements = _array(value, where)
    if not requirements:
        raise ValueError(f"{where} must not be empty")
    for index, raw in enumerate(requirements):
        item_where = f"{where}[{index}]"
        item = _object(raw, item_where)
        _keys(item, item_where, {"kinds", "minimum"})
        kinds = _array(item["kinds"], f"{item_where}.kinds")
        if not kinds or any(kind not in ARTIFACT_KINDS for kind in kinds):
            raise ValueError(f"{item_where}.kinds contains an unsupported artifact kind")
        minimum = item["minimum"]
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            raise ValueError(f"{item_where}.minimum must be a positive integer")


def _validate_case_static(item: dict[str, Any], where: str, root: pathlib.Path) -> str:
    _keys(item, where, CASE_FIELDS)
    case_id = _id(item["id"], f"{where}.id")
    case_class = item["class"]
    if case_class not in {"commercial", "open_sanity"}:
        raise ValueError(f"{where}.class must be commercial or open_sanity")
    _text(item["title"], f"{where}.title", 255)
    if item["system"] not in {"ws", "wsc"}:
        raise ValueError(f"{where}.system must be ws or wsc")
    urls = _array(item["source_urls"], f"{where}.source_urls")
    if not urls:
        raise ValueError(f"{where}.source_urls must not be empty")
    for index, url in enumerate(urls):
        source = _text(url, f"{where}.source_urls[{index}]")
        if not source.startswith(PRIMARY_SOURCE_PREFIXES):
            raise ValueError(f"{where}.source_urls[{index}] is not an approved primary source")
    _text(item["issue_signature"], f"{where}.issue_signature")
    _validate_scenarios(item["scenarios"], f"{where}.scenarios")
    if not isinstance(item["operator_steps_required"], bool):
        raise ValueError(f"{where}.operator_steps_required must be boolean")
    _text(item["reference_requirement"], f"{where}.reference_requirement")
    _validate_requirements(
        item["mode_evidence_requirements"], f"{where}.mode_evidence_requirements"
    )

    fixture_path = item["fixture_path"]
    fixture_sha256 = item["fixture_sha256"]
    if case_class == "commercial":
        if fixture_path is not None or fixture_sha256 is not None:
            raise ValueError(f"{where} commercial case must not embed a fixture identity")
    else:
        relative = pathlib.PurePosixPath(_text(fixture_path, f"{where}.fixture_path"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{where}.fixture_path must be a repository-relative safe path")
        if not isinstance(fixture_sha256, str) or not SHA256_RE.fullmatch(fixture_sha256):
            raise ValueError(f"{where}.fixture_sha256 must be lowercase SHA-256")
        path = root / pathlib.Path(relative)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{where}.fixture_path is missing or not a regular file")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != fixture_sha256:
            raise ValueError(f"{where}.fixture SHA-256 mismatch")
    return case_id


def _validate_pending_fields(item: dict[str, Any], where: str) -> None:
    if item["owner_rom_sha256"] is not None:
        raise ValueError(f"{where}.owner_rom_sha256 must be null in the checked-in template")
    if item["operator_steps"] != []:
        raise ValueError(f"{where}.operator_steps must be empty in the checked-in template")
    if item["reference"] != {"source": None, "artifact_ids": [], "notes": None}:
        raise ValueError(f"{where}.reference must be pending in the checked-in template")
    modes = _object(item["modes"], f"{where}.modes")
    _keys(modes, f"{where}.modes", {"pocket", "dock"})
    pending = {
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "artifact_ids": [],
        "notes": None,
    }
    for name in ("pocket", "dock"):
        if modes[name] != pending:
            raise ValueError(f"{where}.modes.{name} must be pending in the checked-in template")


def validate_catalogue(path: pathlib.Path) -> dict[str, int]:
    """Validate the immutable pending catalogue and all open fixture hashes."""
    body = _body(_load(path, "catalogue"), "catalogue")
    run = _object(body["run"], "catalogue.run")
    _keys(run, "catalogue.run", RUN_FIELDS)
    if any(value is not None for value in run.values()):
        raise ValueError("catalogue.run must contain only null pending fields")
    if body["artifacts"] != []:
        raise ValueError("catalogue.artifacts must be empty")
    if body["attestation"] != {
        "physical_hardware_observed": None,
        "results_not_inferred_from_simulation": None,
        "reviewer": None,
        "reviewed_at": None,
    }:
        raise ValueError("catalogue.attestation must be pending")

    cases = _array(body["cases"], "catalogue.cases")
    ids: list[str] = []
    root = path.resolve().parent
    for index, raw in enumerate(cases):
        where = f"catalogue.cases[{index}]"
        item = _object(raw, where)
        ids.append(_validate_case_static(item, where, root))
        _validate_pending_fields(item, where)
    expected = list(REQUIRED_COMMERCIAL_IDS + REQUIRED_OPEN_IDS)
    if ids != expected:
        raise ValueError("catalogue does not contain the exact reviewed case list and order")
    return {
        "cases": len(ids),
        "commercial_cases": len(REQUIRED_COMMERCIAL_IDS),
        "open_sanity_cases": len(REQUIRED_OPEN_IDS),
    }


def _artifact_path(base: pathlib.Path, value: Any, where: str) -> pathlib.Path:
    relative = pathlib.PurePosixPath(_text(value, where))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{where} must be a safe manifest-relative path")
    path = base / pathlib.Path(relative)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{where} evidence file is missing or not a regular file: {path}")
    if path.stat().st_nlink != 1:
        raise ValueError(f"{where} evidence file must not be a hard link: {path}")
    resolved = path.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"{where} escapes the manifest directory") from error
    return resolved


def _validate_artifacts(
    raw_artifacts: Any, base: pathlib.Path
) -> tuple[dict[str, dict[str, Any]], str]:
    artifacts: dict[str, dict[str, Any]] = {}
    paths: set[pathlib.Path] = set()
    for index, raw in enumerate(_array(raw_artifacts, "manifest.artifacts")):
        where = f"manifest.artifacts[{index}]"
        item = _object(raw, where)
        _keys(item, where, ARTIFACT_FIELDS)
        artifact_id = _id(item["id"], f"{where}.id")
        if artifact_id in artifacts:
            raise ValueError(f"duplicate artifact id {artifact_id}")
        if item["kind"] not in ARTIFACT_KINDS:
            raise ValueError(f"{where}.kind is unsupported")
        _text(item["label"], f"{where}.label", 255)
        _utc(item["captured_at"], f"{where}.captured_at")
        if isinstance(item["size"], bool) or not isinstance(item["size"], int) or item["size"] < 1:
            raise ValueError(f"{where}.size must be a positive integer")
        if not isinstance(item["sha256"], str) or not SHA256_RE.fullmatch(item["sha256"]):
            raise ValueError(f"{where}.sha256 must be lowercase SHA-256")
        path = _artifact_path(base, item["path"], f"{where}.path")
        if path in paths:
            raise ValueError(f"evidence path reused by multiple artifacts: {path}")
        paths.add(path)
        data = path.read_bytes()
        if len(data) != item["size"]:
            raise ValueError(f"{where} evidence size mismatch")
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError(f"{where} evidence SHA-256 mismatch")
        if item["kind"] in {"video", "reference_video"}:
            suffix = path.suffix.casefold()
            valid = (
                suffix in {".mp4", ".mov"}
                and len(data) >= 12
                and data[4:8] == b"ftyp"
            ) or (
                suffix in {".mkv", ".webm"}
                and data.startswith(b"\x1aE\xdf\xa3")
            )
            if not valid:
                raise ValueError(
                    f"{where} {item['kind']} must be MP4/MOV/MKV/WebM evidence "
                    "with a matching media signature"
                )
        artifacts[artifact_id] = item
    digest = hashlib.sha256(
        json.dumps(raw_artifacts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return artifacts, digest


def _artifact_ids(value: Any, where: str, artifacts: dict[str, dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for index, raw in enumerate(_array(value, where)):
        artifact_id = _id(raw, f"{where}[{index}]")
        if artifact_id not in artifacts:
            raise ValueError(f"{where}[{index}] references unknown artifact {artifact_id}")
        if artifact_id in result:
            raise ValueError(f"{where} repeats artifact {artifact_id}")
        result.append(artifact_id)
    return result


def _requirements_met(
    requirements: list[dict[str, Any]],
    artifact_ids: list[str],
    artifacts: dict[str, dict[str, Any]],
    where: str,
) -> None:
    kinds = [artifacts[artifact_id]["kind"] for artifact_id in artifact_ids]
    for requirement in requirements:
        accepted = set(requirement["kinds"])
        count = sum(kind in accepted for kind in kinds)
        if count < requirement["minimum"]:
            raise ValueError(
                f"{where} requires at least {requirement['minimum']} artifact(s) of "
                f"{sorted(accepted)}"
            )


def _validate_run(body: dict[str, Any]) -> None:
    run = _object(body["run"], "manifest.run")
    _keys(run, "manifest.run", RUN_FIELDS)
    _id(run["run_id"], "manifest.run.run_id")
    _utc(run["created_at"], "manifest.run.created_at")
    _text(run["operator"], "manifest.run.operator", 255)
    if not isinstance(run["core_commit"], str) or not COMMIT_RE.fullmatch(run["core_commit"]):
        raise ValueError("manifest.run.core_commit must be a full lowercase Git commit")
    if not isinstance(run["raw_rbf_sha256"], str) or not SHA256_RE.fullmatch(run["raw_rbf_sha256"]):
        raise ValueError("manifest.run.raw_rbf_sha256 must be lowercase SHA-256")
    if run["firmware_version"] != REQUIRED_FIRMWARE:
        raise ValueError(f"manifest must use reviewed firmware {REQUIRED_FIRMWARE}")
    _text(run["pocket_hardware_revision"], "manifest.run.pocket_hardware_revision", 255)
    _text(run["dock_hardware_revision"], "manifest.run.dock_hardware_revision", 255)


def verify_manifest(
    catalogue_path: pathlib.Path,
    manifest_path: pathlib.Path,
    *,
    require_complete: bool = False,
    require_pass: bool = False,
) -> dict[str, Any]:
    """Verify a private evidence manifest against the checked-in catalogue."""
    validate_catalogue(catalogue_path)
    catalogue = _body(_load(catalogue_path, "catalogue"), "catalogue")
    manifest = _body(_load(manifest_path, "manifest"), "manifest")
    _validate_run(manifest)
    run_created_at = manifest["run"]["created_at"]
    artifacts, artifact_digest = _validate_artifacts(
        manifest["artifacts"], manifest_path.resolve().parent
    )

    catalogue_cases = _array(catalogue["cases"], "catalogue.cases")
    manifest_cases = _array(manifest["cases"], "manifest.cases")
    if len(manifest_cases) != len(catalogue_cases):
        raise ValueError("manifest does not contain the exact catalogue case count")

    used_artifacts: dict[str, str] = {}
    commercial_hashes: dict[str, str] = {}
    status_counts = {"pass": 0, "fail": 0, "pending": 0}
    root = catalogue_path.resolve().parent
    for index, (canonical_raw, observed_raw) in enumerate(zip(catalogue_cases, manifest_cases)):
        canonical = _object(canonical_raw, f"catalogue.cases[{index}]")
        observed = _object(observed_raw, f"manifest.cases[{index}]")
        where = f"manifest.cases[{index}]"
        _validate_case_static(observed, where, root)
        for field in IMMUTABLE_CASE_FIELDS:
            if observed[field] != canonical[field]:
                raise ValueError(f"{where}.{field} differs from the reviewed catalogue")

        modes = _object(observed["modes"], f"{where}.modes")
        _keys(modes, f"{where}.modes", {"pocket", "dock"})
        all_modes_pending = all(
            isinstance(modes[name], dict) and modes[name].get("status") == "pending"
            for name in ("pocket", "dock")
        )

        case_class = observed["class"]
        owner_hash = observed["owner_rom_sha256"]
        if case_class == "commercial":
            if owner_hash is None and all_modes_pending:
                pass
            elif not isinstance(owner_hash, str) or not SHA256_RE.fullmatch(owner_hash):
                raise ValueError(f"{where}.owner_rom_sha256 requires an owner-computed SHA-256")
            elif owner_hash in commercial_hashes:
                raise ValueError(
                    f"{where}.owner_rom_sha256 duplicates {commercial_hashes[owner_hash]}"
                )
            else:
                commercial_hashes[owner_hash] = observed["id"]
        elif owner_hash is not None:
            raise ValueError(f"{where}.owner_rom_sha256 must be null for open fixtures")

        operator_steps = _array(observed["operator_steps"], f"{where}.operator_steps")
        for step_index, step in enumerate(operator_steps):
            _text(step, f"{where}.operator_steps[{step_index}]")
        if observed["operator_steps_required"] and not operator_steps and not all_modes_pending:
            raise ValueError(f"{where}.operator_steps is required because the upstream report is sparse")

        reference = _object(observed["reference"], f"{where}.reference")
        _keys(reference, f"{where}.reference", {"source", "artifact_ids", "notes"})
        reference_ids = _artifact_ids(
            reference["artifact_ids"], f"{where}.reference.artifact_ids", artifacts
        )
        if case_class == "commercial":
            pending_reference = {"source": None, "artifact_ids": [], "notes": None}
            if all_modes_pending and reference == pending_reference:
                pass
            elif reference["source"] != "original_hardware_same_revision":
                raise ValueError(f"{where}.reference.source must be original_hardware_same_revision")
            else:
                _text(reference["notes"], f"{where}.reference.notes")
                _requirements_met(
                    [
                        {
                            "kinds": ["reference_video"],
                            "minimum": len(observed["scenarios"]),
                        }
                    ],
                    reference_ids,
                    artifacts,
                    f"{where}.reference",
                )
        else:
            valid_open_reference = {
                "source": "checked_in_open_fixture",
                "artifact_ids": [],
                "notes": None,
            }
            pending_reference = {"source": None, "artifact_ids": [], "notes": None}
            if reference != valid_open_reference and not (
                all_modes_pending and reference == pending_reference
            ):
                raise ValueError(f"{where}.reference must bind the checked-in open fixture")

        for artifact_id in reference_ids:
            owner = f"{observed['id']}.reference"
            if artifact_id in used_artifacts:
                raise ValueError(f"artifact {artifact_id} reused by {owner} and {used_artifacts[artifact_id]}")
            used_artifacts[artifact_id] = owner

        completed_windows: list[tuple[str, str]] = []
        for mode_name in ("pocket", "dock"):
            mode_where = f"{where}.modes.{mode_name}"
            mode = _object(modes[mode_name], mode_where)
            _keys(mode, mode_where, {"status", "started_at", "completed_at", "artifact_ids", "notes"})
            if mode["status"] not in status_counts:
                raise ValueError(f"{mode_where}.status must be pending, pass, or fail")
            status_counts[mode["status"]] += 1
            mode_ids = _artifact_ids(mode["artifact_ids"], f"{mode_where}.artifact_ids", artifacts)
            if mode["status"] == "pending":
                if any(
                    value is not None
                    for value in (mode["started_at"], mode["completed_at"], mode["notes"])
                ) or mode_ids:
                    raise ValueError(f"{mode_where} pending result must not contain evidence")
                if require_complete or require_pass:
                    raise ValueError(f"{mode_where} is pending")
            else:
                started_at = _utc(mode["started_at"], f"{mode_where}.started_at")
                completed_at = _utc(mode["completed_at"], f"{mode_where}.completed_at")
                if started_at > completed_at:
                    raise ValueError(f"{mode_where} completes before it starts")
                if started_at < run_created_at:
                    raise ValueError(f"{mode_where} starts before the compatibility run")
                _text(mode["notes"], f"{mode_where}.notes")
                _requirements_met(
                    observed["mode_evidence_requirements"], mode_ids, artifacts, mode_where
                )
                for artifact_id in mode_ids:
                    captured_at = artifacts[artifact_id]["captured_at"]
                    if not started_at <= captured_at <= completed_at:
                        raise ValueError(
                            f"{mode_where} references evidence captured outside its test interval"
                        )
                completed_windows.append((started_at, completed_at))
                if require_pass and mode["status"] != "pass":
                    raise ValueError(f"{mode_where} is not a pass")
            for artifact_id in mode_ids:
                owner = f"{observed['id']}.{mode_name}"
                if artifact_id in used_artifacts:
                    raise ValueError(
                        f"artifact {artifact_id} reused by {owner} and {used_artifacts[artifact_id]}"
                    )
                used_artifacts[artifact_id] = owner

        if reference_ids:
            # Reference captures may precede either device-mode run, but they must
            # belong to this compatibility campaign and cannot postdate all of
            # the completed observations they support.
            latest_completion = max(completed for _, completed in completed_windows)
            for artifact_id in reference_ids:
                captured_at = artifacts[artifact_id]["captured_at"]
                if not run_created_at <= captured_at <= latest_completion:
                    raise ValueError(
                        f"{where}.reference references evidence captured outside the run window"
                    )

    unknown_artifacts = set(artifacts) - set(used_artifacts)
    if unknown_artifacts:
        raise ValueError("unreferenced artifacts: " + ", ".join(sorted(unknown_artifacts)))

    attestation = _object(manifest["attestation"], "manifest.attestation")
    _keys(
        attestation,
        "manifest.attestation",
        {
            "physical_hardware_observed",
            "results_not_inferred_from_simulation",
            "reviewer",
            "reviewed_at",
        },
    )
    if require_complete or require_pass:
        if attestation["physical_hardware_observed"] is not True:
            raise ValueError("manifest attestation must confirm physical hardware observation")
        if attestation["results_not_inferred_from_simulation"] is not True:
            raise ValueError("manifest attestation must reject simulation-inferred results")
        _text(attestation["reviewer"], "manifest.attestation.reviewer", 255)
        _utc(attestation["reviewed_at"], "manifest.attestation.reviewed_at")
    else:
        allowed = {None, True, False}
        if attestation["physical_hardware_observed"] not in allowed or attestation["results_not_inferred_from_simulation"] not in allowed:
            raise ValueError("manifest attestation booleans must be true, false, or null")
        if attestation["reviewer"] is None and attestation["reviewed_at"] is None:
            pass
        else:
            _text(attestation["reviewer"], "manifest.attestation.reviewer", 255)
            _utc(attestation["reviewed_at"], "manifest.attestation.reviewed_at")

    return {
        "cases": len(manifest_cases),
        "artifacts": len(artifacts),
        "status": status_counts,
        "artifact_index_sha256": artifact_digest,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalogue",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1] / "known-title-compatibility.json",
    )
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.manifest is None:
            summary = validate_catalogue(args.catalogue)
        else:
            summary = verify_manifest(
                args.catalogue,
                args.manifest,
                require_complete=args.require_complete,
                require_pass=args.require_pass,
            )
        print(json.dumps(summary, sort_keys=True))
        return 0
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
