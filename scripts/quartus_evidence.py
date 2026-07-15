#!/usr/bin/env python3
"""Collect a bounded, symlink-safe allowlist of Quartus candidate evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import quartus_container_provenance as container_provenance
import quartus_fit_audit as fit_audit


CHUNK_SIZE = 1024 * 1024
MAX_EVIDENCE_BYTES = 512 * 1024 * 1024
MAX_CONNECTIVITY_REFRESH_BYTES = 72 * 1024 * 1024
MAX_CONNECTIVITY_POLICY_DRAFT_BYTES = 2 * 1024 * 1024
MAX_CONNECTIVITY_ALLOWLIST_DRAFT_BYTES = 2 * 1024 * 1024
CANDIDATE_PROFILE = "candidate"
CONNECTIVITY_REFRESH_PROFILE = "connectivity-refresh"


class EvidenceError(RuntimeError):
    """The candidate evidence tree does not satisfy the upload contract."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON field in Quartus candidate: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class EvidenceFile:
    relative: Path
    max_bytes: int


CANDIDATE_EVIDENCE_FILES = (
    EvidenceFile(Path("quartus-audit-candidate.json"), 8 * 1024 * 1024),
    EvidenceFile(
        Path("quartus-audit-candidate.attestation.json"), 8 * 1024 * 1024
    ),
    EvidenceFile(Path("quartus.log"), 128 * 1024 * 1024),
    EvidenceFile(Path("ap_core.rbf.sha256"), 64 * 1024),
    EvidenceFile(Path("build-metadata.txt"), 1024 * 1024),
    EvidenceFile(Path("toolchain-version.txt"), 1024 * 1024),
    EvidenceFile(Path("build_id.mif"), 1024 * 1024),
    EvidenceFile(Path("container-provenance.json"), 64 * 1024),
    EvidenceFile(Path("container-packages.tsv"), 2 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.rbf"), 32 * 1024 * 1024),
    # Quartus warning 12241 points to the detailed Connectivity Checks tables
    # in the Analysis & Synthesis text report, not to a separate log file.
    EvidenceFile(Path("output_files/ap_core.map.rpt"), 64 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.fit.rpt"), 64 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.asm.rpt"), 64 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.sta.rpt"), 64 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.flow.rpt"), 64 * 1024 * 1024),
)

# A connectivity refresh is discovery evidence, never a fit candidate.  Keep
# only enough material to bind the exact synthesis report to its source and
# toolchain.  In particular, this profile must not distribute an RBF, Quartus
# log, fitter report, or TimeQuest report that could be mistaken for signoff.
CONNECTIVITY_REFRESH_EVIDENCE_FILES = (
    EvidenceFile(Path("build-metadata.txt"), 1024 * 1024),
    EvidenceFile(Path("toolchain-version.txt"), 1024 * 1024),
    EvidenceFile(Path("container-provenance.json"), 64 * 1024),
    EvidenceFile(Path("container-packages.tsv"), 2 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.map.rpt"), 64 * 1024 * 1024),
)

CONNECTIVITY_REFRESH_DRAFT_FILES = (
    EvidenceFile(
        Path("connectivity-warning-12241.draft.json"),
        MAX_CONNECTIVITY_POLICY_DRAFT_BYTES,
    ),
    EvidenceFile(
        Path("connectivity-warning-12241.draft.tsv"),
        MAX_CONNECTIVITY_ALLOWLIST_DRAFT_BYTES,
    ),
)

EVIDENCE_PROFILES = {
    CANDIDATE_PROFILE: (CANDIDATE_EVIDENCE_FILES, MAX_EVIDENCE_BYTES),
    CONNECTIVITY_REFRESH_PROFILE: (
        CONNECTIVITY_REFRESH_EVIDENCE_FILES,
        MAX_CONNECTIVITY_REFRESH_BYTES,
    ),
}

# Preserve the original import surface for callers that inspect the candidate
# allowlist directly.  collect_evidence defaults to this same candidate lane.
EVIDENCE_FILES = CANDIDATE_EVIDENCE_FILES


def _require_plain_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"{label} does not exist: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise EvidenceError(f"{label} must be a nonsymlink directory: {path}")


def _open_source(root: Path, item: EvidenceFile) -> int | None:
    parent = root
    for component in item.relative.parts[:-1]:
        parent = parent / component
        try:
            metadata = parent.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise EvidenceError(
                f"evidence parent must be a nonsymlink directory: {item.relative}"
            )

    source = root / item.relative
    try:
        metadata = source.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EvidenceError(f"evidence input must be a regular file: {item.relative}")
    if metadata.st_size > item.max_bytes:
        raise EvidenceError(
            f"evidence input exceeds {item.max_bytes} bytes: {item.relative}"
        )

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_dev != metadata.st_dev
        or opened.st_ino != metadata.st_ino
    ):
        os.close(descriptor)
        raise EvidenceError(f"evidence input changed while opening: {item.relative}")
    return descriptor


