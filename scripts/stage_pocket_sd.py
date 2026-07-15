#!/usr/bin/env python3
"""Safely validate and stage a Swan Song package for Pocket.

The default CLI operation is a read-only plan. Writing requires ``--apply``;
writing below macOS ``/Volumes`` additionally requires ``--allow-volume``.
Release verification additionally requires caller-supplied expected release
identity and an authorized checked-in release policy. No ROM or BIOS is
downloaded, game ROM contents are never read, and unrelated destination files
are never removed.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import io
import json
import os
import pathlib
import re
import secrets
import stat
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Iterable

from package_core import (
    AUDIT_REQUIRED_TRUE_GATES,
    RELEASE_EVIDENCE_V2,
    RELEASE_QUARTUS_VERSION,
    RELEASE_SOURCE_INPUTS_V1,
    SIGNED_BUILD_PAIR_V1,
    validate_release_policy,
)
from license_manifest import validate_license_manifest
from known_title_compatibility import (
    MAGIC as KNOWN_TITLE_COMPATIBILITY_MAGIC,
    REQUIRED_COMMERCIAL_IDS as KNOWN_TITLE_COMMERCIAL_IDS,
    REQUIRED_OPEN_IDS as KNOWN_TITLE_OPEN_IDS,
)
from package_validator import (
    StrictJsonError,
    ValidatedDistribution,
    strict_json_loads,
    validate_distribution,
)
from reverse_rbf import REVERSE
from pocket_hardware_qa import (
    CASE_SPECS as HARDWARE_QA_CASE_SPECS,
    INSTALLED_STATIC_PAYLOAD_NAMES as HARDWARE_QA_STATIC_PAYLOAD_NAMES,
    MANIFEST_MAGIC as HARDWARE_QA_MANIFEST_MAGIC,
    PERSISTENT_SETTING_NAMES as HARDWARE_QA_PERSISTENT_SETTING_NAMES,
    installed_payload_names as hardware_qa_installed_payload_names,
)


ROOT = pathlib.Path(__file__).resolve().parent.parent
CURRENT_DIST = ROOT / "dist"
RELEASE_POLICY = ROOT / "release-policy.json"
DEFAULT_VOLUMES_ROOT = pathlib.Path("/Volumes")
EXPECTED_CORE_ID = "RegionallyFamous.SwanSong"
EXPECTED_PLATFORM_ID = "wonderswan"
EXPECTED_REPOSITORY = "https://github.com/RegionallyFamous/swansong-core"
CORE_DIRECTORY = pathlib.PurePosixPath("Cores") / EXPECTED_CORE_ID
CORE_JSON = CORE_DIRECTORY / "core.json"
INTERACT_JSON = CORE_DIRECTORY / "interact.json"
DATA_JSON = CORE_DIRECTORY / "data.json"
ASSET_DIRECTORY = pathlib.PurePosixPath("Assets/wonderswan/common")
MAX_ARCHIVE_ENTRIES = 128
MAX_PACKAGE_SIZE = 32 * 1024 * 1024
MAX_ARCHIVE_FILE_SIZE = 8 * 1024 * 1024
MAX_ARCHIVE_TOTAL_SIZE = 16 * 1024 * 1024
MAX_PROVENANCE_SIZE = 2 * 1024 * 1024
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
JOB_NONCE_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
RELEASE_GATE_NAMES = {
    "compressed_bitstream",
    "dock_hardware",
    "fit_success",
    "flow_success",
    "hold_timing",
    "no_critical_warnings",
    "no_unconstrained_paths",
    "pocket_hardware",
    "recovery_timing",
    "removal_timing",
    "setup_timing",
}


class StagingError(ValueError):
    """A validation or safe-install precondition failed."""


@dataclass(frozen=True)
class ManagedFile:
    relative: pathlib.PurePosixPath
    payload: bytes
    source: str


@dataclass(frozen=True)
class StagingPlan:
    root: pathlib.Path
    root_identity: tuple[int, int]
    files: tuple[ManagedFile, ...]
    package: pathlib.Path
    provenance: pathlib.Path
    package_sha256: str
    core_version: str
    release_date: str
    release: bool
    source_commit: str | None
    new_files: tuple[pathlib.PurePosixPath, ...]
    replaced_files: tuple[pathlib.PurePosixPath, ...]
    unchanged_files: tuple[pathlib.PurePosixPath, ...]
    is_volume: bool
    volumes_root: pathlib.Path


@dataclass
class _CreatedDirectory:
    parent_descriptor: int
    name: str
    relative: pathlib.PurePosixPath
    identity: tuple[int, int]


@dataclass
class _PreparedManagedFile:
    managed: ManagedFile
    parent_descriptor: int
    parent_identity: tuple[int, int]
    original: bytes | None
    original_identity: tuple[int, int] | None
    original_mode: int | None
    installed_identity: tuple[int, int] | None = None
    original_quarantine: str | None = None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_input(path: pathlib.Path, description: str, maximum: int | None = None) -> bytes:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise StagingError(
                f"{description} does not exist or is not a regular file: {path}"
            )
        if maximum is not None and before.st_size > maximum:
            raise StagingError(f"{description} exceeds {maximum} bytes: {path}")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = None
            payload = stream.read(maximum + 1 if maximum is not None else -1)
            after = os.fstat(stream.fileno())
    except OSError as error:
        if error.errno == errno.ELOOP or path.is_symlink():
            raise StagingError(f"{description} must not be a symlink: {path}") from error
        raise StagingError(f"cannot read {description} {path}: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    if maximum is not None and len(payload) > maximum:
        raise StagingError(f"{description} exceeds {maximum} bytes: {path}")
    stable_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if not stable_identity or len(payload) != after.st_size:
        raise StagingError(f"{description} changed while it was being read: {path}")
    return payload


def _safe_member_name(raw: str) -> pathlib.PurePosixPath:
    if not raw or "\\" in raw or raw.startswith("/"):
        raise StagingError(f"unsafe package path: {raw!r}")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise StagingError(f"unsafe package path: {raw!r}")
    stripped = raw[:-1] if raw.endswith("/") else raw
    parts = stripped.split("/")
    if not stripped or any(part in {"", ".", ".."} for part in parts):
        raise StagingError(f"unsafe package path: {raw!r}")
    relative = pathlib.PurePosixPath(*parts)
    if relative.parts[0] not in {"Assets", "Cores", "Platforms"}:
        raise StagingError(f"unsupported package base folder: {raw}")
    return relative


def _validate_member_type(info: zipfile.ZipInfo) -> None:
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    allowed = {0, stat.S_IFDIR} if info.is_dir() else {0, stat.S_IFREG}
    if kind not in allowed:
        raise StagingError(f"package entry is a symlink or special file: {info.filename}")
    if info.flag_bits & 1:
        raise StagingError(f"encrypted package entries are not supported: {info.filename}")


def _read_archive(
    path: pathlib.Path, package_payload: bytes
) -> tuple[dict[pathlib.PurePosixPath, bytes], set[pathlib.PurePosixPath]]:
    payloads: dict[pathlib.PurePosixPath, bytes] = {}
    directories: set[pathlib.PurePosixPath] = set()
    folded: dict[str, pathlib.PurePosixPath] = {}
    prefix_casing: dict[str, pathlib.PurePosixPath] = {}
    file_names: set[str] = set()
    total_size = 0
    try:
        # Parse the same immutable byte snapshot whose SHA-256 is validated.
        # Reopening the path here would create a package-swap race.
        with zipfile.ZipFile(io.BytesIO(package_payload)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise StagingError(
                    f"development package has more than {MAX_ARCHIVE_ENTRIES} entries"
                )
            for info in infos:
                relative = _safe_member_name(info.filename)
                _validate_member_type(info)
                folded_name = relative.as_posix().casefold()
                for length in range(1, len(relative.parts) + 1):
                    prefix = pathlib.PurePosixPath(*relative.parts[:length])
                    prefix_folded = prefix.as_posix().casefold()
                    previous_prefix = prefix_casing.setdefault(prefix_folded, prefix)
                    if previous_prefix != prefix:
                        raise StagingError(
                            f"case-colliding package path components: {info.filename}"
                        )
                    if length < len(relative.parts) and prefix_folded in file_names:
                        raise StagingError(
                            f"package file/directory path collision: {info.filename}"
                        )
                previous = folded.setdefault(folded_name, relative)
                if previous != relative or relative in payloads or relative in directories:
                    raise StagingError(
                        f"duplicate or case-colliding package path: {info.filename}"
                    )
                if info.is_dir():
                    directories.add(relative)
                    continue
                existing_names = file_names | {
                    path.as_posix().casefold() for path in directories
                }
                if any(
                    existing.startswith(folded_name + "/")
                    for existing in existing_names
                ):
                    raise StagingError(
                        f"package file/directory path collision: {info.filename}"
                    )
                file_names.add(folded_name)
                if info.file_size > MAX_ARCHIVE_FILE_SIZE:
                    raise StagingError(
                        f"package member exceeds {MAX_ARCHIVE_FILE_SIZE} bytes: {info.filename}"
                    )
                total_size += info.file_size
                if total_size > MAX_ARCHIVE_TOTAL_SIZE:
                    raise StagingError(
                        f"package expands beyond {MAX_ARCHIVE_TOTAL_SIZE} bytes"
                    )
                payload = archive.read(info)
                if len(payload) != info.file_size:
                    raise StagingError(f"package member size changed while reading: {info.filename}")
                payloads[relative] = payload
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
        raise StagingError(f"invalid development package {path}: {error}") from error
    return payloads, directories


def _object(value: object, description: str) -> dict:
    if not isinstance(value, dict):
        raise StagingError(f"{description} must be an object")
    return value


def _json(payload: bytes, description: str) -> dict:
    try:
        return _object(json.loads(payload.decode("utf-8")), description)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise StagingError(f"invalid JSON in {description}: {error}") from error


def _strict_json(payload: bytes, description: str) -> dict:
    try:
        return _object(strict_json_loads(payload.decode("utf-8")), description)
    except (UnicodeError, json.JSONDecodeError, StrictJsonError) as error:
        raise StagingError(f"invalid strict JSON in {description}: {error}") from error


def _exact_members(value: object, description: str, expected: set[str]) -> dict:
    body = _object(value, description)
    observed = set(body)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise StagingError(f"{description} has the wrong schema ({'; '.join(details)})")
    return body


def _integer(value: object, description: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise StagingError(f"{description} must be an integer")
    minimum = 1 if positive else 0
    if value < minimum:
        comparison = "positive" if positive else "nonnegative"
        raise StagingError(f"{description} must be {comparison}")
    return value


def _sha256(value: object, description: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise StagingError(f"{description} must be a lowercase SHA-256")
    return value


def _commit(value: object, description: str) -> str:
    if not isinstance(value, str) or COMMIT_PATTERN.fullmatch(value) is None:
        raise StagingError(f"{description} must be a lowercase 40-hex commit")
    return value


def _leaf_filename(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise StagingError(f"{description} must be a nonempty filename")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise StagingError(f"{description} must not contain a path")
    return value


def _identity_record(value: object, description: str) -> dict:
    record = _exact_members(value, description, {"filename", "size", "sha256"})
    _leaf_filename(record["filename"], f"{description} filename")
    _integer(record["size"], f"{description} size", positive=True)
    _sha256(record["sha256"], f"{description} SHA-256")
    return record


def _source_path(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or value.startswith("/")
        or any(ord(character) < 0x20 for character in value)
    ):
        raise StagingError(f"{description} must be a safe relative source path")
    path = pathlib.PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise StagingError(f"{description} must be a safe relative source path")
    return path.as_posix()


def _source_file_record(value: object, description: str) -> dict:
    record = _exact_members(
        value, description, {"git_blob", "mode", "size", "sha256"}
    )
    if not isinstance(record["git_blob"], str) or COMMIT_PATTERN.fullmatch(
        record["git_blob"]
    ) is None:
        raise StagingError(f"{description} git_blob must be lowercase 40-hex")
    if record["mode"] not in {"100644", "100755"}:
        raise StagingError(f"{description} mode is not a regular Git blob mode")
    _integer(record["size"], f"{description} size")
    _sha256(record["sha256"], f"{description} SHA-256")
    return record


def _verified_release_source_inputs(
    value: object,
    *,
    expected_source_commit: str,
    raw_rbf: dict,
    payloads: dict[pathlib.PurePosixPath, bytes],
    generated: set[pathlib.PurePosixPath],
) -> dict:
    source = _exact_members(
        value,
        "release source inputs",
        {
            "magic",
            "repository",
            "source_commit",
            "source_tree",
            "dist_directory",
            "dist_directories",
            "chip32_assembly",
            "chip32_encoded_image",
            "tracked_files",
            "raw_rbf",
        },
    )
    if source["magic"] != RELEASE_SOURCE_INPUTS_V1:
        raise StagingError(f"release source inputs require {RELEASE_SOURCE_INPUTS_V1}")
    if source["repository"] != EXPECTED_REPOSITORY:
        raise StagingError("release source inputs identify a foreign repository")
    if source["source_commit"] != expected_source_commit:
        raise StagingError("release source inputs do not match the expected commit")
    _commit(source["source_tree"], "release source tree")
    if source["dist_directory"] != "dist":
        raise StagingError("release source inputs have an invalid dist directory")
    assembly = _source_path(
        source["chip32_assembly"], "release source Chip32 assembly"
    )
    encoded = _source_path(
        source["chip32_encoded_image"], "release source Chip32 encoded image"
    )
    if assembly != "src/support/chip32.asm" or encoded != "src/support/chip32.bin.hex":
        raise StagingError("release source inputs have unexpected Chip32 paths")

    raw_source = _identity_record(source["raw_rbf"], "release source raw RBF")
    if raw_source != raw_rbf:
        raise StagingError("release source raw RBF does not match package provenance")

    tracked_value = _object(source["tracked_files"], "release source tracked files")
    tracked: dict[str, dict] = {}
    for raw_name, raw_record in tracked_value.items():
        name = _source_path(raw_name, "release source tracked filename")
        if name in tracked:
            raise StagingError("release source tracked filenames collide")
        tracked[name] = _source_file_record(
            raw_record, f"release source tracked file {name}"
        )
    required_chip = {assembly, encoded}
    if not required_chip.issubset(tracked):
        raise StagingError("release source inputs do not inventory both Chip32 inputs")
    dist_records = {
        name.removeprefix("dist/"): record
        for name, record in tracked.items()
        if name.startswith("dist/")
    }
    if len(dist_records) + len(required_chip) != len(tracked):
        raise StagingError("release source inputs inventory unrelated source paths")
    manifest_static = {
        pathlib.PurePosixPath(name): record
        for name, record in dist_records.items()
        if pathlib.PurePosixPath(name).name != ".gitkeep"
    }
    package_static = {
        relative: payload
        for relative, payload in payloads.items()
        if relative not in generated
    }
    if set(manifest_static) != set(package_static):
        raise StagingError(
            "release ZIP static inventory does not match its commit-derived source inputs"
        )
    for relative, payload in package_static.items():
        record = manifest_static[relative]
        if record["size"] != len(payload) or record["sha256"] != sha256_bytes(payload):
            raise StagingError(
                f"release ZIP member does not match its commit-derived source: {relative}"
            )

    directories_value = source["dist_directories"]
    if not isinstance(directories_value, list):
        raise StagingError("release source dist_directories must be an array")
    directories = [
        _source_path(item, "release source dist directory")
        for item in directories_value
    ]
    if directories != sorted(set(directories)) or any(
        not name.startswith("dist/") for name in directories
    ):
        raise StagingError("release source dist_directories are not canonical")
    expected_directories = sorted(
        {
            parent.as_posix()
            for name in dist_records
            for parent in pathlib.PurePosixPath("dist")
            .joinpath(name)
            .parents
            if parent.as_posix() not in {".", "dist"}
        }
    )
    if directories != expected_directories:
        raise StagingError("release source directory inventory is incomplete")
    return source


def _entry_record(value: object, description: str) -> dict:
    record = _exact_members(value, description, {"size", "sha256"})
    _integer(record["size"], f"{description} size")
    _sha256(record["sha256"], f"{description} SHA-256")
    return record


def _verified_signed_build_origins(
    value: object,
    *,
    source_commit: str,
    source_date_epoch: int,
    build_id: dict,
    root_audit: dict,
) -> dict:
    pair = _exact_members(
        value,
        "release evidence signed build origins",
        {"magic", "source_commit", "source_date_epoch", "rbf", "build_id", "builds"},
    )
    if pair["magic"] != SIGNED_BUILD_PAIR_V1:
        raise StagingError(
            f"release evidence signed origins require {SIGNED_BUILD_PAIR_V1}"
        )
    if pair["source_commit"] != source_commit:
        raise StagingError("signed build origins source commit does not match")
    if _integer(
        pair["source_date_epoch"], "signed build origins source_date_epoch"
    ) != source_date_epoch:
        raise StagingError("signed build origins source epoch does not match")
    pair_rbf = _identity_record(pair["rbf"], "signed build origins RBF")
    if pair_rbf["filename"] != "ap_core.rbf":
        raise StagingError("signed build origins RBF filename is invalid")
    pair_build_id = _identity_record(
        pair["build_id"], "signed build origins build ID"
    )
    if pair_build_id != build_id:
        raise StagingError("signed build origins build ID does not match evidence")

    builds = pair["builds"]
    if not isinstance(builds, list) or len(builds) != 2:
        raise StagingError("signed build origins must contain exactly two builds")
    fields = {
        "label",
        "repository",
        "workflow_path",
        "source_ref",
        "source_commit",
        "run_id",
        "run_attempt",
        "job",
        "job_nonce",
        "runner_environment",
        "candidate_audit",
        "attestation_bundle",
        "recomputed_audit_sha256",
        "submitted_audit_sha256",
    }

    def relative_identity(value: object, description: str, expected: str) -> dict:
        record = _exact_members(value, description, {"filename", "size", "sha256"})
        if record["filename"] != expected:
            raise StagingError(f"{description} filename must be {expected}")
        _integer(record["size"], f"{description} size", positive=True)
        _sha256(record["sha256"], f"{description} SHA-256")
        return record

    normalized: list[dict] = []
    for index, label in enumerate(("a", "b")):
        build = _exact_members(
            builds[index], f"signed build origin {label}", fields
        )
        expected_static = {
            "label": label,
            "repository": "RegionallyFamous/swansong-core",
            "workflow_path": ".github/workflows/quartus-fit.yml",
            "source_ref": "refs/heads/main",
            "source_commit": source_commit,
            "job": "fit",
            "runner_environment": "self-hosted",
        }
        if any(build.get(name) != expected for name, expected in expected_static.items()):
            raise StagingError(f"signed build origin {label} identity is invalid")
        run_id = _integer(
            build["run_id"], f"signed build origin {label} run_id", positive=True
        )
        run_attempt = _integer(
            build["run_attempt"],
            f"signed build origin {label} run_attempt",
            positive=True,
        )
        nonce = build["job_nonce"]
        if not isinstance(nonce, str) or JOB_NONCE_PATTERN.fullmatch(nonce) is None:
            raise StagingError(
                f"signed build origin {label} job_nonce must be 32 lowercase hex"
            )
        candidate = relative_identity(
            build["candidate_audit"],
            f"signed build origin {label} candidate audit",
            f"signed-builds/{label}/quartus-audit-candidate.json",
        )
        bundle = relative_identity(
            build["attestation_bundle"],
            f"signed build origin {label} attestation bundle",
            f"signed-builds/{label}/quartus-audit-candidate.attestation.json",
        )
        recomputed = _sha256(
            build["recomputed_audit_sha256"],
            f"signed build origin {label} recomputed audit SHA-256",
        )
        submitted = _sha256(
            build["submitted_audit_sha256"],
            f"signed build origin {label} submitted audit SHA-256",
        )
        if submitted != candidate["sha256"]:
            raise StagingError(
                f"signed build origin {label} submitted audit identity mismatch"
            )
        if label == "a" and (
            candidate["size"] != root_audit["size"]
            or candidate["sha256"] != root_audit["sha256"]
        ):
            raise StagingError(
                "signed build origin a is not the root recomputed Quartus audit"
            )
        normalized.append(
            {
                **expected_static,
                "run_id": run_id,
                "run_attempt": run_attempt,
                "job_nonce": nonce,
                "candidate_audit": candidate,
                "attestation_bundle": bundle,
                "recomputed_audit_sha256": recomputed,
                "submitted_audit_sha256": submitted,
            }
        )
    if normalized[0]["run_id"] == normalized[1]["run_id"]:
        raise StagingError("signed build origins must have distinct workflow run IDs")
    if normalized[0]["job_nonce"] == normalized[1]["job_nonce"]:
        raise StagingError("signed build origins must have distinct workflow job nonces")
    if (
        normalized[0]["candidate_audit"]["sha256"]
        == normalized[1]["candidate_audit"]["sha256"]
    ):
        raise StagingError("signed build origins must have distinct candidate audits")
    if (
        normalized[0]["attestation_bundle"]["sha256"]
        == normalized[1]["attestation_bundle"]["sha256"]
    ):
        raise StagingError("signed build origins must have distinct attestation bundles")
    return {
        "magic": SIGNED_BUILD_PAIR_V1,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "rbf": pair_rbf,
        "build_id": pair_build_id,
        "builds": normalized,
    }


def _verified_build_evidence(value: object, expected_source_commit: str) -> dict:
    evidence = _exact_members(
        value,
        "release provenance build_evidence",
        {
            "magic",
            "manifest_filename",
            "manifest_size",
            "manifest_sha256",
            "source_commit",
            "source_date_epoch",
            "quartus_version",
            "build_id",
            "reports",
            "quartus_audit",
            "hardware_qa",
            "known_title_compatibility",
            "signed_build_origins",
            "gates",
        },
    )
    if evidence["magic"] != RELEASE_EVIDENCE_V2:
        raise StagingError(f"release provenance requires {RELEASE_EVIDENCE_V2}")
    _leaf_filename(evidence["manifest_filename"], "release evidence manifest filename")
    _integer(evidence["manifest_size"], "release evidence manifest size", positive=True)
    _sha256(evidence["manifest_sha256"], "release evidence manifest SHA-256")
    source_commit = _commit(evidence["source_commit"], "release evidence source_commit")
    if source_commit != expected_source_commit:
        raise StagingError("release source commit does not match the expected commit")
    source_date_epoch = _integer(
        evidence["source_date_epoch"], "release evidence source_date_epoch"
    )
    if source_date_epoch > 253_402_300_799:
        raise StagingError("release evidence source_date_epoch is out of range")
    if evidence["quartus_version"] != RELEASE_QUARTUS_VERSION:
        raise StagingError(
            f"release provenance must identify exact Quartus {RELEASE_QUARTUS_VERSION}"
        )
    build_id = _identity_record(
        evidence["build_id"], "release evidence build_id"
    )

    reports = _exact_members(
        evidence["reports"], "release evidence reports", {"flow", "fit", "sta"}
    )
    for kind in ("flow", "fit", "sta"):
        report = _exact_members(
            reports[kind],
            f"release evidence {kind} report",
            {"filename", "size", "sha256"},
        )
        if report["filename"] != f"output_files/ap_core.{kind}.rpt":
            raise StagingError(f"release evidence {kind} report filename is invalid")
        _integer(report["size"], f"release evidence {kind} report size", positive=True)
        _sha256(report["sha256"], f"release evidence {kind} report SHA-256")

    audit = _exact_members(
        evidence["quartus_audit"],
        "release evidence Quartus audit",
        {
            "filename",
            "size",
            "sha256",
            "magic",
            "audit_pass",
            "source_commit",
            "source_date_epoch",
            "artifact_count",
            "required_candidate_gates",
        },
    )
    if audit["filename"] != "quartus-audit-candidate.json":
        raise StagingError("release evidence Quartus audit filename is invalid")
    _integer(audit["size"], "release evidence Quartus audit size", positive=True)
    _sha256(audit["sha256"], "release evidence Quartus audit SHA-256")
    if audit["magic"] != "SWAN_SONG_QUARTUS_AUDIT_V1" or audit["audit_pass"] is not True:
        raise StagingError("release evidence Quartus audit is not an accepted V1 audit")
    if audit["source_commit"] != source_commit:
        raise StagingError("release evidence Quartus audit source commit does not match")
    if audit["source_date_epoch"] != source_date_epoch:
        raise StagingError("release evidence Quartus audit source epoch does not match")
    _integer(
        audit["artifact_count"],
        "release evidence Quartus audit artifact count",
        positive=True,
    )
    candidate_gates = _exact_members(
        audit["required_candidate_gates"],
        "release evidence required candidate gates",
        set(AUDIT_REQUIRED_TRUE_GATES),
    )
    if any(candidate_gates[name] is not True for name in AUDIT_REQUIRED_TRUE_GATES):
        raise StagingError("release evidence has an unaccepted candidate gate")

    _verified_signed_build_origins(
        evidence["signed_build_origins"],
        source_commit=source_commit,
        source_date_epoch=source_date_epoch,
        build_id=build_id,
        root_audit=audit,
    )

    hardware = _exact_members(
        evidence["hardware_qa"],
        "release evidence hardware QA",
        {
            "manifest", "inventory", "magic", "run_id", "case_count",
            "artifact_count", "firmware_version", "core", "pocket", "dock",
        },
    )
    _identity_record(hardware["manifest"], "release evidence hardware QA manifest")
    _identity_record(hardware["inventory"], "release evidence hardware QA inventory")
    if hardware["magic"] != HARDWARE_QA_MANIFEST_MAGIC:
        raise StagingError("release evidence hardware QA magic is invalid")
    if not isinstance(hardware["run_id"], str) or not hardware["run_id"]:
        raise StagingError("release evidence hardware QA run_id is invalid")
    case_count = _integer(
        hardware["case_count"],
        "release evidence hardware QA case count",
        positive=True,
    )
    if case_count != len(HARDWARE_QA_CASE_SPECS):
        raise StagingError("release evidence hardware QA case catalogue is incomplete")
    _integer(
        hardware["artifact_count"],
        "release evidence hardware QA artifact count",
        positive=True,
    )
    if hardware["firmware_version"] != "2.6.0":
        raise StagingError("release evidence hardware QA firmware must be 2.6.0")
    core = _exact_members(
        hardware["core"],
        "release evidence hardware QA core",
        {
            "core_id", "version", "date_release", "core_json", "interact_json",
            "persistent_settings", "raw_rbf", "installed_bitstream",
            "installed_payloads",
        },
    )
    if core["core_id"] != EXPECTED_CORE_ID:
        raise StagingError("release evidence hardware QA core identity is invalid")
    if not isinstance(core["version"], str) or not core["version"]:
        raise StagingError("release evidence hardware QA core version is invalid")
    if not isinstance(core["date_release"], str) or not core["date_release"]:
        raise StagingError("release evidence hardware QA core date is invalid")
    for name in ("core_json", "interact_json", "raw_rbf", "installed_bitstream"):
        _identity_record(core[name], f"release evidence hardware QA {name}")
    if core["persistent_settings"] != list(HARDWARE_QA_PERSISTENT_SETTING_NAMES):
        raise StagingError(
            "release evidence hardware QA persistent-setting catalogue is invalid"
        )
    installed_payloads = _object(
        core["installed_payloads"],
        "release evidence hardware QA installed payloads",
    )
    static_names = set(HARDWARE_QA_STATIC_PAYLOAD_NAMES)
    if (
        not static_names.issubset(installed_payloads)
        or len(installed_payloads) != len(static_names) + 2
    ):
        raise StagingError(
            "release evidence hardware QA installed payload catalogue is incomplete"
        )
    for name, value in installed_payloads.items():
        if not isinstance(name, str):
            raise StagingError(
                "release evidence hardware QA installed payload name is invalid"
            )
        relative = _safe_member_name(name)
        if relative.as_posix() != name:
            raise StagingError(
                "release evidence hardware QA installed payload name is not canonical"
            )
        _entry_record(
            value, f"release evidence hardware QA installed payload {name}"
        )
    pocket = _exact_members(
        hardware["pocket"],
        "release evidence hardware QA Pocket",
        {"model", "hardware_revision", "device_id_sha256"},
    )
    dock = _exact_members(
        hardware["dock"],
        "release evidence hardware QA Dock",
        {"model", "hardware_revision", "firmware_version", "device_id_sha256"},
    )
    for device, description in ((pocket, "Pocket"), (dock, "Dock")):
        for name in set(device) - {"device_id_sha256"}:
            if not isinstance(device[name], str) or not device[name]:
                raise StagingError(
                    f"release evidence hardware QA {description} {name} is invalid"
                )
        _sha256(
            device["device_id_sha256"],
            f"release evidence hardware QA {description} device ID",
        )

    known_title = _exact_members(
        evidence["known_title_compatibility"],
        "release evidence known-title compatibility",
        {
            "catalogue", "manifest", "magic", "run_id", "case_count",
            "commercial_case_count", "open_sanity_case_count", "mode_pass_count",
            "artifact_count", "artifact_index_sha256", "firmware_version",
        },
    )
    _identity_record(
        known_title["catalogue"],
        "release evidence known-title compatibility catalogue",
    )
    _identity_record(
        known_title["manifest"],
        "release evidence known-title compatibility manifest",
    )
    if known_title["magic"] != KNOWN_TITLE_COMPATIBILITY_MAGIC:
        raise StagingError("release evidence known-title compatibility magic is invalid")
    if not isinstance(known_title["run_id"], str) or not known_title["run_id"]:
        raise StagingError("release evidence known-title compatibility run_id is invalid")
    expected_commercial = len(KNOWN_TITLE_COMMERCIAL_IDS)
    expected_open = len(KNOWN_TITLE_OPEN_IDS)
    expected_cases = expected_commercial + expected_open
    if known_title["commercial_case_count"] != expected_commercial:
        raise StagingError("release evidence known-title commercial catalogue is incomplete")
    if known_title["open_sanity_case_count"] != expected_open:
        raise StagingError("release evidence known-title open catalogue is incomplete")
    if known_title["case_count"] != expected_cases:
        raise StagingError("release evidence known-title case catalogue is incomplete")
    if known_title["mode_pass_count"] != expected_cases * 2:
        raise StagingError("release evidence known-title Pocket/Dock passes are incomplete")
    _integer(
        known_title["artifact_count"],
        "release evidence known-title artifact count",
        positive=True,
    )
    _sha256(
        known_title["artifact_index_sha256"],
        "release evidence known-title artifact index SHA-256",
    )
    if known_title["firmware_version"] != "2.6.0":
        raise StagingError("release evidence known-title firmware must be 2.6.0")

    gates = _exact_members(
        evidence["gates"], "release evidence final gates", set(RELEASE_GATE_NAMES)
    )
    if any(gates[name] is not True for name in RELEASE_GATE_NAMES):
        raise StagingError("release evidence has an unaccepted final gate")
    return evidence


def _validate_release_provenance(
    path: pathlib.Path,
    package: pathlib.Path,
    package_payload: bytes,
    payloads: dict[pathlib.PurePosixPath, bytes],
    definition: ValidatedDistribution,
    license_manifest: dict[str, object],
    bitstream_name: str,
    chip32_name: str,
    *,
    expected_package_sha256: str,
    expected_provenance_sha256: str,
    expected_version: str,
    expected_source_commit: str,
) -> str:
    expected_digest = _sha256(expected_package_sha256, "expected package SHA-256")
    expected_provenance_digest = _sha256(
        expected_provenance_sha256, "expected provenance SHA-256"
    )
    expected_commit = _commit(expected_source_commit, "expected source commit")
    if not isinstance(expected_version, str) or not expected_version:
        raise StagingError("expected release version must be nonempty")
    actual_digest = sha256_bytes(package_payload)
    if actual_digest != expected_digest:
        raise StagingError("release ZIP SHA-256 does not match the expected checksum")
    if definition.core_id != EXPECTED_CORE_ID:
        raise StagingError("release core ID is not RegionallyFamous.SwanSong")
    if definition.version != expected_version:
        raise StagingError("release core version does not match the expected version")
    if package.name != definition.recommended_archive_name:
        raise StagingError(
            f"release ZIP filename must be {definition.recommended_archive_name}"
        )

    provenance_payload = _safe_input(
        path, "release package provenance", MAX_PROVENANCE_SIZE
    )
    if sha256_bytes(provenance_payload) != expected_provenance_digest:
        raise StagingError(
            "release provenance SHA-256 does not match the expected checksum"
        )
    document = _strict_json(provenance_payload, "release package provenance")
    envelope = _exact_members(document, "release package provenance", {"package_provenance"})
    body = _exact_members(
        envelope["package_provenance"],
        "release package provenance body",
        {
            "magic",
            "release",
            "archive",
            "raw_rbf",
            "packaged_bitstream",
            "chip32",
            "entries",
            "build_evidence",
            "license_manifest",
            "release_policy",
            "source_inputs",
        },
    )
    if body["magic"] != "SWAN_SONG_PACKAGE_PROVENANCE_V1":
        raise StagingError("release package provenance magic is invalid")
    if body["release"] is not True:
        raise StagingError("release package provenance must explicitly identify a release")
    provenance_license = _object(
        body["license_manifest"], "release license manifest provenance"
    )
    source_notice_sha256 = _sha256(
        provenance_license.get("wonderswan_notice_sha256"),
        "release source notice SHA-256",
    )
    expected_license = {
        **license_manifest,
        # This source-only check cannot be reconstructed from an installed ZIP;
        # it is independently protected by the required provenance digest.
        "wonderswan_notice_sha256": source_notice_sha256,
    }
    if provenance_license != expected_license:
        raise StagingError(
            "release license manifest provenance does not match the packaged manifest"
        )
    if (
        license_manifest.get("licensing_review_complete") is not True
        or license_manifest.get("unresolved_ids") != []
    ):
        raise StagingError("release license manifest review is not complete")

    archive = _identity_record(body["archive"], "release provenance archive")
    if archive != {
        "filename": package.name,
        "size": len(package_payload),
        "sha256": actual_digest,
    }:
        raise StagingError("release ZIP does not exactly match its provenance archive identity")

    entries = _object(body["entries"], "release provenance entries")
    expected_names = {relative.as_posix() for relative in payloads}
    if set(entries) != expected_names:
        raise StagingError("release ZIP file inventory does not match its provenance")
    for relative, payload in payloads.items():
        record = _entry_record(
            entries[relative.as_posix()], f"release provenance entry {relative}"
        )
        if record != {"size": len(payload), "sha256": sha256_bytes(payload)}:
            raise StagingError(f"release ZIP member does not match its provenance: {relative}")

    raw_rbf = _identity_record(body["raw_rbf"], "release provenance raw RBF")
    packaged = _identity_record(
        body["packaged_bitstream"], "release provenance packaged bitstream"
    )
    chip32 = _identity_record(body["chip32"], "release provenance Chip32 image")
    bitstream_payload = payloads[CORE_DIRECTORY / bitstream_name]
    chip32_payload = payloads[CORE_DIRECTORY / chip32_name]
    reconstructed_raw_rbf = bitstream_payload.translate(REVERSE)
    raw_identity_matches = (
        raw_rbf["size"] == len(reconstructed_raw_rbf)
        and raw_rbf["sha256"] == sha256_bytes(reconstructed_raw_rbf)
    )
    if not raw_identity_matches:
        raise StagingError(
            "release raw RBF identity does not match the reversible packaged bitstream"
        )
    if packaged != {
        "filename": bitstream_name,
        "size": len(bitstream_payload),
        "sha256": sha256_bytes(bitstream_payload),
    }:
        raise StagingError("release packaged bitstream identity is invalid")
    if chip32 != {
        "filename": chip32_name,
        "size": len(chip32_payload),
        "sha256": sha256_bytes(chip32_payload),
    }:
        raise StagingError("release Chip32 identity is invalid")

    verified_build = _verified_build_evidence(body["build_evidence"], expected_commit)
    if verified_build["signed_build_origins"]["rbf"] != raw_rbf:
        raise StagingError(
            "release signed build RBF identity does not match package provenance"
        )
    hardware_core = verified_build["hardware_qa"]["core"]
    if hardware_core["raw_rbf"] != raw_rbf:
        raise StagingError(
            "release hardware QA raw RBF identity does not match package provenance"
        )
    expected_core_json = {
        "filename": "core.json",
        "size": len(payloads[CORE_JSON]),
        "sha256": sha256_bytes(payloads[CORE_JSON]),
    }
    if hardware_core["core_json"] != expected_core_json:
        raise StagingError(
            "release hardware QA core.json identity does not match package content"
        )
    expected_interact_json = {
        "filename": "interact.json",
        "size": len(payloads[INTERACT_JSON]),
        "sha256": sha256_bytes(payloads[INTERACT_JSON]),
    }
    if hardware_core["interact_json"] != expected_interact_json:
        raise StagingError(
            "release hardware QA interact.json identity does not match package content"
        )
    if hardware_core["version"] != definition.version:
        raise StagingError(
            "release hardware QA core version does not match package metadata"
        )
    if hardware_core["date_release"] != definition.release_date:
        raise StagingError(
            "release hardware QA core date does not match package metadata"
        )
    if hardware_core["installed_bitstream"] != packaged:
        raise StagingError(
            "release hardware QA installed bitstream does not match package content"
        )
    expected_installed_payloads = {
        name: {
            "size": len(payloads[pathlib.PurePosixPath(name)]),
            "sha256": sha256_bytes(payloads[pathlib.PurePosixPath(name)]),
        }
        for name in hardware_qa_installed_payload_names(bitstream_name, chip32_name)
    }
    if hardware_core["installed_payloads"] != expected_installed_payloads:
        raise StagingError(
            "release hardware QA installed payload inventory does not match package content"
        )
    _verified_release_source_inputs(
        body["source_inputs"],
        expected_source_commit=expected_commit,
        raw_rbf=raw_rbf,
        payloads=payloads,
        generated={
            CORE_DIRECTORY / bitstream_name,
            CORE_DIRECTORY / chip32_name,
        },
    )
    try:
        verified_policy = validate_release_policy(RELEASE_POLICY, definition)
    except (ValueError, OSError) as error:
        raise StagingError(f"release policy does not authorize installation: {error}") from error
    if body["release_policy"] != verified_policy:
        raise StagingError("release provenance does not match the authorized release policy")
    return expected_commit


def _validate_provenance(
    path: pathlib.Path,
    package: pathlib.Path,
    package_payload: bytes,
    payloads: dict[pathlib.PurePosixPath, bytes],
    license_manifest: dict[str, object],
) -> None:
    document = _json(
        _safe_input(path, "package provenance", MAX_PROVENANCE_SIZE),
        "package provenance",
    )
    if set(document) != {"package_provenance"}:
        raise StagingError("package provenance has an unexpected envelope")
    body = _exact_members(
        document["package_provenance"],
        "package provenance body",
        {
            "magic",
            "release",
            "archive",
            "raw_rbf",
            "packaged_bitstream",
            "chip32",
            "entries",
            "build_evidence",
            "license_manifest",
        },
    )
    if body.get("magic") != "SWAN_SONG_PACKAGE_PROVENANCE_V1":
        raise StagingError("package provenance magic is invalid")
    if body.get("release") is not False:
        raise StagingError("this staging workflow accepts development packages only")
    if body["license_manifest"] != license_manifest:
        raise StagingError(
            "license manifest provenance does not match the packaged manifest"
        )
    archive = _object(body.get("archive"), "package provenance archive")
    if archive.get("filename") != package.name:
        raise StagingError("package filename does not match its provenance")
    if archive.get("size") != len(package_payload):
        raise StagingError("package size does not match its provenance")
    if archive.get("sha256") != sha256_bytes(package_payload):
        raise StagingError("package SHA-256 does not match its provenance")
    entries = _object(body.get("entries"), "package provenance entries")
    expected_names = {relative.as_posix() for relative in payloads}
    if set(entries) != expected_names:
        raise StagingError("package file inventory does not match its provenance")
    for relative, payload in payloads.items():
        record = _object(entries[relative.as_posix()], f"provenance entry {relative}")
        if record.get("size") != len(payload) or record.get("sha256") != sha256_bytes(payload):
            raise StagingError(f"package member does not match its provenance: {relative}")


def _core_generated_names(payloads: dict[pathlib.PurePosixPath, bytes]) -> tuple[str, str]:
    if CORE_JSON not in payloads:
        raise StagingError(f"development package is missing {CORE_JSON}")
    core_document = _json(payloads[CORE_JSON], CORE_JSON.as_posix())
    try:
        core = core_document["core"]
        metadata = core["metadata"]
        framework = core["framework"]
        cores = core["cores"]
        author = metadata["author"]
        shortname = metadata["shortname"]
        platform_ids = metadata["platform_ids"]
        repository = metadata["url"]
        chip32_name = framework["chip32_vm"]
        bitstream_name = cores[0]["filename"]
    except (KeyError, IndexError, TypeError) as error:
        raise StagingError(f"invalid core identity in {CORE_JSON}: {error}") from error
    if f"{author}.{shortname}" != EXPECTED_CORE_ID:
        raise StagingError("development package has a stale or foreign core identity")
    if platform_ids != [EXPECTED_PLATFORM_ID]:
        raise StagingError("development package has a stale or foreign platform identity")
    if repository != EXPECTED_REPOSITORY:
        raise StagingError("development package repository identity is stale or foreign")
    for name, description in ((bitstream_name, "bitstream"), (chip32_name, "Chip32 image")):
        if not isinstance(name, str) or not name or pathlib.PurePosixPath(name).name != name:
            raise StagingError(f"development package {description} name is unsafe")
        relative = CORE_DIRECTORY / name
        if not payloads.get(relative):
            raise StagingError(f"development package is missing its {description}: {relative}")
    return bitstream_name, chip32_name


def _materialize_source_snapshot(
    payloads: dict[pathlib.PurePosixPath, bytes],
    directories: Iterable[pathlib.PurePosixPath],
    bitstream_name: str,
    chip32_name: str,
) -> tuple[ValidatedDistribution, dict[str, object]]:
    generated = {CORE_DIRECTORY / bitstream_name, CORE_DIRECTORY / chip32_name}
    with tempfile.TemporaryDirectory(prefix="swan-song-stage-validate-") as temporary:
        root = pathlib.Path(temporary)
        for relative in directories:
            (root / pathlib.Path(*relative.parts)).mkdir(parents=True, exist_ok=True)
        for relative, payload in payloads.items():
            if relative in generated:
                continue
            destination = root / pathlib.Path(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        try:
            definition = validate_distribution(root)
            return definition, validate_license_manifest(root)
        except ValueError as error:
            raise StagingError(f"development package definition validation failed: {error}") from error


def _validate_current_checkout(
    payloads: dict[pathlib.PurePosixPath, bytes],
    definition: ValidatedDistribution,
    bitstream_name: str,
    chip32_name: str,
) -> None:
    try:
        current = validate_distribution(CURRENT_DIST)
    except ValueError as error:
        raise StagingError(f"current checkout distribution is invalid: {error}") from error
    if definition != current or definition.core_id != EXPECTED_CORE_ID:
        raise StagingError("development package identity does not match the current checkout")
    generated = {CORE_DIRECTORY / bitstream_name, CORE_DIRECTORY / chip32_name}
    package_static = {relative: value for relative, value in payloads.items() if relative not in generated}
    current_static: dict[pathlib.PurePosixPath, bytes] = {}
    for path in CURRENT_DIST.rglob("*"):
        if path.is_file() and path.name != ".gitkeep":
            relative = pathlib.PurePosixPath(path.relative_to(CURRENT_DIST).as_posix())
            current_static[relative] = path.read_bytes()
    if package_static != current_static:
        raise StagingError(
            "development package definitions/art do not match the current checkout; rebuild it"
        )


def _validate_bios(path: pathlib.Path, name: str, expected_size: int) -> bytes:
    payload = _safe_input(path, f"user-supplied {name}")
    if len(payload) != expected_size:
        raise StagingError(
            f"user-supplied {name} must be exactly {expected_size} bytes, got {len(payload)}"
        )
    return payload


def _validate_bios_contract(payloads: dict[pathlib.PurePosixPath, bytes]) -> None:
    if DATA_JSON not in payloads:
        raise StagingError(f"development package is missing {DATA_JSON}")
    document = _json(payloads[DATA_JSON], DATA_JSON.as_posix())
    try:
        slots = {int(slot["id"]): slot for slot in document["data"]["data_slots"]}
    except (KeyError, TypeError, ValueError) as error:
        raise StagingError(f"invalid BIOS data-slot contract: {error}") from error
    expected = {9: ("bw.rom", 4096), 10: ("color.rom", 8192)}
    for slot_id, (filename, size) in expected.items():
        slot = slots.get(slot_id)
        if not isinstance(slot, dict):
            raise StagingError(f"development package is missing BIOS slot {slot_id}")
        if (
            slot.get("required") is not True
            or slot.get("filename") != filename
            or slot.get("size_exact") != size
        ):
            raise StagingError(f"development package BIOS slot {slot_id} is stale")


def _root(path: pathlib.Path) -> tuple[pathlib.Path, tuple[int, int]]:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, _directory_flags())
        opened = os.fstat(descriptor)
        result = path.resolve(strict=True)
        observed = os.stat(result, follow_symlinks=False)
        identity = (opened.st_dev, opened.st_ino)
        if identity != (observed.st_dev, observed.st_ino):
            raise StagingError("staging directory identity changed during validation")
    except OSError as error:
        if error.errno == errno.ELOOP or path.is_symlink():
            raise StagingError(f"staging directory must not be a symlink: {path}") from error
        raise StagingError(f"staging directory must already exist and be safe: {path}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if result == pathlib.Path(result.anchor):
        raise StagingError("refusing to use a filesystem root as the staging directory")
    return result, identity


def _is_within(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _classify(
    root: pathlib.Path,
    files: Iterable[ManagedFile],
    root_identity: tuple[int, int],
) -> tuple[tuple, tuple, tuple]:
    new: list[pathlib.PurePosixPath] = []
    replaced: list[pathlib.PurePosixPath] = []
    unchanged: list[pathlib.PurePosixPath] = []
    root_descriptor = _open_root_descriptor(root, root_identity)
    try:
        for managed in files:
            parent_descriptor = _open_parent_at(
                root_descriptor, managed.relative, create=False
            )
            if parent_descriptor is None:
                new.append(managed.relative)
                continue
            try:
                existing = _read_regular_at(
                    parent_descriptor, managed.relative.name
                )
            finally:
                os.close(parent_descriptor)
            if existing is None:
                new.append(managed.relative)
            elif existing == managed.payload:
                unchanged.append(managed.relative)
            else:
                replaced.append(managed.relative)
    finally:
        os.close(root_descriptor)
    return tuple(new), tuple(replaced), tuple(unchanged)


def plan_staging(
    *,
    staging_dir: pathlib.Path,
    package: pathlib.Path,
    provenance: pathlib.Path,
    bw_bios: pathlib.Path | None,
    color_bios: pathlib.Path | None,
    verify_release: bool = False,
    expected_package_sha256: str | None = None,
    expected_provenance_sha256: str | None = None,
    expected_version: str | None = None,
    expected_source_commit: str | None = None,
    volumes_root: pathlib.Path = DEFAULT_VOLUMES_ROOT,
) -> StagingPlan:
    root, root_identity = _root(staging_dir)
    package = package.absolute()
    provenance = provenance.absolute()
    package_payload = _safe_input(package, "Swan Song package", MAX_PACKAGE_SIZE)
    payloads, directories = _read_archive(package, package_payload)
    bitstream_name, chip32_name = _core_generated_names(payloads)
    definition, license_manifest = _materialize_source_snapshot(
        payloads, directories, bitstream_name, chip32_name
    )
    source_commit: str | None = None
    if verify_release:
        if (
            expected_package_sha256 is None
            or expected_provenance_sha256 is None
            or expected_version is None
            or expected_source_commit is None
        ):
            raise StagingError(
                "--verify-release requires --expected-package-sha256, "
                "--expected-provenance-sha256, "
                "--expected-version, and --expected-source-commit"
            )
        source_commit = _validate_release_provenance(
            provenance,
            package,
            package_payload,
            payloads,
            definition,
            license_manifest,
            bitstream_name,
            chip32_name,
            expected_package_sha256=expected_package_sha256,
            expected_provenance_sha256=expected_provenance_sha256,
            expected_version=expected_version,
            expected_source_commit=expected_source_commit,
        )
    else:
        if any(
            value is not None
            for value in (
                expected_package_sha256,
                expected_provenance_sha256,
                expected_version,
                expected_source_commit,
            )
        ):
            raise StagingError("release expectations require --verify-release")
        if bw_bios is None or color_bios is None:
            raise StagingError(
                "development staging requires both --bw-bios and --color-bios"
            )
        _validate_provenance(
            provenance,
            package,
            package_payload,
            payloads,
            license_manifest,
        )
        _validate_current_checkout(payloads, definition, bitstream_name, chip32_name)
    _validate_bios_contract(payloads)

    managed = [
        ManagedFile(
            relative,
            payload,
            "release package" if verify_release else "development package",
        )
        for relative, payload in sorted(payloads.items(), key=lambda item: item[0].as_posix())
    ]
    for bios_path, name, size in (
        (bw_bios, "bw.rom", 4096),
        (color_bios, "color.rom", 8192),
    ):
        if bios_path is not None:
            managed.append(
                ManagedFile(
                    ASSET_DIRECTORY / name,
                    _validate_bios(bios_path.absolute(), name, size),
                    "user-supplied BIOS",
                )
            )
    files = tuple(managed)
    new, replaced, unchanged = _classify(root, files, root_identity)
    resolved_volumes = volumes_root.resolve()
    is_volume = _is_within(root, resolved_volumes) and root != resolved_volumes
    return StagingPlan(
        root=root,
        root_identity=root_identity,
        files=files,
        package=package,
        provenance=provenance,
        package_sha256=sha256_bytes(package_payload),
        core_version=definition.version,
        release_date=definition.release_date,
        release=verify_release,
        source_commit=source_commit,
        new_files=new,
        replaced_files=replaced,
        unchanged_files=unchanged,
        is_volume=is_volume,
        volumes_root=resolved_volumes,
    )


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_root_descriptor(
    root: pathlib.Path, expected_identity: tuple[int, int]
) -> int:
    try:
        descriptor = os.open(root, _directory_flags())
    except OSError as error:
        raise StagingError("staging directory became unsafe after validation") from error
    try:
        opened = os.fstat(descriptor)
        observed = os.stat(root, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino):
            raise StagingError("staging directory identity changed after validation")
        if (opened.st_dev, opened.st_ino) != expected_identity:
            raise StagingError("staging directory is not the directory that was planned")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _case_safe_name_at(directory: int, name: str, description: str) -> bool:
    matches = [entry for entry in os.listdir(directory) if entry.casefold() == name.casefold()]
    if len(matches) > 1 or (matches and matches[0] != name):
        observed = matches[0] if matches else name
        raise StagingError(f"stale or case-colliding {description}: {observed}")
    return bool(matches)


def _open_parent_at(
    root_descriptor: int,
    relative: pathlib.PurePosixPath,
    *,
    create: bool,
    created_directories: list[_CreatedDirectory] | None = None,
) -> int | None:
    current = os.dup(root_descriptor)
    walked: list[str] = []
    try:
        for part in relative.parts[:-1]:
            walked.append(part)
            created_here = False
            exists = _case_safe_name_at(
                current, part, "managed destination identity"
            )
            if not exists:
                if not create:
                    os.close(current)
                    return None
                try:
                    os.mkdir(part, 0o755, dir_fd=current)
                except FileExistsError:
                    pass
                else:
                    created_here = True
                    _fsync_directory(current)
                _case_safe_name_at(current, part, "managed destination identity")
            try:
                metadata = os.stat(part, dir_fd=current, follow_symlinks=False)
            except OSError as error:
                raise StagingError(
                    "managed destination parent is unsafe: " + "/".join(walked)
                ) from error
            if stat.S_ISLNK(metadata.st_mode):
                raise StagingError(
                    "managed destination must not be a symlink: "
                    + "/".join(walked)
                )
            if not stat.S_ISDIR(metadata.st_mode):
                raise StagingError(
                    "managed destination parent is not a directory: "
                    + "/".join(walked)
                )
            try:
                child = os.open(part, _directory_flags(), dir_fd=current)
            except OSError as error:
                raise StagingError(
                    "managed destination parent is unsafe: " + "/".join(walked)
                ) from error
            if created_here and created_directories is not None:
                opened = os.fstat(child)
                created_directories.append(
                    _CreatedDirectory(
                        parent_descriptor=os.dup(current),
                        name=part,
                        relative=pathlib.PurePosixPath(*walked),
                        identity=(opened.st_dev, opened.st_ino),
                    )
                )
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def _read_regular_snapshot_at(
    directory: int, name: str
) -> tuple[bytes, tuple[int, int], int] | None:
    if not _case_safe_name_at(directory, name, "managed destination identity"):
        return None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except OSError as error:
        raise StagingError(f"managed destination is unsafe: {name}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise StagingError(f"managed destination is not a regular file: {name}")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            payload = stream.read()
            after = os.fstat(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    stable_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if not stable_identity or len(payload) != after.st_size:
        raise StagingError(f"managed destination changed while being read: {name}")
    return payload, (after.st_dev, after.st_ino), stat.S_IMODE(after.st_mode)


def _read_regular_at(directory: int, name: str) -> bytes | None:
    snapshot = _read_regular_snapshot_at(directory, name)
    return None if snapshot is None else snapshot[0]


_UNCONDITIONAL_REPLACE = object()


def _fsync_directory(directory: int) -> bool:
    """Sync directory metadata when the mounted filesystem supports it."""

    try:
        os.fsync(directory)
        return True
    except OSError as error:
        unsupported = {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL)}
        if error.errno in unsupported:
            return False
        raise


def _rename_noreplace(
    source_directory: int,
    source_name: str,
    destination_directory: int,
    destination_name: str,
) -> None:
    """Atomically rename while refusing to replace an existing destination."""

    def raise_native_error(error_number: int) -> None:
        unavailable = {
            errno.ENOSYS,
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if error_number in unavailable:
            raise StagingError(
                "target filesystem lacks the native atomic no-clobber rename "
                "required for safe staging"
            )
        raise OSError(error_number, os.strerror(error_number), destination_name)

    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(
            source_directory,
            source,
            destination_directory,
            destination,
            0x00000004,  # RENAME_EXCL
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        raise_native_error(error_number)
    if hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        result = function(
            source_directory,
            source,
            destination_directory,
            destination,
            1,  # RENAME_NOREPLACE
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        raise_native_error(error_number)

    # A link-then-unlink fallback has a partially-published failure state if
    # unlink fails. Safe staging therefore requires a native, single-operation
    # no-clobber rename and fails closed when the platform lacks one.
    raise StagingError(
        "platform lacks the native atomic no-clobber rename required for safe staging"
    )


def _rename_to_unique(
    directory: int, name: str, purpose: str
) -> str:
    for _ in range(32):
        quarantine = f".swan-song-{purpose}-{secrets.token_hex(12)}"
        try:
            _rename_noreplace(directory, name, directory, quarantine)
        except FileExistsError:
            continue
        return quarantine
    raise StagingError(f"could not allocate an exclusive {purpose} quarantine")


def _restore_quarantine(directory: int, quarantine: str, name: str) -> None:
    _rename_noreplace(directory, quarantine, directory, name)
    _fsync_directory(directory)


def _atomic_write_at(
    directory: int,
    name: str,
    payload: bytes,
    *,
    mode: int = 0o644,
    expected_identity=_UNCONDITIONAL_REPLACE,
    on_replace=None,
) -> tuple[int, int]:
    temporary_name: str | None = None
    descriptor: int | None = None
    installed_identity: tuple[int, int] | None = None
    original_quarantine: str | None = None
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for _ in range(32):
            candidate = f".{name}.{secrets.token_hex(8)}.tmp"
            try:
                descriptor = os.open(candidate, flags, 0o600, dir_fd=directory)
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if descriptor is None or temporary_name is None:
            raise StagingError(f"could not allocate a temporary file for {name}")
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
            metadata = os.fstat(stream.fileno())
            installed_identity = (metadata.st_dev, metadata.st_ino)
        _case_safe_name_at(directory, name, "managed destination identity")
        if expected_identity is _UNCONDITIONAL_REPLACE:
            os.replace(
                temporary_name,
                name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
        else:
            if expected_identity is not None:
                try:
                    original_quarantine = _rename_to_unique(
                        directory, name, "original"
                    )
                    _fsync_directory(directory)
                    snapshot = _read_regular_snapshot_at(
                        directory, original_quarantine
                    )
                    if snapshot is None or snapshot[1] != expected_identity:
                        raise StagingError(
                            f"managed destination changed after snapshot: {name}"
                        )
                except Exception:
                    if original_quarantine is not None:
                        try:
                            _restore_quarantine(
                                directory, original_quarantine, name
                            )
                            original_quarantine = None
                        except Exception as restore_error:
                            raise StagingError(
                                f"managed destination changed and its quarantined "
                                f"inode could not be restored: {name}: {restore_error}"
                            )
                    raise
            try:
                _rename_noreplace(
                    directory, temporary_name, directory, name
                )
            except Exception:
                if original_quarantine is not None:
                    try:
                        _restore_quarantine(directory, original_quarantine, name)
                        original_quarantine = None
                    except Exception as restore_error:
                        raise StagingError(
                            f"conditional publication failed and the original "
                            f"inode remains quarantined as {original_quarantine}: "
                            f"{restore_error}"
                        )
                raise
        temporary_name = None
        assert installed_identity is not None
        if on_replace is not None:
            on_replace(installed_identity, original_quarantine)
        _fsync_directory(directory)
        return installed_identity
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory)
                _fsync_directory(directory)
            except FileNotFoundError:
                pass


def _discard_quarantined_file(
    directory: int, quarantine: str, expected_identity: tuple[int, int]
) -> None:
    """Remove a private quarantine only while it still names the expected inode."""

    discard = _rename_to_unique(directory, quarantine, "discard")
    try:
        _fsync_directory(directory)
        snapshot = _read_regular_snapshot_at(directory, discard)
        if snapshot is None or snapshot[1] != expected_identity:
            raise StagingError(
                f"quarantined file identity changed before cleanup: {quarantine}"
            )
        os.unlink(discard, dir_fd=directory)
        _fsync_directory(directory)
    except Exception:
        try:
            _restore_quarantine(directory, discard, quarantine)
        except Exception as restore_error:
            raise StagingError(
                f"cleanup failed and quarantine {discard} could not be restored: "
                f"{restore_error}"
            )
        raise


def _original_state_matches(
    item: _PreparedManagedFile,
    snapshot: tuple[bytes, tuple[int, int], int] | None,
) -> bool:
    if item.original_identity is None:
        return snapshot is None
    return (
        snapshot is not None
        and snapshot[0] == item.original
        and snapshot[1] == item.original_identity
        and snapshot[2] == item.original_mode
    )


def _rollback_files(prepared: list[_PreparedManagedFile]) -> list[str]:
    failures: list[str] = []
    for item in reversed(prepared):
        relative = item.managed.relative.as_posix()
        try:
            snapshot = _read_regular_snapshot_at(
                item.parent_descriptor, item.managed.relative.name
            )
            if item.installed_identity is None:
                if not _original_state_matches(item, snapshot):
                    failures.append(f"rollback conflict at {relative}")
                continue

            # Move the current name away without replacing anything, then
            # validate the moved inode. This closes the check/use gap that an
            # lstat followed by unlink/replace would leave at the public name.
            installed_quarantine = _rename_to_unique(
                item.parent_descriptor, item.managed.relative.name, "rollback"
            )
            _fsync_directory(item.parent_descriptor)
            installed_snapshot = _read_regular_snapshot_at(
                item.parent_descriptor, installed_quarantine
            )
            if (
                installed_snapshot is None
                or installed_snapshot[1] != item.installed_identity
                or installed_snapshot[0] != item.managed.payload
            ):
                try:
                    _restore_quarantine(
                        item.parent_descriptor,
                        installed_quarantine,
                        item.managed.relative.name,
                    )
                except Exception as restore_error:
                    failures.append(
                        f"rollback conflict at {relative}; current inode remains "
                        f"quarantined as {installed_quarantine}: {restore_error}"
                    )
                else:
                    failures.append(f"rollback conflict at {relative}")
                continue

            if item.original_identity is not None:
                if item.original_quarantine is None:
                    failures.append(
                        f"original inode is unavailable for rollback at {relative}; "
                        f"installed inode remains quarantined as {installed_quarantine}"
                    )
                    continue
                try:
                    _restore_quarantine(
                        item.parent_descriptor,
                        item.original_quarantine,
                        item.managed.relative.name,
                    )
                    item.original_quarantine = None
                except Exception as restore_error:
                    failures.append(
                        f"could not restore original inode at {relative}; installed "
                        f"inode remains quarantined as {installed_quarantine}: "
                        f"{restore_error}"
                    )
                    continue

            _discard_quarantined_file(
                item.parent_descriptor,
                installed_quarantine,
                item.installed_identity,
            )
            restored = _read_regular_snapshot_at(
                item.parent_descriptor, item.managed.relative.name
            )
            if not _original_state_matches(item, restored):
                failures.append(
                    f"original metadata was not restored at {relative}"
                )
        except Exception as error:  # Preserve the original transaction failure.
            failures.append(
                f"{relative}: {type(error).__name__}: {error}"
            )
    return failures


def _rollback_directories(created: list[_CreatedDirectory]) -> list[str]:
    # There is no portable conditional rmdir-by-inode. Even an exclusive
    # rename followed by inode validation leaves a race in which another actor
    # can add entries before rmdir. Retaining benign directories is safer than
    # ever deleting state that may no longer be ours.
    return [
        f"retained created directory after rollback: {item.relative.as_posix()}"
        for item in created
    ]


def _verify_installed_paths(
    root: pathlib.Path,
    root_descriptor: int,
    root_identity: tuple[int, int],
    prepared: list[_PreparedManagedFile],
) -> None:
    opened_root = os.fstat(root_descriptor)
    observed_root = os.stat(root, follow_symlinks=False)
    if (
        (opened_root.st_dev, opened_root.st_ino) != root_identity
        or (observed_root.st_dev, observed_root.st_ino) != root_identity
    ):
        raise StagingError("staging directory identity changed during transaction")
    for item in prepared:
        current_parent = _open_parent_at(
            root_descriptor, item.managed.relative, create=False
        )
        if current_parent is None:
            raise StagingError(
                "managed destination parent detached during transaction: "
                + item.managed.relative.as_posix()
            )
        try:
            metadata = os.fstat(current_parent)
            if (metadata.st_dev, metadata.st_ino) != item.parent_identity:
                raise StagingError(
                    "managed destination parent identity changed during transaction: "
                    + item.managed.relative.as_posix()
                )
            if item.installed_identity is not None:
                snapshot = _read_regular_snapshot_at(
                    current_parent, item.managed.relative.name
                )
                if snapshot is None or snapshot[1] != item.installed_identity:
                    raise StagingError(
                        "managed destination file identity changed during transaction: "
                        + item.managed.relative.as_posix()
                    )
                if snapshot[0] != item.managed.payload:
                    raise StagingError(
                        "managed destination file changed during transaction: "
                        + item.managed.relative.as_posix()
                    )
                if snapshot[2] != 0o644:
                    raise StagingError(
                        "managed destination file mode changed during transaction: "
                        + item.managed.relative.as_posix()
                    )
            else:
                snapshot = _read_regular_snapshot_at(
                    current_parent, item.managed.relative.name
                )
                if not _original_state_matches(item, snapshot):
                    raise StagingError(
                        "unchanged managed destination changed during transaction: "
                        + item.managed.relative.as_posix()
                    )
        finally:
            os.close(current_parent)


def _cleanup_originals(prepared: list[_PreparedManagedFile]) -> list[str]:
    failures: list[str] = []
    for item in prepared:
        if item.original_quarantine is None or item.original_identity is None:
            continue
        quarantine = item.original_quarantine
        try:
            _discard_quarantined_file(
                item.parent_descriptor, quarantine, item.original_identity
            )
            item.original_quarantine = None
        except Exception as error:
            failures.append(
                f"{item.managed.relative.as_posix()} ({quarantine}): "
                f"{type(error).__name__}: {error}"
            )
    return failures


def _close_prepared(prepared: list[_PreparedManagedFile]) -> None:
    for item in prepared:
        os.close(item.parent_descriptor)
    prepared.clear()


def _close_created(created: list[_CreatedDirectory]) -> None:
    for item in created:
        os.close(item.parent_descriptor)
    created.clear()


def apply_staging(plan: StagingPlan, *, allow_volume: bool = False) -> None:
    root, root_identity = _root(plan.root)
    if root != plan.root or root_identity != plan.root_identity:
        raise StagingError("staging directory identity changed after validation")
    if plan.is_volume and not allow_volume:
        raise StagingError(
            f"refusing to write below {plan.volumes_root}; use --allow-volume only for an intentional SD write"
        )
    root_descriptor = _open_root_descriptor(root, plan.root_identity)
    prepared: list[_PreparedManagedFile] = []
    created: list[_CreatedDirectory] = []
    changed: list[_PreparedManagedFile] = []
    try:
        # Hold every destination parent descriptor and snapshot every original
        # before replacing the first file. This pins the transaction to the
        # planned tree and makes a complete rollback possible after any write.
        for managed in plan.files:
            parent_descriptor = _open_parent_at(
                root_descriptor,
                managed.relative,
                create=True,
                created_directories=created,
            )
            assert parent_descriptor is not None
            parent_metadata = os.fstat(parent_descriptor)
            item = _PreparedManagedFile(
                managed=managed,
                parent_descriptor=parent_descriptor,
                parent_identity=(parent_metadata.st_dev, parent_metadata.st_ino),
                original=None,
                original_identity=None,
                original_mode=None,
            )
            prepared.append(item)
            snapshot = _read_regular_snapshot_at(
                parent_descriptor, managed.relative.name
            )
            if snapshot is not None:
                item.original, item.original_identity, item.original_mode = snapshot
        for item in prepared:
            if item.original == item.managed.payload:
                continue
            # Record before the call because a late fsync failure can occur
            # after the atomic replacement has already succeeded.
            changed.append(item)

            def record_publication(
                identity: tuple[int, int],
                quarantine: str | None,
                *,
                target: _PreparedManagedFile = item,
            ) -> None:
                target.installed_identity = identity
                target.original_quarantine = quarantine

            item.installed_identity = _atomic_write_at(
                item.parent_descriptor,
                item.managed.relative.name,
                item.managed.payload,
                expected_identity=item.original_identity,
                on_replace=record_publication,
            )
        _verify_installed_paths(
            root, root_descriptor, plan.root_identity, prepared
        )
    except BaseException as error:
        rollback_failures = _rollback_files(changed)
        _close_prepared(prepared)
        rollback_failures.extend(_rollback_directories(created))
        _close_created(created)
        if rollback_failures:
            raise StagingError(
                f"staging transaction failed ({type(error).__name__}: {error}); "
                "safety-preserving rollback report: "
                + "; ".join(rollback_failures)
            ) from error
        raise
    else:
        cleanup_failures = _cleanup_originals(changed)
        if cleanup_failures:
            raise StagingError(
                "staging files were installed and verified, but obsolete-file cleanup "
                "was incomplete: " + "; ".join(cleanup_failures)
            )
    finally:
        _close_prepared(prepared)
        _close_created(created)
        os.close(root_descriptor)


def _summary(plan: StagingPlan, *, applied: bool) -> str:
    bios = {
        file.relative.name: (len(file.payload), sha256_bytes(file.payload))
        for file in plan.files
        if file.source == "user-supplied BIOS"
    }
    mode = "APPLIED" if applied else "VALIDATED ONLY — no files written"
    location = "macOS volume/possible SD" if plan.is_volume else "local staging directory"
    lines = [
        mode,
        f"Target: {plan.root} ({location})",
        (
            f"Core: {EXPECTED_CORE_ID} {plan.core_version} ({plan.release_date}); "
            f"{'verified release' if plan.release else 'development package'}"
        ),
        f"Package SHA-256: {plan.package_sha256}",
        (
            f"Managed files: {len(plan.new_files)} new, "
            f"{len(plan.replaced_files)} replace, {len(plan.unchanged_files)} unchanged"
        ),
        (
            "Cartridge saves: Swan Song uses its core-specific namespace; this "
            "stager does not copy legacy Saves/wonderswan/common files. Run Swan "
            "Song Doctor and the ROM-aware migration helper after making an SD backup."
        ),
    ]
    if plan.source_commit is not None:
        lines.append(f"Release source commit: {plan.source_commit}")
    for name in ("bw.rom", "color.rom"):
        if name in bios:
            lines.append(f"{name}: {bios[name][0]} bytes, SHA-256 {bios[name][1]}")
        elif plan.release:
            lines.append(f"{name}: not selected; existing destination file was not read or changed")
    if not applied:
        lines.append("Next: review this plan, then rerun with --apply to write the selected target.")
        if plan.is_volume:
            lines.append("A write to this /Volumes target will also require --allow-volume.")
    elif plan.is_volume:
        lines.extend(
            (
                "Next: add only your legally obtained .ws/.wsc files under Assets/wonderswan/common/.",
                "Then eject the Pocket SD cleanly and validate the core on hardware.",
            )
        )
    else:
        lines.extend(
            (
                "Next: inspect this local tree and add only your legally obtained .ws/.wsc files.",
                "Merge its Assets, Cores, and Platforms folders into the SD root; do not use Finder Replace.",
            )
        )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and stage a Swan Song package. Development provenance remains "
            "the default; --verify-release requires exact trusted release identity. "
            "Dry-run is the default; no ROM or BIOS is downloaded."
        )
    )
    parser.add_argument("--staging-dir", required=True, type=pathlib.Path)
    parser.add_argument("--package", required=True, type=pathlib.Path)
    parser.add_argument(
        "--provenance",
        type=pathlib.Path,
        help="package provenance JSON (default: <package>.provenance.json)",
    )
    parser.add_argument(
        "--verify-release",
        action="store_true",
        help="require exact release provenance and checked-in policy authorization",
    )
    parser.add_argument(
        "--expected-package-sha256",
        help="trusted lowercase SHA-256 published for the release ZIP",
    )
    parser.add_argument(
        "--expected-provenance-sha256",
        help="trusted lowercase SHA-256 published for the release provenance sidecar",
    )
    parser.add_argument("--expected-version", help="trusted published core version")
    parser.add_argument(
        "--expected-source-commit",
        help="trusted published full lowercase 40-hex source commit",
    )
    parser.add_argument(
        "--bw-bios",
        type=pathlib.Path,
        help="optional in release mode; development staging still requires it",
    )
    parser.add_argument(
        "--color-bios",
        type=pathlib.Path,
        help="optional in release mode; development staging still requires it",
    )
    parser.add_argument("--apply", action="store_true", help="perform the validated writes")
    parser.add_argument(
        "--allow-volume",
        action="store_true",
        help="with --apply, explicitly permit a target below macOS /Volumes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    provenance = arguments.provenance or arguments.package.with_name(
        arguments.package.name + ".provenance.json"
    )
    try:
        plan = plan_staging(
            staging_dir=arguments.staging_dir,
            package=arguments.package,
            provenance=provenance,
            bw_bios=arguments.bw_bios,
            color_bios=arguments.color_bios,
            verify_release=arguments.verify_release,
            expected_package_sha256=arguments.expected_package_sha256,
            expected_provenance_sha256=arguments.expected_provenance_sha256,
            expected_version=arguments.expected_version,
            expected_source_commit=arguments.expected_source_commit,
        )
        if arguments.apply:
            apply_staging(plan, allow_volume=arguments.allow_volume)
        print(_summary(plan, applied=arguments.apply))
        return 0
    except (StagingError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
