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


EVIDENCE_FILES = (
    EvidenceFile(Path("quartus-audit-candidate.json"), 8 * 1024 * 1024),
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


def collect_evidence(artifacts: Path, output: Path) -> list[Path]:
    """Copy only present allowlisted files; missing files are valid after a failed fit."""

    if sum(item.max_bytes for item in EVIDENCE_FILES) > MAX_EVIDENCE_BYTES:
        raise EvidenceError("Quartus evidence allowlist exceeds its total size bound")
    _require_plain_directory(artifacts, "artifact root")
    _require_plain_directory(output, "evidence output")
    if os.path.samefile(artifacts, output):
        raise EvidenceError("artifact root and evidence output must be different")
    if any(output.iterdir()):
        raise EvidenceError(f"evidence output must be empty: {output}")

    opened: list[tuple[EvidenceFile, int]] = []
    try:
        for item in EVIDENCE_FILES:
            descriptor = _open_source(artifacts, item)
            if descriptor is not None:
                opened.append((item, descriptor))

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
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        collected = collect_evidence(args.artifacts, args.output)
    except (EvidenceError, OSError) as error:
        print(f"quartus_evidence.py: {error}", file=sys.stderr)
        return 1
    print(f"collected {len(collected)} bounded Quartus evidence file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