def _copy_source(descriptor: int, output: Path, item: EvidenceFile) -> None:
    destination = output / item.relative
    copied = 0
    with os.fdopen(descriptor, "rb", closefd=True) as source:
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        output_descriptor = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(output_descriptor, "wb", closefd=True) as target:
                while chunk := source.read(CHUNK_SIZE):
                    copied += len(chunk)
                    if copied > item.max_bytes:
                        raise EvidenceError(
                            f"evidence input grew beyond {item.max_bytes} bytes: "
                            f"{item.relative}"
                        )
                    target.write(chunk)
                target.flush()
                os.fchmod(target.fileno(), 0o644)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def _validate_container_pair(
    output: Path, collected: list[Path]
) -> dict[str, object] | None:
    provenance_path = Path("container-provenance.json")
    packages_path = Path("container-packages.tsv")
    has_provenance = provenance_path in collected
    has_packages = packages_path in collected
    if has_provenance != has_packages:
        raise EvidenceError("container provenance and package manifest must appear together")
    if not has_provenance:
        return None
    try:
        return container_provenance.validate_provenance(
            output / provenance_path, output / packages_path
        )
    except container_provenance.ProvenanceError as error:
        raise EvidenceError(f"invalid container provenance: {error}") from error


def _file_identity(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(CHUNK_SIZE):
            digest.update(block)
            size += len(block)
    return {"sha256": digest.hexdigest(), "size": size}


def _validate_candidate_binding(
    output: Path,
    collected: list[Path],
    validated_container: dict[str, object] | None,
) -> None:
    candidate_path = Path("quartus-audit-candidate.json")
    if candidate_path not in collected:
        return
    if validated_container is None:
        raise EvidenceError("successful candidate requires container provenance pair")
    try:
        document = json.loads(
            (output / candidate_path).read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError("Quartus candidate audit is not valid UTF-8 JSON") from error
    audit = document.get("quartus_audit") if isinstance(document, dict) else None
    if not isinstance(audit, dict):
        raise EvidenceError("Quartus candidate audit envelope is invalid")
    artifacts = audit.get("artifacts")
    if not isinstance(artifacts, dict):
        raise EvidenceError("Quartus candidate artifact binding is missing")
    required_bindings = fit_audit.REQUIRED_ARTIFACTS
    declared_bindings = set(artifacts)
    expected_bindings = set(required_bindings)
    if declared_bindings != expected_bindings:
        missing = sorted(expected_bindings - declared_bindings)
        unknown = sorted(declared_bindings - expected_bindings)
        raise EvidenceError(
            "Quartus candidate has unknown or missing audited artifact members: "
            f"missing={missing!r}, unknown={unknown!r}"
        )
    for relative in required_bindings:
        if Path(relative) not in collected:
            raise EvidenceError(
                f"audited candidate requires collected {relative}"
            )
        if artifacts.get(relative) != _file_identity(output / relative):
            raise EvidenceError(
                f"Quartus candidate does not bind collected {relative}"
            )
    if audit.get("container_provenance") != validated_container:
        raise EvidenceError("Quartus candidate container document does not match evidence")
    try:
        recomputed_document = fit_audit.audit(output)
    except (fit_audit.AuditError, OSError) as error:
        raise EvidenceError(
            f"could not reproduce Quartus candidate from collected evidence: {error}"
        ) from error
    if document != recomputed_document:
        raise EvidenceError(
            "Quartus candidate document does not match the audit recomputed from "
            "collected evidence"
        )


def _clear_output(output: Path) -> None:
    for path in sorted(output.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()


def validate_connectivity_refresh_bundle(output: Path) -> list[Path]:
    """Validate the exact, total-bounded refresh tree immediately before upload."""

    _require_plain_directory(output, "connectivity refresh evidence root")
    limits = {
        item.relative: item.max_bytes
        for item in (
            *CONNECTIVITY_REFRESH_EVIDENCE_FILES,
            *CONNECTIVITY_REFRESH_DRAFT_FILES,
        )
    }
    expected_files = set(limits)
    expected_directories = {Path("output_files")}
    observed_files: set[Path] = set()
    observed_directories: set[Path] = set()
    total_bytes = 0

    for path in output.rglob("*"):
        relative = path.relative_to(output)
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise EvidenceError(
                f"connectivity refresh bundle contains a symlink: {relative}"
            )
        if stat.S_ISDIR(metadata.st_mode):
            observed_directories.add(relative)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceError(
                "connectivity refresh bundle contains a non-regular member: "
                f"{relative}"
            )
        observed_files.add(relative)
        maximum = limits.get(relative)
        if maximum is None:
            raise EvidenceError(
                f"connectivity refresh bundle contains an unknown file: {relative}"
            )
        if metadata.st_size <= 0:
            raise EvidenceError(
                f"connectivity refresh bundle contains an empty file: {relative}"
            )
        if metadata.st_size > maximum:
            raise EvidenceError(
                f"connectivity refresh bundle member exceeds {maximum} bytes: "
                f"{relative}"
            )
        total_bytes += metadata.st_size

    missing = sorted(expected_files - observed_files)
    unknown_directories = sorted(observed_directories - expected_directories)
    missing_directories = sorted(expected_directories - observed_directories)
    if missing or unknown_directories or missing_directories:
        raise EvidenceError(
            "connectivity refresh bundle members are not exact: "
            f"missing={missing!r}, unknown_directories={unknown_directories!r}, "
            f"missing_directories={missing_directories!r}"
        )
    if total_bytes > MAX_CONNECTIVITY_REFRESH_BYTES:
        raise EvidenceError(
            "connectivity refresh bundle exceeds its total size bound: "
            f"{total_bytes} > {MAX_CONNECTIVITY_REFRESH_BYTES}"
        )
    return sorted(observed_files)


def collect_evidence(
    artifacts: Path,
    output: Path,
    *,
    profile: str = CANDIDATE_PROFILE,
) -> list[Path]:
    """Copy only present allowlisted files; missing files are valid after a failed fit."""

    try:
        evidence_files, maximum_bytes = EVIDENCE_PROFILES[profile]
    except KeyError as error:
        raise EvidenceError(f"unknown Quartus evidence profile: {profile}") from error
    if sum(item.max_bytes for item in evidence_files) > maximum_bytes:
        raise EvidenceError(
            f"Quartus {profile} evidence allowlist exceeds its total size bound"
        )
    _require_plain_directory(artifacts, "artifact root")
    _require_plain_directory(output, "evidence output")
    if os.path.samefile(artifacts, output):
        raise EvidenceError("artifact root and evidence output must be different")
    if any(output.iterdir()):
        raise EvidenceError(f"evidence output must be empty: {output}")

    opened: list[tuple[EvidenceFile, int]] = []
    try:
        for item in evidence_files:
            descriptor = _open_source(artifacts, item)
            if descriptor is not None:
                opened.append((item, descriptor))
        if profile == CONNECTIVITY_REFRESH_PROFILE:
            present = {item.relative for item, _ in opened}
            required = {item.relative for item in evidence_files}
            if present != required:
                raise EvidenceError(
                    "connectivity refresh requires complete discovery evidence: "
                    f"missing={sorted(required - present)!r}"
                )

        collected: list[Path] = []
        try:
            while opened:
                item, descriptor = opened.pop(0)
                _copy_source(descriptor, output, item)
                collected.append(item.relative)
            validated_container = _validate_container_pair(output, collected)
            _validate_candidate_binding(
                output, collected, validated_container
            )
            return collected
        except BaseException:
            _clear_output(output)
            raise
    finally:
        for _, descriptor in opened:
            os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=tuple(EVIDENCE_PROFILES),
        default=CANDIDATE_PROFILE,
    )
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-connectivity-refresh-bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.validate_connectivity_refresh_bundle is not None:
            if args.artifacts is not None or args.output is not None:
                raise EvidenceError(
                    "bundle validation cannot be combined with evidence collection"
                )
            collected = validate_connectivity_refresh_bundle(
                args.validate_connectivity_refresh_bundle
            )
            print(
                "validated exact bounded connectivity-refresh bundle "
                f"({len(collected)} files)"
            )
            return 0
        if args.artifacts is None or args.output is None:
            raise EvidenceError(
                "evidence collection requires --artifacts and --output"
            )
        collected = collect_evidence(args.artifacts, args.output, profile=args.profile)
    except (EvidenceError, OSError) as error:
        print(f"quartus_evidence.py: {error}", file=sys.stderr)
        return 1
    print(
        f"collected {len(collected)} bounded {args.profile} Quartus evidence file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
