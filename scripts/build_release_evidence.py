#!/usr/bin/env python3
"""Build a relocated, revalidated Swan Song Release Evidence V2 bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Iterable

import package_core
import quartus_evidence
import quartus_fit_audit
from known_title_compatibility import verify_manifest as verify_known_title_manifest
from pocket_hardware_qa import verify_manifest as verify_hardware_qa_manifest


RELEASE_EVIDENCE_FILENAME = "release-evidence.json"
HARDWARE_MANIFEST_FILENAME = "hardware-qa-manifest.json"
HARDWARE_INVENTORY_FILENAME = "hardware-qa-inventory.json"
KNOWN_TITLE_CATALOGUE = Path(__file__).resolve().parents[1] / "known-title-compatibility.json"
KNOWN_TITLE_CATALOGUE_FILENAME = "known-title-compatibility-catalogue.json"
KNOWN_TITLE_MANIFEST_FILENAME = "known-title-compatibility-manifest.json"
MAX_QA_JSON_BYTES = 16 * 1024 * 1024
ATTESTATION_FILENAME = "quartus-audit-candidate.attestation.json"


class ReleaseEvidenceError(RuntimeError):
    """An input cannot prove the complete final release-evidence claim."""


def _strict_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _read_plain_file(path, label, MAX_QA_JSON_BYTES)
    try:
        document = package_core.strict_json_loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, package_core.StrictJsonError) as error:
        raise ReleaseEvidenceError(f"{label} is not strict UTF-8 JSON: {error}") from error
    if not isinstance(document, dict):
        raise ReleaseEvidenceError(f"{label} must contain a JSON object")
    return document, payload


def _read_plain_file(path: Path, label: str, maximum: int | None = None) -> bytes:
    path = path.absolute()
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise ReleaseEvidenceError(f"{label} does not exist: {path}") from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ReleaseEvidenceError(f"{label} must be a regular nonsymlink file: {path}")
    if maximum is not None and before.st_size > maximum:
        raise ReleaseEvidenceError(f"{label} exceeds {maximum} bytes: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
        ):
            raise ReleaseEvidenceError(f"{label} changed while opening: {path}")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            total += len(chunk)
            if maximum is not None and total > maximum:
                raise ReleaseEvidenceError(f"{label} grew beyond {maximum} bytes: {path}")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _identity(path: Path, *, filename: str | None = None) -> dict[str, object]:
    return {
        "filename": filename if filename is not None else path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _relative_path(value: object, label: str) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ReleaseEvidenceError(f"{label} must be a nonempty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute():
        return None
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseEvidenceError(f"{label} is not a safe relative path: {value!r}")
    return path


def _source_path(base: Path, value: object, label: str) -> tuple[Path, PurePosixPath | None]:
    relative = _relative_path(value, label)
    if relative is None:
        assert isinstance(value, str)
        return Path(value), None
    return base.joinpath(*relative.parts), relative


def _same_payload(left: Path, right: Path) -> bool:
    return left.stat().st_size == right.stat().st_size and _sha256(left) == _sha256(right)


def _copy_snapshot(source: Path, destination: Path, label: str) -> None:
    source = source.absolute()
    try:
        metadata = source.lstat()
    except FileNotFoundError as error:
        raise ReleaseEvidenceError(f"{label} does not exist: {source}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ReleaseEvidenceError(f"{label} must be a regular nonsymlink file: {source}")
    if destination.exists() or destination.is_symlink():
        if (
            destination.is_symlink()
            or not destination.is_file()
            or not _same_payload(source, destination)
        ):
            raise ReleaseEvidenceError(
                f"relocated evidence path collision has different bytes: {destination}"
            )
        return

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    read_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    source_fd = os.open(source, read_flags)
    try:
        opened = os.fstat(source_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise ReleaseEvidenceError(f"{label} changed while opening: {source}")
        write_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        destination_fd = os.open(destination, write_flags, 0o600)
        try:
            with os.fdopen(source_fd, "rb", closefd=False) as input_stream, os.fdopen(
                destination_fd, "wb", closefd=False
            ) as output_stream:
                shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
                output_stream.flush()
                os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        os.close(source_fd)


def _copy_relative_reference(
    *, base: Path, value: object, destination_root: Path, label: str
) -> None:
    source, relative = _source_path(base, value, label)
    if relative is None:
        # Absolute inventory paths deliberately retain their original meaning.
        # The strict post-relocation verifier will reopen them before publication.
        return
    _copy_snapshot(source, destination_root.joinpath(*relative.parts), label)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseEvidenceError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReleaseEvidenceError(f"{label} must be an array")
    return value


def _relocate_hardware_dependencies(
    *,
    manifest_path: Path,
    manifest_document: dict[str, Any],
    inventory_path: Path,
    inventory_document: dict[str, Any],
    hardware_summary: dict[str, Any],
    destination_root: Path,
) -> None:
    manifest = _object(manifest_document.get("hardware_qa"), "hardware QA manifest")
    for index, entry in enumerate(_array(manifest.get("artifacts"), "hardware QA artifacts")):
        artifact = _object(entry, f"hardware QA artifacts[{index}]")
        _copy_relative_reference(
            base=manifest_path.parent,
            value=artifact.get("path"),
            destination_root=destination_root,
            label=f"hardware QA artifact {artifact.get('id', index)!r}",
        )

    inventory = _object(
        inventory_document.get("hardware_qa_inventory"), "hardware QA inventory"
    )
    firmware = _object(inventory.get("firmware"), "hardware QA inventory firmware")
    _copy_relative_reference(
        base=inventory_path.parent,
        value=firmware.get("update_path"),
        destination_root=destination_root,
        label="hardware QA firmware",
    )
    for name in ("pocket", "dock"):
        device = _object(inventory.get(name), f"hardware QA inventory {name}")
        _copy_relative_reference(
            base=inventory_path.parent,
            value=device.get("device_id_path"),
            destination_root=destination_root,
            label=f"hardware QA {name} device identity",
        )

    core = _object(inventory.get("core"), "hardware QA inventory core")
    for field in (
        "core_json_path",
        "interact_json_path",
        "raw_rbf_path",
        "installed_bitstream_path",
    ):
        _copy_relative_reference(
            base=inventory_path.parent,
            value=core.get(field),
            destination_root=destination_root,
            label=f"hardware QA inventory {field}",
        )

    installed_root_source, installed_root_relative = _source_path(
        inventory_path.parent,
        core.get("installed_dist_path"),
        "hardware QA installed_dist_path",
    )
    installed_payloads = _object(
        _object(hardware_summary.get("core"), "verified hardware core").get(
            "installed_payloads"
        ),
        "verified hardware installed payloads",
    )
    if installed_root_relative is not None:
        installed_root_destination = destination_root.joinpath(
            *installed_root_relative.parts
        )
        for name in sorted(installed_payloads):
            relative = _relative_path(name, "verified installed payload name")
            if relative is None:
                raise ReleaseEvidenceError("verified installed payload name is absolute")
            _copy_snapshot(
                installed_root_source.joinpath(*relative.parts),
                installed_root_destination.joinpath(*relative.parts),
                f"hardware QA installed payload {name}",
            )

    for collection, singular in (("bios", "BIOS"), ("roms", "ROM")):
        for index, entry in enumerate(
            _array(inventory.get(collection), f"hardware QA inventory {collection}")
        ):
            item = _object(entry, f"hardware QA inventory {collection}[{index}]")
            _copy_relative_reference(
                base=inventory_path.parent,
                value=item.get("path"),
                destination_root=destination_root,
                label=f"hardware QA {singular} {item.get('id', index)!r}",
            )


def _relocate_known_title_dependencies(
    *,
    manifest_path: Path,
    manifest_document: dict[str, Any],
    destination_root: Path,
) -> None:
    body = _object(
        manifest_document.get("known_title_compatibility"),
        "known-title compatibility manifest",
    )
    for index, entry in enumerate(
        _array(body.get("artifacts"), "known-title compatibility artifacts")
    ):
        artifact = _object(entry, f"known-title compatibility artifacts[{index}]")
        _copy_relative_reference(
            base=manifest_path.parent,
            value=artifact.get("path"),
            destination_root=destination_root,
            label=f"known-title compatibility artifact {artifact.get('id', index)!r}",
        )


def _relocate_known_title_catalogue_fixtures(
    *,
    catalogue_path: Path,
    catalogue_document: dict[str, Any],
    destination_root: Path,
) -> None:
    """Snapshot only the checked-in open fixtures used by a relocated catalogue.

    ``known_title_compatibility`` deliberately resolves fixture paths relative
    to its catalogue.  The evidence bundle carries a relocated catalogue, so
    its public/open fixture dependencies must move with it.  Commercial cases
    have no fixture paths and are never copied by this function.
    """

    body = _object(
        catalogue_document.get("known_title_compatibility"),
        "known-title compatibility catalogue",
    )
    source_root = catalogue_path.resolve().parent
    copied: set[PurePosixPath] = set()
    for index, raw in enumerate(
        _array(body.get("cases"), "known-title compatibility catalogue cases")
    ):
        where = f"known-title compatibility catalogue cases[{index}]"
        item = _object(raw, where)
        case_class = item.get("class")
        if case_class == "commercial":
            if (
                item.get("fixture_path") is not None
                or item.get("fixture_sha256") is not None
            ):
                raise ReleaseEvidenceError(
                    f"{where} commercial case must not contain a fixture"
                )
            continue
        if case_class != "open_sanity":
            raise ReleaseEvidenceError(f"{where} has an unsupported case class")

        relative = _relative_path(item.get("fixture_path"), f"{where}.fixture_path")
        if relative is None:
            raise ReleaseEvidenceError(
                f"{where}.fixture_path must be repository-relative"
            )
        if relative in copied:
            raise ReleaseEvidenceError(
                f"known-title catalogue repeats open fixture {relative.as_posix()}"
            )
        copied.add(relative)

        expected_digest = item.get("fixture_sha256")
        if (
            not isinstance(expected_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        ):
            raise ReleaseEvidenceError(f"{where}.fixture_sha256 is invalid")

        source = source_root.joinpath(*relative.parts)
        try:
            resolved_source = source.resolve(strict=True)
            resolved_source.relative_to(source_root)
        except (OSError, ValueError) as error:
            raise ReleaseEvidenceError(
                f"{where}.fixture_path escapes or is missing: {relative.as_posix()}"
            ) from error
        if source.is_symlink() or not resolved_source.is_file():
            raise ReleaseEvidenceError(
                f"{where}.fixture_path must be a regular nonsymlink file"
            )

        destination = destination_root.joinpath(*relative.parts)
        _copy_snapshot(resolved_source, destination, f"{where} open fixture")
        if _sha256(destination) != expected_digest:
            destination.unlink(missing_ok=True)
            raise ReleaseEvidenceError(
                f"{where}.fixture_path does not match its catalogue SHA-256"
            )


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    payload = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(descriptor)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def _assert_source_identity(
    audit: dict[str, Any], source_commit: str, source_date_epoch: int
) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ReleaseEvidenceError("--source-commit must be a full lowercase 40-hex SHA")
    if isinstance(source_date_epoch, bool) or not isinstance(source_date_epoch, int):
        raise ReleaseEvidenceError("--source-date-epoch must be an integer")
    provenance = _object(audit.get("provenance"), "Quartus audit provenance")
    expected = {
        "source_commit": source_commit,
        "source_date_epoch": str(source_date_epoch),
        "platform": "linux/amd64",
        "quartus": "21.1.1.850 Lite",
        "device": "5CEBA4F23C8",
    }
    if any(provenance.get(key) != value for key, value in expected.items()):
        raise ReleaseEvidenceError(
            "explicit source commit/epoch do not match the accepted Quartus audit"
        )


def build_release_evidence(
    *,
    artifacts: Path,
    signed_artifacts: tuple[Path, Path],
    signed_build_origins: dict[str, object],
    hardware_manifest: Path,
    hardware_inventory: Path,
    known_title_manifest: Path,
    output: Path,
    source_commit: str,
    source_date_epoch: int,
    compressed_bitstream_reviewed: bool,
) -> Path:
    """Create an immutable private bundle consumed directly by package_core.py."""

    if not compressed_bitstream_reviewed:
        raise ReleaseEvidenceError(
            "final evidence requires explicit --compressed-bitstream-reviewed acceptance"
        )
    if output.name != RELEASE_EVIDENCE_FILENAME:
        raise ReleaseEvidenceError(
            f"--output filename must be {RELEASE_EVIDENCE_FILENAME}"
        )
    bundle = output.absolute().parent
    if bundle.exists() or bundle.is_symlink():
        raise ReleaseEvidenceError(
            "release-evidence bundle directory must not already exist: " + str(bundle)
        )
    parent = bundle.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ReleaseEvidenceError(
            f"release-evidence bundle parent must be an existing nonsymlink directory: {parent}"
        )
    artifacts = artifacts.absolute()
    signed_artifacts = tuple(path.absolute() for path in signed_artifacts)
    if signed_artifacts[0].resolve() != artifacts.resolve():
        raise ReleaseEvidenceError(
            "primary --artifacts must be signed build a"
        )
    if signed_artifacts[0].resolve() == signed_artifacts[1].resolve():
        raise ReleaseEvidenceError("signed build artifact roots must be distinct")
    if signed_build_origins.get("magic") != "SWAN_SONG_SIGNED_BUILD_PAIR_V1":
        raise ReleaseEvidenceError("signed build origins are missing or malformed")
    origin_builds = signed_build_origins.get("builds")
    if (
        not isinstance(origin_builds, list)
        or len(origin_builds) != 2
        or [entry.get("label") if isinstance(entry, dict) else None for entry in origin_builds]
        != ["a", "b"]
    ):
        raise ReleaseEvidenceError("signed build origins must contain exact a/b records")
    hardware_manifest = hardware_manifest.absolute()
    hardware_inventory = hardware_inventory.absolute()
    known_title_manifest = known_title_manifest.absolute()
    if artifacts == bundle or bundle in artifacts.parents:
        raise ReleaseEvidenceError("--output bundle must be separate from --artifacts")

    manifest_document, manifest_bytes = _strict_json(
        hardware_manifest, "hardware QA manifest"
    )
    inventory_document, inventory_bytes = _strict_json(
        hardware_inventory, "hardware QA inventory"
    )
    known_title_document, known_title_bytes = _strict_json(
        known_title_manifest, "known-title compatibility manifest"
    )
    catalogue_document, catalogue_bytes = _strict_json(
        KNOWN_TITLE_CATALOGUE, "checked-in known-title compatibility catalogue"
    )
    try:
        original_hardware_summary = verify_hardware_qa_manifest(
            hardware_manifest, hardware_inventory, require_pass=True
        )
    except ValueError as error:
        raise ReleaseEvidenceError(f"hardware QA is not accepted: {error}") from error
    try:
        original_known_title_summary = verify_known_title_manifest(
            KNOWN_TITLE_CATALOGUE, known_title_manifest, require_pass=True
        )
    except ValueError as error:
        raise ReleaseEvidenceError(
            f"known-title compatibility is not accepted: {error}"
        ) from error
    _object(original_known_title_summary.get("run"), "verified known-title run")

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{bundle.name}.", dir=parent)
    )
    published = False
    try:
        try:
            collected = quartus_evidence.collect_evidence(
                artifacts, temporary, profile=quartus_evidence.CANDIDATE_PROFILE
            )
        except (quartus_evidence.EvidenceError, OSError) as error:
            raise ReleaseEvidenceError(f"Quartus evidence collection failed: {error}") from error
        required_quartus = {
            item.relative for item in quartus_evidence.CANDIDATE_EVIDENCE_FILES
        }
        if set(collected) != required_quartus:
            raise ReleaseEvidenceError(
                "release evidence requires the complete successful Quartus candidate bundle"
            )

        for index, label in enumerate(("a", "b")):
            origin = _object(origin_builds[index], f"signed build {label} origin")
            signed_root = signed_artifacts[index]
            signed_audit = signed_root / package_core.QUARTUS_AUDIT_FILENAME
            signed_bundle = signed_root / ATTESTATION_FILENAME
            audit_destination = (
                temporary
                / "signed-builds"
                / label
                / package_core.QUARTUS_AUDIT_FILENAME
            )
            bundle_destination = (
                temporary / "signed-builds" / label / ATTESTATION_FILENAME
            )
            _copy_snapshot(
                signed_audit,
                audit_destination,
                f"signed build {label} candidate audit",
            )
            _copy_snapshot(
                signed_bundle,
                bundle_destination,
                f"signed build {label} attestation bundle",
            )
            for key, destination in (
                ("candidate_audit", audit_destination),
                ("attestation_bundle", bundle_destination),
            ):
                expected = _object(origin.get(key), f"signed build {label} {key}")
                observed = _identity(
                    destination,
                    filename=destination.relative_to(temporary).as_posix(),
                )
                if expected != observed:
                    raise ReleaseEvidenceError(
                        f"signed build {label} {key} identity does not match input"
                    )

        manifest_copy = temporary / HARDWARE_MANIFEST_FILENAME
        inventory_copy = temporary / HARDWARE_INVENTORY_FILENAME
        manifest_copy.write_bytes(manifest_bytes)
        inventory_copy.write_bytes(inventory_bytes)
        os.chmod(manifest_copy, 0o600)
        os.chmod(inventory_copy, 0o600)
        _relocate_hardware_dependencies(
            manifest_path=hardware_manifest,
            manifest_document=manifest_document,
            inventory_path=hardware_inventory,
            inventory_document=inventory_document,
            hardware_summary=original_hardware_summary,
            destination_root=temporary,
        )
        known_title_catalogue_copy = temporary / KNOWN_TITLE_CATALOGUE_FILENAME
        known_title_manifest_copy = temporary / KNOWN_TITLE_MANIFEST_FILENAME
        known_title_catalogue_copy.write_bytes(catalogue_bytes)
        known_title_manifest_copy.write_bytes(known_title_bytes)
        os.chmod(known_title_catalogue_copy, 0o600)
        os.chmod(known_title_manifest_copy, 0o600)
        _relocate_known_title_catalogue_fixtures(
            catalogue_path=KNOWN_TITLE_CATALOGUE,
            catalogue_document=catalogue_document,
            destination_root=temporary,
        )
        _relocate_known_title_dependencies(
            manifest_path=known_title_manifest,
            manifest_document=known_title_document,
            destination_root=temporary,
        )
        try:
            hardware_summary = verify_hardware_qa_manifest(
                manifest_copy, inventory_copy, require_pass=True
            )
        except ValueError as error:
            raise ReleaseEvidenceError(
                f"relocated hardware QA snapshot is not accepted: {error}"
            ) from error
        try:
            known_title_summary = verify_known_title_manifest(
                known_title_catalogue_copy,
                known_title_manifest_copy,
                require_pass=True,
            )
        except ValueError as error:
            raise ReleaseEvidenceError(
                f"relocated known-title compatibility snapshot is not accepted: {error}"
            ) from error

        audit_document = quartus_fit_audit.audit(temporary)
        audit = _object(audit_document.get("quartus_audit"), "Quartus audit")
        _assert_source_identity(audit, source_commit, source_date_epoch)
        candidate_gates = _object(audit.get("candidate_gates"), "Quartus candidate gates")
        failed_candidate = sorted(
            gate
            for gate in package_core.AUDIT_REQUIRED_TRUE_GATES
            if candidate_gates.get(gate) is not True
        )
        if audit.get("audit_pass") is not True or failed_candidate:
            raise ReleaseEvidenceError(
                "Quartus candidate gates are not accepted: "
                + ", ".join(failed_candidate or ["audit_pass"])
            )
        if candidate_gates.get("compressed_bitstream") is not None:
            raise ReleaseEvidenceError(
                "candidate audit must leave compressed_bitstream unclaimed"
            )
        if any(candidate_gates.get(name) is not False for name in ("pocket_hardware", "dock_hardware")):
            raise ReleaseEvidenceError(
                "candidate audit must leave Pocket and Dock hardware gates false"
            )

        rbf = temporary / "output_files/ap_core.rbf"
        build_id = temporary / "build_id.mif"
        audit_path = temporary / package_core.QUARTUS_AUDIT_FILENAME
        reports = {
            kind: temporary / f"output_files/ap_core.{kind}.rpt"
            for kind in ("flow", "fit", "sta")
        }
        rbf_identity = _identity(rbf, filename=rbf.name)
        raw_hardware_rbf = _object(
            _object(hardware_summary.get("core"), "verified hardware core").get(
                "raw_rbf"
            ),
            "verified hardware raw RBF",
        )
        if raw_hardware_rbf != rbf_identity:
            raise ReleaseEvidenceError(
                "hardware QA raw RBF does not match the accepted Quartus candidate"
            )
        known_title_run = _object(
            known_title_summary.get("run"), "verified relocated known-title run"
        )
        if known_title_run.get("core_commit") != source_commit:
            raise ReleaseEvidenceError(
                "relocated known-title compatibility source commit does not match release"
            )
        if known_title_run.get("raw_rbf_sha256") != rbf_identity["sha256"]:
            raise ReleaseEvidenceError(
                "known-title compatibility raw RBF does not match the accepted Quartus candidate"
            )

        final_gates = {
            "flow_success": candidate_gates["flow_success"] is True,
            "fit_success": candidate_gates["fit_success"] is True,
            "setup_timing": candidate_gates["setup_timing"] is True,
            "hold_timing": candidate_gates["hold_timing"] is True,
            "recovery_timing": candidate_gates["recovery_timing"] is True,
            "removal_timing": candidate_gates["removal_timing"] is True,
            "no_unconstrained_paths": candidate_gates["no_unconstrained_paths"] is True,
            "no_critical_warnings": candidate_gates["no_critical_warnings"] is True,
            "compressed_bitstream": True,
            "pocket_hardware": True,
            "dock_hardware": True,
        }
        if not all(final_gates.values()):
            raise ReleaseEvidenceError("one or more derived final release gates failed")

        document = {
            "release_evidence": {
                "magic": package_core.RELEASE_EVIDENCE_V2,
                "source_commit": source_commit,
                "source_date_epoch": source_date_epoch,
                "quartus_version": package_core.RELEASE_QUARTUS_VERSION,
                "rbf": rbf_identity,
                "build_id": _identity(build_id),
                "reports": {
                    kind: _identity(path, filename=f"output_files/{path.name}")
                    for kind, path in reports.items()
                },
                "quartus_audit": _identity(audit_path),
                "signed_build_origins": signed_build_origins,
                "hardware_qa": {
                    "manifest": _identity(manifest_copy),
                    "inventory": _identity(inventory_copy),
                },
                "known_title_compatibility": {
                    "catalogue": _identity(known_title_catalogue_copy),
                    "manifest": _identity(known_title_manifest_copy),
                },
                "gates": final_gates,
            }
        }
        staged_output = temporary / RELEASE_EVIDENCE_FILENAME
        _write_json_atomic(staged_output, document)
        try:
            package_core.validate_build_evidence(
                staged_output, rbf.read_bytes(), rbf.name
            )
        except (ValueError, OSError) as error:
            raise ReleaseEvidenceError(
                f"generated evidence failed the package validator: {error}"
            ) from error

        os.replace(temporary, bundle)
        published = True
        directory = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return bundle / RELEASE_EVIDENCE_FILENAME
    except quartus_fit_audit.AuditError as error:
        raise ReleaseEvidenceError(f"Quartus audit failed: {error}") from error
    finally:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Direct Release Evidence V2 assembly is disabled. Use "
            "scripts/assemble_stable_release.py; it verifies two distinct signed "
            "Quartus workflow executions."
        )
    )
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if any(argument in {"-h", "--help"} for argument in arguments):
        parser.parse_args(arguments)
    print(
        "build_release_evidence.py: direct Release Evidence V2 assembly is disabled; "
        "use assemble_stable_release.py so two distinct signed workflow executions "
        "are verified",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
