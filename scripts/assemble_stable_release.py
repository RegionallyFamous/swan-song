#!/usr/bin/env python3
"""Assemble a complete Swan Song stable release with signed build provenance.

The default operation is a read-only plan.  ``--apply`` is deliberately
required before any durable output is created.  This program never publishes;
it lets GitHub CLI obtain the current official Sigstore trust material while
verifying the two workflow-generated attestation bundles.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterable

import build_release_evidence
from known_title_compatibility import verify_manifest as verify_known_title_manifest
from license_manifest import validate_license_manifest
import package_core
from package_validator import ValidatedDistribution, validate_distribution
from pocket_hardware_qa import verify_manifest as verify_hardware_qa_manifest
import quartus_evidence
import quartus_fit_audit
import stage_pocket_sd


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
RELEASE_POLICY = ROOT / "release-policy.json"
KNOWN_TITLE_CATALOGUE = ROOT / "known-title-compatibility.json"
MAGIC = "SWAN_SONG_STABLE_RELEASE_V1"
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
RUN_INVOCATION_RE = re.compile(
    r"https://github\.com/RegionallyFamous/swansong-core/actions/runs/"
    r"([1-9][0-9]*)/attempts/([1-9][0-9]*)\Z"
)
MAX_SOURCE_ARCHIVE_BYTES = 512 * 1024 * 1024
RELEASE_BODY_FILENAME = "release-body.md"
SIGNED_PROVENANCE_FILENAME = "signed-quartus-provenance.tar"
ATTESTATION_FILENAME = "quartus-audit-candidate.attestation.json"
ATTESTATION_REPOSITORY = "RegionallyFamous/swansong-core"
ATTESTATION_WORKFLOW = (
    "github.com/RegionallyFamous/swansong-core/.github/workflows/quartus-fit.yml"
)
ATTESTATION_SOURCE_REF = "refs/heads/main"
RELEASE_DECISION_LABELS = (
    "Original-work license",
    "First public version",
    "Release date",
    "Firmware floor",
    "Distribution authorization",
    "Run the complete regression",
    "Build the final commit",
    "Test the exact final package",
    "Preserve the accepted hardware manifest",
    "Preserve both signed Quartus candidates",
    "Publish the exact seven-file release",
    "Immutable release protection",
)
RELEASE_DOCUMENT_STALE_MARKERS = {
    "README.md": (
        "swan song is still in development. there is not yet a verified public",
        "there is nothing for most players to install yet",
        "blocks installation because distribution and licensing are not authorized yet",
    ),
    "docs/wiki/Home.md": (
        "swan song does not have a verified public release",
    ),
    "docs/wiki/Install-Swan-Song.md": (
        "there is no verified swan song release to install yet",
    ),
    "POCKET_FIRST_CLASS.md": (
        "not yet a first-class pocket release",
    ),
    "PHASE_STATUS.md": (
        "public release correctly blocked",
        "release installation correctly blocked by current policy",
        "every hardware result pending",
    ),
    "RELEASE_DECISIONS.md": (
        "owner decisions still required",
        "evidence that must be newly produced",
        "no stable public release is authorized",
    ),
}


class AssemblyError(RuntimeError):
    """A stable release precondition or assembly invariant failed."""


@dataclass(frozen=True)
class BuildPair:
    snapshots: tuple[Path, Path]
    audits: tuple[dict[str, Any], dict[str, Any]]
    audit_sha256: tuple[str, str]
    submitted_audit_sha256: tuple[str, str]
    attestations: tuple[dict[str, object], dict[str, object]]
    rbf: dict[str, object]
    build_id: dict[str, object]


@dataclass(frozen=True)
class ReleasePlan:
    output: Path
    source_commit: str
    source_date_epoch: int
    core_id: str
    version: str
    release_date: str
    package_filename: str
    source_filename: str
    signed_provenance_filename: str
    rbf: dict[str, object]
    build_id: dict[str, object]
    audit_sha256: tuple[str, str]
    hardware_run_id: str
    known_title_run_id: str
    release_body: str
    release_body_sha256: str


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def _canonical_sha256(document: object) -> str:
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AssemblyError(f"duplicate JSON field in attestation output: {key}")
        result[key] = value
    return result


def _plain_file_identity(path: Path, label: str, maximum: int) -> dict[str, object]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise AssemblyError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AssemblyError(f"{label} must be a nonsymlink regular file: {path}")
    if metadata.st_size <= 0 or metadata.st_size > maximum:
        raise AssemblyError(f"{label} has an invalid bounded size: {path}")
    return _identity(path)


def _workflow_identity(provenance: object) -> dict[str, str]:
    if not isinstance(provenance, dict):
        raise AssemblyError("Quartus candidate has no workflow provenance")
    fields = (
        "workflow_repository",
        "workflow_path",
        "workflow_sha",
        "workflow_run_id",
        "workflow_run_attempt",
        "workflow_job",
        "workflow_job_nonce",
    )
    identity = {field: provenance.get(field) for field in fields}
    if not all(isinstance(value, str) for value in identity.values()):
        raise AssemblyError("Quartus candidate workflow provenance is incomplete")
    return identity  # type: ignore[return-value]


def _verify_candidate_attestation(
    *,
    candidate: Path,
    bundle: Path,
    source_commit: str,
    workflow_identity: dict[str, str],
) -> dict[str, object]:
    """Verify one candidate using GitHub CLI's current official online trust root."""

    candidate_identity = _plain_file_identity(
        candidate, "attested Quartus candidate audit", 8 * 1024 * 1024
    )
    bundle_identity = _plain_file_identity(
        bundle, "Quartus candidate attestation bundle", 8 * 1024 * 1024
    )
    command = [
        "gh",
        "attestation",
        "verify",
        str(candidate),
        "--repo",
        ATTESTATION_REPOSITORY,
        "--signer-workflow",
        ATTESTATION_WORKFLOW,
        "--source-digest",
        source_commit,
        "--source-ref",
        ATTESTATION_SOURCE_REF,
        "--bundle",
        str(bundle),
        "--format",
        "json",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = (
            error.stderr.strip()
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        raise AssemblyError(
            "signed Quartus candidate provenance did not verify"
            + (f": {detail}" if detail else "")
        ) from error
    try:
        payload = json.loads(completed.stdout, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AssemblyError("gh returned malformed attestation verification JSON") from error
    if not isinstance(payload, list) or len(payload) != 1:
        raise AssemblyError("expected exactly one verified candidate attestation")
    result = payload[0].get("verificationResult") if isinstance(payload[0], dict) else None
    signature = result.get("signature") if isinstance(result, dict) else None
    certificate = signature.get("certificate") if isinstance(signature, dict) else None
    timestamps = result.get("verifiedTimestamps") if isinstance(result, dict) else None
    statement = result.get("statement") if isinstance(result, dict) else None
    if not isinstance(certificate, dict) or not isinstance(timestamps, list) or not timestamps:
        raise AssemblyError("verified attestation lacks certificate or timestamp evidence")
    subjects = statement.get("subject") if isinstance(statement, dict) else None
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise AssemblyError("verified attestation must bind exactly one subject")
    subject = subjects[0] if isinstance(subjects[0], dict) else None
    digest = subject.get("digest") if isinstance(subject, dict) else None
    if (
        not isinstance(digest, dict)
        or subject.get("name") != package_core.QUARTUS_AUDIT_FILENAME
        or digest != {"sha256": candidate_identity["sha256"]}
    ):
        raise AssemblyError("verified attestation subject is not the candidate audit")

    signer_uri = (
        "https://github.com/RegionallyFamous/swansong-core/"
        ".github/workflows/quartus-fit.yml@refs/heads/main"
    )
    expected_certificate = {
        "githubWorkflowTrigger": "workflow_dispatch",
        "githubWorkflowSHA": source_commit,
        "githubWorkflowRepository": ATTESTATION_REPOSITORY,
        "githubWorkflowRef": ATTESTATION_SOURCE_REF,
        "buildSignerURI": signer_uri,
        "buildSignerDigest": source_commit,
        "runnerEnvironment": "self-hosted",
        "sourceRepositoryURI": "https://github.com/RegionallyFamous/swansong-core",
        "sourceRepositoryDigest": source_commit,
        "sourceRepositoryRef": ATTESTATION_SOURCE_REF,
        "buildConfigURI": signer_uri,
        "buildConfigDigest": source_commit,
        "buildTrigger": "workflow_dispatch",
    }
    if any(certificate.get(key) != value for key, value in expected_certificate.items()):
        raise AssemblyError("verified candidate certificate origin does not match release")
    invocation = certificate.get("runInvocationURI")
    match = RUN_INVOCATION_RE.fullmatch(invocation) if isinstance(invocation, str) else None
    if match is None:
        raise AssemblyError("verified candidate certificate has no exact run invocation")
    run_id, run_attempt = match.groups()
    if (
        workflow_identity.get("workflow_repository") != ATTESTATION_REPOSITORY
        or workflow_identity.get("workflow_path") != ".github/workflows/quartus-fit.yml"
        or workflow_identity.get("workflow_sha") != source_commit
        or workflow_identity.get("workflow_job") != "fit"
        or workflow_identity.get("workflow_run_id") != run_id
        or workflow_identity.get("workflow_run_attempt") != run_attempt
    ):
        raise AssemblyError(
            "signed run invocation does not match candidate workflow metadata"
        )
    return {
        "repository": ATTESTATION_REPOSITORY,
        "workflow_path": ".github/workflows/quartus-fit.yml",
        "source_ref": ATTESTATION_SOURCE_REF,
        "source_commit": source_commit,
        "run_id": int(run_id),
        "run_attempt": int(run_attempt),
        "job": workflow_identity["workflow_job"],
        "job_nonce": workflow_identity["workflow_job_nonce"],
        "runner_environment": certificate["runnerEnvironment"],
        "candidate_audit": candidate_identity,
        "attestation_bundle": bundle_identity,
    }


def _git(source_root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = (
            error.stderr.decode("utf-8", errors="replace").strip()
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        raise AssemblyError(
            "cannot inspect the exact release checkout" + (f": {detail}" if detail else "")
        ) from error
    return result.stdout


def _exact_checked_in_path(path: Path, expected: Path, label: str) -> Path:
    if path.absolute().resolve() != expected.resolve():
        raise AssemblyError(f"{label} must be the exact checked-in {expected}")
    return expected.resolve()


def _validate_output(output: Path, *, source_root: Path) -> Path:
    output = output.absolute()
    if output.name in {"", ".", ".."}:
        raise AssemblyError("--output-dir must name a new directory")
    parent = output.parent
    try:
        metadata = parent.lstat()
    except FileNotFoundError as error:
        raise AssemblyError(f"output parent does not exist: {parent}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise AssemblyError(f"output parent must be a nonsymlink directory: {parent}")
    resolved_parent = parent.resolve()
    output = resolved_parent / output.name
    resolved_source = source_root.resolve()
    try:
        output.relative_to(resolved_source)
    except ValueError:
        pass
    else:
        raise AssemblyError(
            "stable release output must be outside the exact source checkout"
        )
    if output.exists() or output.is_symlink():
        raise AssemblyError(f"output directory already exists: {output}")
    return output


def _validate_checkout(source_root: Path, source_commit: str) -> None:
    if COMMIT_RE.fullmatch(source_commit) is None:
        raise AssemblyError("--source-commit must be a full lowercase 40-hex commit")
    repository = Path(
        _git(source_root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve()
    if repository != source_root.resolve():
        raise AssemblyError("assembler must run from the exact repository root")
    head = _git(source_root, "rev-parse", "HEAD").decode("ascii").strip()
    if head != source_commit:
        raise AssemblyError("--source-commit does not match checkout HEAD")
    status = _git(
        source_root, "status", "--porcelain=v1", "--untracked-files=all"
    )
    if status:
        first = status.decode("utf-8", errors="replace").splitlines()[0]
        raise AssemblyError(
            "stable release assembly requires a clean exact checkout; "
            f"first dirty path: {first}"
        )


def _release_document_text(source_root: Path, relative: str) -> str:
    path = source_root / relative
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise AssemblyError(f"release documentation is missing: {relative}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AssemblyError(
            f"release documentation must be a nonsymlink regular file: {relative}"
        )
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise AssemblyError(f"cannot read release documentation: {relative}") from error


def _validate_release_documentation(source_root: Path) -> None:
    """Require owner decisions and public-facing release truth to agree."""

    documents = {
        relative: _release_document_text(source_root, relative)
        for relative in RELEASE_DOCUMENT_STALE_MARKERS
    }
    decisions: dict[str, bool] = {}
    unexpected_entries: list[str] = []
    for match in re.finditer(
        r"^- \[([ xX])\] (.*?)(?=^- \[[ xX]\] |\Z)",
        documents["RELEASE_DECISIONS.md"],
        flags=re.MULTILINE | re.DOTALL,
    ):
        entry = " ".join(
            match.group(2).replace("**", "").replace("`", "").split()
        )
        matching_labels = [
            label
            for label in RELEASE_DECISION_LABELS
            if entry.startswith(label)
        ]
        if len(matching_labels) != 1:
            unexpected_entries.append(entry[:80])
            continue
        label = matching_labels[0]
        if label in decisions:
            raise AssemblyError(f"release decision is duplicated: {label}")
        decisions[label] = match.group(1).lower() == "x"

    required = set(RELEASE_DECISION_LABELS)
    actual = set(decisions)
    if actual != required:
        missing = sorted(required - actual)
        unexpected = sorted(actual - required)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unexpected or unexpected_entries:
            detail.append(
                "unexpected " + ", ".join(sorted(unexpected) + unexpected_entries)
            )
        raise AssemblyError(
            "release decision checklist does not match the audited checklist: "
            + "; ".join(detail)
        )
    unchecked = sorted(label for label, accepted in decisions.items() if not accepted)
    if unchecked:
        raise AssemblyError(
            "release decision checklist is incomplete: " + ", ".join(unchecked)
        )

    for relative, markers in RELEASE_DOCUMENT_STALE_MARKERS.items():
        normalized = " ".join(documents[relative].casefold().split())
        for marker in markers:
            if marker in normalized:
                raise AssemblyError(
                    f"release documentation still claims a blocked release: {relative}"
                )


def _release_preflight(
    *,
    source_root: Path,
    dist: Path,
    release_policy: Path,
    source_commit: str,
    source_date_epoch: int,
    expected_version: str,
    expected_release_date: str,
    compressed_bitstream_reviewed: bool,
) -> tuple[ValidatedDistribution, dict[str, object], dict[str, object]]:
    if (
        isinstance(source_date_epoch, bool)
        or not isinstance(source_date_epoch, int)
        or source_date_epoch < 0
    ):
        raise AssemblyError("--source-date-epoch must be a nonnegative integer")
    if not compressed_bitstream_reviewed:
        raise AssemblyError(
            "stable release assembly requires --compressed-bitstream-reviewed"
        )
    _validate_checkout(source_root, source_commit)
    dist = _exact_checked_in_path(dist, source_root / "dist", "--dist")
    release_policy = _exact_checked_in_path(
        release_policy, source_root / "release-policy.json", "--release-policy"
    )
    _validate_release_documentation(source_root)
    definition = validate_distribution(dist)
    if definition.version != expected_version:
        raise AssemblyError(
            "--expected-version does not match checked-in core release metadata"
        )
    if definition.release_date != expected_release_date:
        raise AssemblyError(
            "--expected-release-date does not match checked-in core release metadata"
        )
    try:
        policy = package_core.validate_release_policy(release_policy, definition)
        licensing = validate_license_manifest(
            dist, source_root=source_root, require_release_ready=True
        )
    except (ValueError, OSError) as error:
        raise AssemblyError(f"release authorization is not accepted: {error}") from error
    return definition, policy, licensing


def _audit_snapshot(
    *,
    artifacts: Path,
    destination: Path,
    source_commit: str,
    source_date_epoch: int,
) -> tuple[dict[str, Any], str, str, dict[str, object]]:
    destination.mkdir(mode=0o700)
    try:
        collected = quartus_evidence.collect_evidence(
            artifacts.absolute(), destination, profile=quartus_evidence.CANDIDATE_PROFILE
        )
        required = {item.relative for item in quartus_evidence.CANDIDATE_EVIDENCE_FILES}
        if set(collected) != required:
            raise AssemblyError("Quartus candidate bundle is incomplete")
        document = quartus_fit_audit.audit(destination)
    except (quartus_evidence.EvidenceError, quartus_fit_audit.AuditError, OSError) as error:
        raise AssemblyError(f"Quartus candidate audit failed: {error}") from error
    audit = document.get("quartus_audit")
    if not isinstance(audit, dict):
        raise AssemblyError("Quartus candidate audit has no audit object")
    gates = audit.get("candidate_gates")
    if not isinstance(gates, dict):
        raise AssemblyError("Quartus candidate audit has no candidate gates")
    failed = sorted(
        gate
        for gate in package_core.AUDIT_REQUIRED_TRUE_GATES
        if gates.get(gate) is not True
    )
    if audit.get("audit_pass") is not True or failed:
        raise AssemblyError(
            "Quartus candidate gates are not accepted: "
            + ", ".join(failed or ["audit_pass"])
        )
    if gates.get("compressed_bitstream") is not None:
        raise AssemblyError("candidate audit must leave compressed_bitstream unclaimed")
    if any(gates.get(name) is not False for name in ("pocket_hardware", "dock_hardware")):
        raise AssemblyError("candidate audit must not claim Pocket or Dock hardware")
    expected_source_provenance = {
        "source_commit": source_commit,
        "source_date_epoch": str(source_date_epoch),
        "platform": "linux/amd64",
        "quartus": "21.1.1.850 Lite",
        "device": "5CEBA4F23C8",
    }
    provenance = audit.get("provenance")
    if not isinstance(provenance, dict) or any(
        provenance.get(key) != value
        for key, value in expected_source_provenance.items()
    ):
        raise AssemblyError("Quartus candidate source identity does not match release")
    workflow_identity = _workflow_identity(provenance)
    attestation = _verify_candidate_attestation(
        candidate=destination / package_core.QUARTUS_AUDIT_FILENAME,
        bundle=destination / ATTESTATION_FILENAME,
        source_commit=source_commit,
        workflow_identity=workflow_identity,
    )
    return (
        audit,
        _canonical_sha256(document),
        _sha256(destination / package_core.QUARTUS_AUDIT_FILENAME),
        attestation,
    )


def snapshot_and_audit_pair(
    *,
    artifacts_a: Path,
    artifacts_b: Path,
    scratch: Path,
    source_commit: str,
    source_date_epoch: int,
) -> BuildPair:
    try:
        if artifacts_a.resolve(strict=True) == artifacts_b.resolve(strict=True):
            raise AssemblyError(
                "--artifacts-a and --artifacts-b must be distinct bundles"
            )
    except OSError as error:
        raise AssemblyError(f"cannot resolve Quartus artifact bundles: {error}") from error
    snapshots = (scratch / "quartus-a", scratch / "quartus-b")
    first = _audit_snapshot(
        artifacts=artifacts_a,
        destination=snapshots[0],
        source_commit=source_commit,
        source_date_epoch=source_date_epoch,
    )
    second = _audit_snapshot(
        artifacts=artifacts_b,
        destination=snapshots[1],
        source_commit=source_commit,
        source_date_epoch=source_date_epoch,
    )
    if first[3]["run_id"] == second[3]["run_id"]:
        raise AssemblyError(
            "Quartus candidates must have distinct signed workflow run IDs"
        )
    if first[3]["job_nonce"] == second[3]["job_nonce"]:
        raise AssemblyError(
            "Quartus candidates must have distinct workflow job nonces"
        )
    rbf = tuple(
        _identity(path / "output_files/ap_core.rbf", filename="ap_core.rbf")
        for path in snapshots
    )
    build_id = tuple(_identity(path / "build_id.mif") for path in snapshots)
    if rbf[0] != rbf[1]:
        raise AssemblyError("reproduced Quartus RBF outputs are not byte-identical")
    if build_id[0] != build_id[1]:
        raise AssemblyError("reproduced Quartus build IDs are not byte-identical")
    return BuildPair(
        snapshots=snapshots,
        audits=(first[0], second[0]),
        audit_sha256=(first[1], second[1]),
        submitted_audit_sha256=(first[2], second[2]),
        attestations=(first[3], second[3]),
        rbf=rbf[0],
        build_id=build_id[0],
    )


def signed_build_origins(
    pair: BuildPair, *, source_commit: str, source_date_epoch: int
) -> dict[str, object]:
    """Materialize the exact downstream record for two verified signed builds."""

    builds: list[dict[str, object]] = []
    for index, label in enumerate(("a", "b")):
        origin = dict(pair.attestations[index])
        origin["candidate_audit"] = {
            **origin["candidate_audit"],  # type: ignore[arg-type]
            "filename": (
                f"signed-builds/{label}/{package_core.QUARTUS_AUDIT_FILENAME}"
            ),
        }
        origin["attestation_bundle"] = {
            **origin["attestation_bundle"],  # type: ignore[arg-type]
            "filename": f"signed-builds/{label}/{ATTESTATION_FILENAME}",
        }
        builds.append(
            {
                "label": label,
                **origin,
                "recomputed_audit_sha256": pair.audit_sha256[index],
                "submitted_audit_sha256": pair.submitted_audit_sha256[index],
            }
        )
    return {
        "magic": "SWAN_SONG_SIGNED_BUILD_PAIR_V1",
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "rbf": pair.rbf,
        "build_id": pair.build_id,
        "builds": builds,
    }


def _accepted_hardware(
    *, manifest: Path, inventory: Path, expected_rbf: dict[str, object]
) -> dict[str, Any]:
    try:
        summary = verify_hardware_qa_manifest(
            manifest.absolute(), inventory.absolute(), require_pass=True
        )
    except (ValueError, OSError) as error:
        raise AssemblyError(f"hardware QA is not accepted: {error}") from error
    core = summary.get("core")
    if not isinstance(core, dict) or core.get("raw_rbf") != expected_rbf:
        raise AssemblyError(
            "accepted hardware QA raw RBF does not match both Quartus builds"
        )
    return summary


def _accepted_known_title_compatibility(
    *, manifest: Path, expected_rbf: dict[str, object], source_commit: str
) -> dict[str, Any]:
    try:
        summary = verify_known_title_manifest(
            KNOWN_TITLE_CATALOGUE, manifest.absolute(), require_pass=True
        )
    except (ValueError, OSError) as error:
        raise AssemblyError(
            f"known-title compatibility is not accepted: {error}"
        ) from error
    run = summary.get("run")
    if not isinstance(run, dict):
        raise AssemblyError("known-title compatibility has no verified run identity")
    if run.get("core_commit") != source_commit:
        raise AssemblyError(
            "known-title compatibility source commit does not match release"
        )
    if run.get("raw_rbf_sha256") != expected_rbf.get("sha256"):
        raise AssemblyError(
            "known-title compatibility raw RBF does not match both Quartus builds"
        )
    return summary


def _source_archive_bytes(
    *, source_root: Path, source_commit: str, prefix: str
) -> bytes:
    tree = _git(source_root, "ls-tree", "-r", "-z", source_commit)
    file_count = 0
    for raw in tree.split(b"\0"):
        if not raw:
            continue
        try:
            header, _ = raw.split(b"\t", 1)
            mode, kind, _object_id = header.decode("ascii").split(" ")
        except (UnicodeError, ValueError) as error:
            raise AssemblyError("source tree inventory is malformed") from error
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise AssemblyError(
                "corresponding-source archive refuses symlinks, submodules, or special entries"
            )
        file_count += 1
    if file_count == 0:
        raise AssemblyError("source commit has no tracked files")
    payload = _git(
        source_root,
        "archive",
        "--format=tar",
        f"--prefix={prefix}/",
        source_commit,
    )
    if not payload or len(payload) > MAX_SOURCE_ARCHIVE_BYTES:
        raise AssemblyError("corresponding-source archive is empty or too large")
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            members = archive.getmembers()
    except tarfile.TarError as error:
        raise AssemblyError(f"generated corresponding-source tar is invalid: {error}") from error
    names = [member.name for member in members if member.isfile()]
    if len(names) != file_count or names != sorted(names):
        raise AssemblyError("corresponding-source archive inventory is not exact and sorted")
    required = {
        f"{prefix}/src/fpga/apf/apf_top.v",
        f"{prefix}/scripts/package_core.py",
        f"{prefix}/dist/Cores/RegionallyFamous.SwanSong/core.json",
    }
    if not required.issubset(names):
        raise AssemblyError("corresponding-source archive is missing required build sources")
    if any(
        member.issym()
        or member.islnk()
        or member.isdev()
        or member.isfifo()
        or PurePosixPath(member.name).is_absolute()
        or ".." in PurePosixPath(member.name).parts
        for member in members
    ):
        raise AssemblyError("corresponding-source archive contains an unsafe member")
    return payload


def _signed_provenance_archive_bytes(
    pair: BuildPair, *, source_date_epoch: int
) -> bytes:
    """Create the public-safe deterministic archive for both signed audits."""

    members: list[tuple[str, bytes]] = []
    for index, label in enumerate(("a", "b")):
        origin = pair.attestations[index]
        for filename, identity_key in (
            (package_core.QUARTUS_AUDIT_FILENAME, "candidate_audit"),
            (ATTESTATION_FILENAME, "attestation_bundle"),
        ):
            source = pair.snapshots[index] / filename
            payload = _read_bounded_plain_file(
                source,
                f"signed build {label} public provenance",
                8 * 1024 * 1024,
            )
            identity = origin.get(identity_key)
            if not isinstance(identity, dict) or identity != {
                "filename": filename,
                "size": len(payload),
                "sha256": _sha256_bytes(payload),
            }:
                raise AssemblyError(
                    f"signed build {label} {identity_key} changed after verification"
                )
            members.append((f"signed-builds/{label}/{filename}", payload))
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in sorted(members):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = source_date_epoch
            archive.addfile(info, io.BytesIO(payload))
    return stream.getvalue()


def _read_bounded_plain_file(
    path: Path, label: str, maximum: int
) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise AssemblyError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AssemblyError(f"{label} must be a nonsymlink regular file: {path}")
    if metadata.st_size <= 0 or metadata.st_size > maximum:
        raise AssemblyError(f"{label} has an invalid bounded size: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise AssemblyError(f"{label} changed while opening: {path}")
        payload = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            payload += chunk
            if len(payload) > maximum:
                raise AssemblyError(f"{label} grew beyond {maximum} bytes: {path}")
        if len(payload) != metadata.st_size:
            raise AssemblyError(f"{label} changed while reading: {path}")
        return payload
    finally:
        os.close(descriptor)


def _write_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(descriptor)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)


def _write_json(path: Path, document: object) -> None:
    _write_file(
        path,
        (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        ),
    )


def _rename_noreplace(parent: Path, source_name: str, destination_name: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        source = os.fsencode(source_name)
        destination = os.fsencode(destination_name)
        function = None
        flags = 0
        if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            function = libc.renameatx_np
            flags = 0x00000004  # RENAME_EXCL
        elif hasattr(libc, "renameat2"):
            function = libc.renameat2
            flags = 1  # RENAME_NOREPLACE
        if function is None:
            raise AssemblyError(
                "platform lacks atomic no-clobber directory publication"
            )
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        if function(descriptor, source, descriptor, destination, flags) != 0:
            number = ctypes.get_errno()
            unavailable = {
                errno.ENOSYS,
                errno.EINVAL,
                getattr(errno, "ENOTSUP", errno.EINVAL),
                getattr(errno, "EOPNOTSUPP", errno.EINVAL),
            }
            if number in unavailable:
                raise AssemblyError(
                    "filesystem lacks atomic no-clobber directory publication"
                )
            raise OSError(number, os.strerror(number), str(parent / destination_name))
        # Publication has already succeeded atomically. Some filesystems do
        # not support directory fsync; no post-rename error may relabel the
        # complete published tree as a failed/partial operation.
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)


def _render_release_body(
    *,
    version: str,
    release_date: str,
    package_filename: str,
    source_filename: str,
    signed_provenance_filename: str,
    source_commit: str,
    hardware_run_id: str,
) -> str:
    """Render the exact, end-user-facing GitHub release notes."""

    return f"""# Swan Song {version}

Swan Song is a WonderSwan and WonderSwan Color openFPGA core for Analogue
Pocket, by Regionally Famous. This verified release was published on
{release_date}.

## Install or update

1. Back up the complete Pocket SD card.
2. Download `{package_filename}` and verify it with the attached `SHA256SUMS`.
3. Merge the ZIP's `Assets`, `Cores`, and `Platforms` folders into the matching
   folders at the root of the SD card. Do not replace the entire top-level
   folders on macOS.
4. Add your legally obtained `.ws` and `.wsc` games. Swan Song uses its
   built-in Open IPL, so no external BIOS file is required.
5. Start Swan Song from **openFPGA**.

Read the [installation, update, rollback, and uninstall guide](https://github.com/RegionallyFamous/swansong-core/wiki/Install-Swan-Song)
before changing an existing installation. `core.json` declares the minimum
Pocket firmware that may load the core; use the evidence-backed Analogue OS
support version stated in that guide for this release.

Swan Song can remain installed beside `agg23.WonderSwan`. Its cartridge saves,
console data, settings, and presets use the independent
`RegionallyFamous.SwanSong` namespace. Back up before migrating older data.

## Rollback safety

The safest rollback is to restore the complete SD-card backup made before the
update. Replacing only the core files does not roll back saves or settings.

## Verified release records

- Source commit: `{source_commit}`
- Accepted physical hardware-QA run: `{hardware_run_id}`
- Corresponding source: `{source_filename}`
- Signed Quartus provenance: `{signed_provenance_filename}`
- Verification procedure: [extract the signed provenance archive and verify both workflow attestations](https://github.com/RegionallyFamous/swansong-core/blob/main/BUILDING.md#signed-stable-release-assembly)
- Machine-readable evidence summary: `release-manifest.json`
- Checksums for the package and public release records: `SHA256SUMS`

The package was assembled only after two distinct signed Quartus workflow
executions produced byte-identical FPGA outputs and the exact package passed
the required Pocket and Dock hardware protocol. The signed records establish
distinct workflow executions, not distinct physical build hosts. Games, saves,
device identity, and private test captures are not included in these public
downloads; the built-in Open IPL is part of the core package.
"""


def _render_summary(plan: ReleasePlan, *, applied: bool) -> str:
    mode = "ASSEMBLED" if applied else "VALIDATED PLAN — no durable files written"
    summary = "\n".join(
        (
            mode,
            f"Output: {plan.output}",
            f"Release: {plan.core_id} {plan.version} ({plan.release_date})",
            f"Source: {plan.source_commit} @ {plan.source_date_epoch}",
            f"Reproduced RBF: {plan.rbf['sha256']}",
            f"Reproduced build ID: {plan.build_id['sha256']}",
            f"Accepted hardware QA run: {plan.hardware_run_id}",
            f"Accepted known-title run: {plan.known_title_run_id}",
            f"Release body SHA-256: {plan.release_body_sha256}",
            f"Public files: {plan.package_filename}, {plan.package_filename}.provenance.json, "
            f"{plan.source_filename}, {plan.signed_provenance_filename}, "
            f"{RELEASE_BODY_FILENAME}, release-manifest.json, "
            "SHA256SUMS",
        )
    )
    if not applied:
        summary += (
            "\n\nReview the exact generated release-body.md below, then pass its "
            "SHA-256 with --release-body-reviewed-sha256 when using --apply.\n\n"
            "---\n\n"
            + plan.release_body
        )
    return summary


def assemble_release(
    *,
    artifacts_a: Path,
    artifacts_b: Path,
    hardware_manifest: Path,
    hardware_inventory: Path,
    known_title_manifest: Path,
    output: Path,
    source_commit: str,
    source_date_epoch: int,
    expected_version: str,
    expected_release_date: str,
    compressed_bitstream_reviewed: bool,
    release_body_reviewed_sha256: str | None,
    apply: bool,
    source_root: Path = ROOT,
    dist: Path = DIST,
    release_policy: Path = RELEASE_POLICY,
) -> ReleasePlan:
    source_root = source_root.resolve()
    output = _validate_output(output, source_root=source_root)
    definition, policy, licensing = _release_preflight(
        source_root=source_root,
        dist=dist,
        release_policy=release_policy,
        source_commit=source_commit,
        source_date_epoch=source_date_epoch,
        expected_version=expected_version,
        expected_release_date=expected_release_date,
        compressed_bitstream_reviewed=compressed_bitstream_reviewed,
    )
    workspace_parent = output.parent if apply else Path(tempfile.gettempdir())
    workspace = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.assemble-", dir=workspace_parent)
    )
    published = False
    try:
        private = workspace / ".private"
        private.mkdir(mode=0o700)
        pair = snapshot_and_audit_pair(
            artifacts_a=artifacts_a,
            artifacts_b=artifacts_b,
            scratch=private,
            source_commit=source_commit,
            source_date_epoch=source_date_epoch,
        )
        signed_origins = signed_build_origins(
            pair,
            source_commit=source_commit,
            source_date_epoch=source_date_epoch,
        )
        hardware = _accepted_hardware(
            manifest=hardware_manifest,
            inventory=hardware_inventory,
            expected_rbf=pair.rbf,
        )
        known_title = _accepted_known_title_compatibility(
            manifest=known_title_manifest,
            expected_rbf=pair.rbf,
            source_commit=source_commit,
        )
        known_title_run = known_title.get("run")
        if not isinstance(known_title_run, dict):
            raise AssemblyError("known-title compatibility run identity disappeared")
        source_filename = definition.recommended_archive_name.removesuffix(".zip") + "-source.tar"
        release_body = _render_release_body(
            version=definition.version,
            release_date=definition.release_date,
            package_filename=definition.recommended_archive_name,
            source_filename=source_filename,
            signed_provenance_filename=SIGNED_PROVENANCE_FILENAME,
            source_commit=source_commit,
            hardware_run_id=str(hardware.get("run_id", "")),
        )
        plan = ReleasePlan(
            output=output,
            source_commit=source_commit,
            source_date_epoch=source_date_epoch,
            core_id=definition.core_id,
            version=definition.version,
            release_date=definition.release_date,
            package_filename=definition.recommended_archive_name,
            source_filename=source_filename,
            signed_provenance_filename=SIGNED_PROVENANCE_FILENAME,
            rbf=pair.rbf,
            build_id=pair.build_id,
            audit_sha256=pair.audit_sha256,
            hardware_run_id=str(hardware.get("run_id", "")),
            known_title_run_id=str(known_title_run.get("run_id", "")),
            release_body=release_body,
            release_body_sha256=_sha256_bytes(release_body.encode("utf-8")),
        )
        if not apply:
            return plan
        if (
            release_body_reviewed_sha256 is None
            or SHA256_RE.fullmatch(release_body_reviewed_sha256) is None
            or release_body_reviewed_sha256 != plan.release_body_sha256
        ):
            raise AssemblyError(
                "--apply requires --release-body-reviewed-sha256 to equal the "
                f"validated plan value {plan.release_body_sha256}"
            )

        evidence = build_release_evidence.build_release_evidence(
            artifacts=pair.snapshots[0],
            signed_artifacts=pair.snapshots,
            signed_build_origins=signed_origins,
            hardware_manifest=hardware_manifest,
            hardware_inventory=hardware_inventory,
            known_title_manifest=known_title_manifest,
            output=private / "release-evidence" / build_release_evidence.RELEASE_EVIDENCE_FILENAME,
            source_commit=source_commit,
            source_date_epoch=source_date_epoch,
            compressed_bitstream_reviewed=True,
        )
        evidence_rbf = evidence.parent / "output_files/ap_core.rbf"
        validated_evidence = package_core.validate_build_evidence(
            evidence, evidence_rbf.read_bytes(), evidence_rbf.name
        )
        bound_hardware = validated_evidence.get("hardware_qa")
        if not isinstance(bound_hardware, dict):
            raise AssemblyError("Release Evidence V2 has no verified hardware binding")
        if {
            "magic": bound_hardware.get("magic"),
            "run_id": bound_hardware.get("run_id"),
            "manifest_sha256": (
                bound_hardware.get("manifest", {}).get("sha256")
                if isinstance(bound_hardware.get("manifest"), dict)
                else None
            ),
            "inventory_sha256": (
                bound_hardware.get("inventory", {}).get("sha256")
                if isinstance(bound_hardware.get("inventory"), dict)
                else None
            ),
        } != {
            "magic": hardware.get("magic"),
            "run_id": hardware.get("run_id"),
            "manifest_sha256": hardware.get("manifest_sha256"),
            "inventory_sha256": hardware.get("inventory_sha256"),
        }:
            raise AssemblyError("hardware QA inputs changed during release assembly")
        bound_known_title = validated_evidence.get("known_title_compatibility")
        if not isinstance(bound_known_title, dict):
            raise AssemblyError(
                "Release Evidence V2 has no verified known-title compatibility binding"
            )
        if {
            "magic": bound_known_title.get("magic"),
            "run_id": bound_known_title.get("run_id"),
            "catalogue_sha256": (
                bound_known_title.get("catalogue", {}).get("sha256")
                if isinstance(bound_known_title.get("catalogue"), dict)
                else None
            ),
            "manifest_sha256": (
                bound_known_title.get("manifest", {}).get("sha256")
                if isinstance(bound_known_title.get("manifest"), dict)
                else None
            ),
        } != {
            "magic": known_title.get("magic"),
            "run_id": known_title_run.get("run_id"),
            "catalogue_sha256": known_title.get("catalogue_sha256"),
            "manifest_sha256": known_title.get("manifest_sha256"),
        }:
            raise AssemblyError(
                "known-title compatibility inputs changed during release assembly"
            )
        package = workspace / definition.recommended_archive_name
        package_core.create_package(
            dist=dist,
            rbf=evidence_rbf,
            output=package,
            chip32_assembly=source_root / "src/support/chip32.asm",
            chip32_encoded_image=source_root / "src/support/chip32.bin.hex",
            build_evidence=evidence,
            release_policy=release_policy,
            release=True,
        )
        provenance = package.with_name(package.name + ".provenance.json")
        package_digest = _sha256(package)
        provenance_digest = _sha256(provenance)
        stage = private / "release-stage"
        stage.mkdir()
        stage_plan = stage_pocket_sd.plan_staging(
            staging_dir=stage,
            package=package,
            provenance=provenance,
            verify_release=True,
            expected_package_sha256=package_digest,
            expected_provenance_sha256=provenance_digest,
            expected_version=definition.version,
            expected_source_commit=source_commit,
        )
        stage_pocket_sd.apply_staging(stage_plan)
        verified_again = stage_pocket_sd.plan_staging(
            staging_dir=stage,
            package=package,
            provenance=provenance,
            verify_release=True,
            expected_package_sha256=package_digest,
            expected_provenance_sha256=provenance_digest,
            expected_version=definition.version,
            expected_source_commit=source_commit,
        )
        if verified_again.new_files or verified_again.replaced_files:
            raise AssemblyError("release staging did not reproduce the verified package tree")

        source_path = workspace / source_filename
        source_prefix = source_filename.removesuffix(".tar")
        _write_file(
            source_path,
            _source_archive_bytes(
                source_root=source_root,
                source_commit=source_commit,
                prefix=source_prefix,
            ),
        )
        signed_provenance_path = workspace / SIGNED_PROVENANCE_FILENAME
        _write_file(
            signed_provenance_path,
            _signed_provenance_archive_bytes(
                pair, source_date_epoch=source_date_epoch
            ),
        )
        release_body_path = workspace / RELEASE_BODY_FILENAME
        _write_file(release_body_path, release_body.encode("utf-8"))
        release_evidence_identity = _identity(evidence)
        artifact_records = {
            package.name: _identity(package),
            provenance.name: _identity(provenance),
            source_path.name: _identity(source_path),
            signed_provenance_path.name: _identity(signed_provenance_path),
            release_body_path.name: _identity(release_body_path),
        }
        manifest = {
            "release_manifest": {
                "magic": MAGIC,
                "core_id": definition.core_id,
                "repository_url": definition.repository_url,
                "version": definition.version,
                "date_release": definition.release_date,
                "source_commit": source_commit,
                "source_date_epoch": source_date_epoch,
                "artifacts": artifact_records,
                "release_policy": policy,
                "license_manifest": licensing,
                "reproducible_builds": [
                    {
                        "label": "a",
                        "recomputed_audit_sha256": pair.audit_sha256[0],
                        "submitted_audit_sha256": pair.submitted_audit_sha256[0],
                    },
                    {
                        "label": "b",
                        "recomputed_audit_sha256": pair.audit_sha256[1],
                        "submitted_audit_sha256": pair.submitted_audit_sha256[1],
                    },
                ],
                "signed_build_origins": signed_origins,
                "rbf": pair.rbf,
                "build_id": pair.build_id,
                "hardware_qa": {
                    "magic": bound_hardware.get("magic"),
                    "run_id": bound_hardware.get("run_id"),
                    "manifest_sha256": bound_hardware["manifest"]["sha256"],
                    "inventory_sha256": bound_hardware["inventory"]["sha256"],
                },
                "known_title_compatibility": {
                    "magic": bound_known_title.get("magic"),
                    "run_id": bound_known_title.get("run_id"),
                    "catalogue_sha256": bound_known_title["catalogue"]["sha256"],
                    "manifest_sha256": bound_known_title["manifest"]["sha256"],
                    "case_count": bound_known_title.get("case_count"),
                    "mode_pass_count": bound_known_title.get("mode_pass_count"),
                    "artifact_count": bound_known_title.get("artifact_count"),
                    "artifact_index_sha256": bound_known_title.get(
                        "artifact_index_sha256"
                    ),
                },
                "private_release_evidence": {
                    **release_evidence_identity,
                    "published": False,
                },
                "verification": {
                    "both_quartus_audits_pass": True,
                    "distinct_signed_quartus_runs": True,
                    "rbf_and_build_id_reproduced": True,
                    "hardware_qa_accepted": True,
                    "known_title_compatibility_accepted": True,
                    "release_evidence_v2_validated": True,
                    "release_package_validated": True,
                    "release_stage_applied_and_reverified": True,
                    "corresponding_source_archived": True,
                },
            }
        }
        manifest_path = workspace / "release-manifest.json"
        _write_json(manifest_path, manifest)
        checksum_paths = [
            package,
            provenance,
            source_path,
            signed_provenance_path,
            release_body_path,
            manifest_path,
        ]
        checksum_payload = "".join(
            f"{_sha256(path)}  {path.name}\n"
            for path in sorted(checksum_paths, key=lambda item: item.name)
        ).encode("ascii")
        _write_file(workspace / "SHA256SUMS", checksum_payload)

        shutil.rmtree(private)
        expected_names = {
            package.name,
            provenance.name,
            source_path.name,
            signed_provenance_path.name,
            release_body_path.name,
            manifest_path.name,
            "SHA256SUMS",
        }
        observed = {path.name for path in workspace.iterdir()}
        if observed != expected_names:
            raise AssemblyError(
                f"public release inventory is not exact: {sorted(observed)!r}"
            )
        for path in workspace.iterdir():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise AssemblyError(f"public release member is not a plain file: {path}")
            os.chmod(path, 0o644)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.chmod(workspace, 0o755)
        _rename_noreplace(output.parent, workspace.name, output.name)
        published = True
        return plan
    except (
        AssemblyError,
        build_release_evidence.ReleaseEvidenceError,
        quartus_fit_audit.AuditError,
        ValueError,
        OSError,
    ) as error:
        if isinstance(error, AssemblyError):
            raise
        raise AssemblyError(str(error)) from error
    finally:
        if not published:
            shutil.rmtree(workspace, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-a", required=True, type=Path)
    parser.add_argument("--artifacts-b", required=True, type=Path)
    parser.add_argument("--hardware-manifest", required=True, type=Path)
    parser.add_argument("--hardware-inventory", required=True, type=Path)
    parser.add_argument("--known-title-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-date-epoch", required=True, type=int)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-release-date", required=True)
    parser.add_argument(
        "--compressed-bitstream-reviewed",
        action="store_true",
        help="record explicit human acceptance of the exact compressed RBF configuration",
    )
    parser.add_argument(
        "--release-body-reviewed-sha256",
        help=(
            "with --apply, must equal the release-body SHA-256 printed by the "
            "validated plan"
        ),
    )
    parser.add_argument(
        "--release-policy", default=RELEASE_POLICY, type=Path,
        help="must be the exact checked-in release-policy.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create and atomically publish the release directory; default is plan only",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        plan = assemble_release(
            artifacts_a=arguments.artifacts_a,
            artifacts_b=arguments.artifacts_b,
            hardware_manifest=arguments.hardware_manifest,
            hardware_inventory=arguments.hardware_inventory,
            known_title_manifest=arguments.known_title_manifest,
            output=arguments.output_dir,
            source_commit=arguments.source_commit,
            source_date_epoch=arguments.source_date_epoch,
            expected_version=arguments.expected_version,
            expected_release_date=arguments.expected_release_date,
            compressed_bitstream_reviewed=arguments.compressed_bitstream_reviewed,
            release_body_reviewed_sha256=arguments.release_body_reviewed_sha256,
            apply=arguments.apply,
            release_policy=arguments.release_policy,
        )
    except (AssemblyError, ValueError, OSError) as error:
        print(f"assemble_stable_release.py: {error}", file=sys.stderr)
        return 1
    print(_render_summary(plan, applied=arguments.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
