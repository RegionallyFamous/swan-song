#!/usr/bin/env python3
"""Create a deterministic APF package from dist/ and a compiled Quartus RBF."""

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile

from quartus_report_text import decode_quartus_report
import quartus_fit_audit as fit_audit

from build_chip32 import chip32_image, chip32_image_bytes
from license_manifest import validate_license_manifest
from known_title_compatibility import (
    MAGIC as KNOWN_TITLE_COMPATIBILITY_MAGIC,
    REQUIRED_COMMERCIAL_IDS as KNOWN_TITLE_COMMERCIAL_IDS,
    REQUIRED_OPEN_IDS as KNOWN_TITLE_OPEN_IDS,
    verify_manifest as verify_known_title_compatibility_manifest,
)
from pocket_hardware_qa import (
    CASE_SPECS as HARDWARE_QA_CASE_SPECS,
    MANIFEST_MAGIC as HARDWARE_QA_MANIFEST_MAGIC,
    PERSISTENT_SETTING_NAMES as HARDWARE_QA_PERSISTENT_SETTING_NAMES,
    installed_payload_names as hardware_qa_installed_payload_names,
    verify_manifest as verify_hardware_qa_manifest,
)
from package_validator import (
    StrictJsonError,
    ValidatedDistribution,
    strict_json_loads,
    validate_distribution,
)
from reverse_rbf import REVERSE


SEMVER_PATTERN = re.compile(
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
RELEASE_QUARTUS_VERSION = "21.1.1 Build 850"
QUARTUS_REPORT_VERSION_PATTERN = re.compile(
    r"^(?:Version )?21[.]1[.]1 Build 850"
    r"(?: [0-9]{2}/[0-9]{2}/[0-9]{4} [A-Za-z0-9]+ Lite Edition)?$"
)
MIF_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*([0-9A-Fa-f]+)\s*:\s*([0-9A-Fa-f]+)\s*;\s*(?:--.*)?$"
)
RELEASE_EVIDENCE_V1 = "SWAN_SONG_RELEASE_EVIDENCE_V1"
RELEASE_EVIDENCE_V2 = "SWAN_SONG_RELEASE_EVIDENCE_V2"
SIGNED_BUILD_PAIR_V1 = "SWAN_SONG_SIGNED_BUILD_PAIR_V1"
RELEASE_SOURCE_INPUTS_V1 = "SWAN_SONG_RELEASE_SOURCE_INPUTS_V1"
SOURCE_ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPECTED_REPOSITORY = "https://github.com/RegionallyFamous/swan-song"
QUARTUS_AUDIT_FILENAME = "quartus-audit-candidate.json"
ATTESTATION_FILENAME = "quartus-audit-candidate.attestation.json"
ATTESTATION_REPOSITORY = "RegionallyFamous/swan-song"
ATTESTATION_WORKFLOW = (
    "github.com/RegionallyFamous/swan-song/.github/workflows/quartus-fit.yml"
)
ATTESTATION_WORKFLOW_PATH = ".github/workflows/quartus-fit.yml"
ATTESTATION_SOURCE_REF = "refs/heads/main"
ATTESTATION_RUN_INVOCATION_PATTERN = re.compile(
    r"https://github[.]com/RegionallyFamous/swan-song/actions/runs/"
    r"([1-9][0-9]*)/attempts/([1-9][0-9]*)"
)
JOB_NONCE_PATTERN = re.compile(r"[0-9a-f]{32}")
AUDIT_REQUIRED_TRUE_GATES = {
    "assembly_success",
    "connectivity_warnings_reviewed",
    "fit_success",
    "flow_success",
    "hold_timing",
    "io_delay_constraints_preserved",
    "no_evaluation_or_time_limited_ip",
    "no_critical_warnings",
    "no_unconstrained_paths",
    "pll_self_reset_configured",
    "ram_block_headroom",
    "recovery_timing",
    "removal_timing",
    "setup_timing",
    "timing_analysis_success",
}


def package_filename(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise ValueError(f"{description} must be a nonempty filename")
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise ValueError(f"{description} must not contain a path: {value!r}")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def installed_payload_records(
    *,
    dist: pathlib.Path,
    bitstream_name: str,
    bitstream: bytes,
    chip32_name: str,
    chip32: bytes,
) -> dict[str, dict[str, object]]:
    """Identify the exact non-private Pocket-facing files in one package."""

    generated = {
        (pathlib.PurePosixPath("Cores/RegionallyFamous.SwanSong") / bitstream_name).as_posix(): bitstream,
        (pathlib.PurePosixPath("Cores/RegionallyFamous.SwanSong") / chip32_name).as_posix(): chip32,
    }
    result: dict[str, dict[str, object]] = {}
    for name in hardware_qa_installed_payload_names(bitstream_name, chip32_name):
        payload = generated.get(name)
        if payload is None:
            payload = (dist / pathlib.Path(*pathlib.PurePosixPath(name).parts)).read_bytes()
        result[name] = {"size": len(payload), "sha256": sha256_bytes(payload)}
    return result


def exact_members(
    value: object, description: str, expected: set[str]
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be an object")
    missing = expected - value.keys()
    unknown = value.keys() - expected
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise ValueError(f"{description} has invalid members ({'; '.join(details)})")
    return value


def evidence_integer(value: object, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{description} must be a nonnegative integer")
    return value


def evidence_sha256(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{description} must be a lowercase SHA-256 digest")
    return value


def _git(source_root: pathlib.Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            "release packaging requires a readable exact Git checkout"
            + (f": {detail}" if detail else "")
        ) from error
    return result.stdout


def _relative_source_file(
    source_root: pathlib.Path, path: pathlib.Path, expected: pathlib.PurePosixPath
) -> pathlib.Path:
    resolved = path.resolve()
    expected_path = source_root / pathlib.Path(*expected.parts)
    if resolved != expected_path.resolve():
        raise ValueError(
            f"release input must be the exact checked-out {expected.as_posix()}: {path}"
        )
    return resolved


def validate_release_source_checkout(
    *,
    source_root: pathlib.Path,
    dist: pathlib.Path,
    chip32_assembly: pathlib.Path,
    chip32_encoded_image: pathlib.Path,
    rbf_filename: str,
    rbf_bytes: bytes,
    source_commit: str,
) -> dict[str, object]:
    """Bind every release input to one clean, exact source commit.

    The raw RBF is generated rather than tracked, so its identity is bound to
    the same commit by the independently validated V2 build evidence. All
    source-controlled package inputs are additionally compared byte-for-byte
    with their blobs at that commit.
    """

    source_root = source_root.resolve()
    repository_root = pathlib.Path(
        _git(source_root, "rev-parse", "--show-toplevel")
        .decode("utf-8")
        .strip()
    ).resolve()
    if repository_root != source_root:
        raise ValueError("release source root is not the exact Git checkout root")
    head = _git(source_root, "rev-parse", "HEAD").decode("ascii").strip()
    if head != source_commit:
        raise ValueError(
            "release build evidence source commit does not match checkout HEAD"
        )
    tree = _git(source_root, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    if re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise ValueError("release checkout tree identity is malformed")
    status = _git(
        source_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status:
        first = status.decode("utf-8", errors="replace").splitlines()[0]
        raise ValueError(
            "release packaging requires a clean exact source checkout; "
            f"first dirty path: {first}"
        )

    dist = _relative_source_file(
        source_root, dist, pathlib.PurePosixPath("dist")
    )
    assembly = _relative_source_file(
        source_root,
        chip32_assembly,
        pathlib.PurePosixPath("src/support/chip32.asm"),
    )
    encoded_image = _relative_source_file(
        source_root,
        chip32_encoded_image,
        pathlib.PurePosixPath("src/support/chip32.bin.hex"),
    )

    requested = (
        "dist",
        "src/support/chip32.asm",
        "src/support/chip32.bin.hex",
    )
    raw_tree = _git(source_root, "ls-tree", "-r", "-z", "HEAD", "--", *requested)
    records: dict[str, tuple[str, str]] = {}
    for raw_record in raw_tree.split(b"\0"):
        if not raw_record:
            continue
        try:
            header, raw_path = raw_record.split(b"\t", 1)
            mode, kind, object_id = header.decode("ascii").split(" ")
            relative = raw_path.decode("utf-8")
        except (UnicodeError, ValueError) as error:
            raise ValueError("release Git tree inventory is malformed") from error
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"release source input is not a regular Git blob: {relative}")
        records[relative] = (mode, object_id)

    required_leafs = {
        "src/support/chip32.asm",
        "src/support/chip32.bin.hex",
    }
    if not required_leafs.issubset(records):
        raise ValueError("release checkout is missing a tracked Chip32 input")
    dist_files = {name for name in records if name.startswith("dist/")}
    if not dist_files:
        raise ValueError("release checkout has no tracked dist files")

    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in dist.rglob("*"):
        metadata = path.lstat()
        relative = "dist/" + path.relative_to(dist).as_posix()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"release dist input must not be a symlink: {relative}")
        if stat.S_ISREG(metadata.st_mode):
            actual_files.add(relative)
        elif stat.S_ISDIR(metadata.st_mode):
            actual_directories.add(relative)
        else:
            raise ValueError(f"release dist input is a special file: {relative}")
    if actual_files != dist_files:
        missing = sorted(dist_files - actual_files)
        extra = sorted(actual_files - dist_files)
        raise ValueError(
            "release dist inventory does not match the exact source commit "
            f"(missing={missing!r}, extra={extra!r})"
        )
    expected_directories = {
        parent.as_posix()
        for filename in dist_files
        for parent in pathlib.PurePosixPath(filename).parents
        if parent.as_posix() not in {".", "dist"}
    }
    if actual_directories != expected_directories:
        raise ValueError("release dist contains an untracked or missing directory")

    tracked_files: dict[str, dict[str, object]] = {}
    for relative in sorted(records):
        path = source_root / pathlib.Path(*pathlib.PurePosixPath(relative).parts)
        payload = path.read_bytes()
        mode, object_id = records[relative]
        committed = _git(source_root, "show", f"{source_commit}:{relative}")
        if payload != committed:
            raise ValueError(
                f"release source input changed after clean-check validation: {relative}"
            )
        tracked_files[relative] = {
            "git_blob": object_id,
            "mode": mode,
            "size": len(payload),
            "sha256": sha256_bytes(payload),
        }

    return {
        "magic": RELEASE_SOURCE_INPUTS_V1,
        "repository": EXPECTED_REPOSITORY,
        "source_commit": source_commit,
        "source_tree": tree,
        "dist_directory": "dist",
        "dist_directories": sorted(actual_directories),
        "chip32_assembly": "src/support/chip32.asm",
        "chip32_encoded_image": "src/support/chip32.bin.hex",
        "tracked_files": tracked_files,
        "raw_rbf": {
            "filename": rbf_filename,
            "size": len(rbf_bytes),
            "sha256": sha256_bytes(rbf_bytes),
        },
    }


def verify_release_dist_snapshot(
    stage: pathlib.Path, source_inputs: dict[str, object]
) -> None:
    tracked = source_inputs["tracked_files"]
    assert isinstance(tracked, dict)
    expected = {
        name.removeprefix("dist/"): record
        for name, record in tracked.items()
        if name.startswith("dist/")
    }
    actual_files = {
        path.relative_to(stage).as_posix(): path
        for path in stage.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if set(actual_files) != set(expected):
        raise ValueError("release dist snapshot changed after source binding")
    actual_directories = sorted(
        "dist/" + path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_dir() and not path.is_symlink()
    )
    if actual_directories != source_inputs["dist_directories"]:
        raise ValueError("release dist directory snapshot changed after source binding")
    for relative, path in actual_files.items():
        payload = path.read_bytes()
        record = expected[relative]
        if not isinstance(record, dict) or record.get("size") != len(payload) or record.get(
            "sha256"
        ) != sha256_bytes(payload):
            raise ValueError(
                f"release dist snapshot changed after source binding: {relative}"
            )


def release_chip32_image(source_root: pathlib.Path, source_commit: str) -> bytes:
    """Build Chip32 from immutable blobs addressed by the evidence commit."""

    assembly_path = "src/support/chip32.asm"
    encoded_path = "src/support/chip32.bin.hex"
    assembly_bytes = _git(source_root, "show", f"{source_commit}:{assembly_path}")
    encoded_bytes = _git(source_root, "show", f"{source_commit}:{encoded_path}")
    return chip32_image_bytes(
        assembly_bytes,
        encoded_bytes,
        assembly_description=f"{source_commit}:{assembly_path}",
        encoded_image_description=f"{source_commit}:{encoded_path}",
    )


def quartus_report_version(report_bytes: bytes, description: str) -> str:
    try:
        report_text = decode_quartus_report(report_bytes)
    except UnicodeError as error:
        raise ValueError(
            f"{description} contains bytes other than UTF-8 and Quartus's "
            "Latin-1 degree symbol"
        ) from error

    versions: list[str] = []
    for line in report_text.splitlines():
        stripped = line.strip()
        if ";" in stripped:
            fields = [field.strip() for field in stripped.strip(";").split(";")]
            if len(fields) == 2 and fields[0].casefold() in {
                "quartus prime version",
                "quartus version",
            }:
                value = " ".join(fields[1].split())
                versions.append(value.removeprefix("Version "))
                continue
        flat = re.fullmatch(
            r"\s*(?:Quartus Prime Version|Quartus Version)\s+"
            r"((?:Version\s+)?21[.][^\r\n]*)\s*",
            line,
            flags=re.IGNORECASE,
        )
        if flat is not None:
            value = " ".join(flat.group(1).split())
            versions.append(value.removeprefix("Version "))

    unique_versions = sorted(set(versions))
    if len(unique_versions) != 1:
        raise ValueError(
            f"{description} must contain one unambiguous Quartus version line"
        )
    version = unique_versions[0]
    if QUARTUS_REPORT_VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(
            f"{description} must identify exact Quartus {RELEASE_QUARTUS_VERSION}"
        )
    return version


def parse_build_id_words(build_id_text: str) -> dict[str, str]:
    required_addresses = {0x0E0: "0E0", 0x0E1: "0E1", 0x0E2: "0E2"}
    assignments: dict[str, list[tuple[int, str]]] = {
        label: [] for label in required_addresses.values()
    }
    for line_number, line in enumerate(build_id_text.splitlines(), 1):
        match = MIF_ASSIGNMENT_PATTERN.fullmatch(line)
        if match is None:
            continue
        address = int(match.group(1), 16)
        if address in required_addresses:
            assignments[required_addresses[address]].append(
                (line_number, match.group(2).lower())
            )

    parsed: dict[str, str] = {}
    for address in sorted(assignments):
        observed = assignments[address]
        if len(observed) != 1:
            locations = ", ".join(str(line) for line, _ in observed) or "none"
            raise ValueError(
                "build evidence build ID must assign each source identity word "
                f"exactly once; {address} appears at lines {locations}"
            )
        parsed[address] = observed[0][1]
    return parsed


def _canonical_json_sha256(value: object) -> str:
    return sha256_bytes(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    )


def _bound_signed_build_file(
    *,
    evidence_directory: pathlib.Path,
    value: object,
    expected_relative: str,
    description: str,
) -> tuple[pathlib.Path, bytes, dict[str, object]]:
    record = exact_members(value, description, {"filename", "size", "sha256"})
    if record["filename"] != expected_relative:
        raise ValueError(f"{description} filename must be {expected_relative}")
    relative = pathlib.PurePosixPath(expected_relative)
    current = evidence_directory
    for part in relative.parts[:-1]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError as error:
            raise ValueError(f"{description} parent directory is missing: {current}") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"{description} parent must be a real directory: {current}")
    path = evidence_directory.joinpath(*relative.parts)
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ValueError(f"{description} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{description} must be a nonsymlink regular file: {path}")
    if metadata.st_nlink != 1:
        raise ValueError(f"{description} must not be a hard link: {path}")
    expected_size = evidence_integer(record["size"], f"{description} size")
    if expected_size <= 0 or expected_size > 8 * 1024 * 1024:
        raise ValueError(f"{description} size is outside the accepted bound")
    payload = path.read_bytes()
    if len(payload) != expected_size:
        raise ValueError(f"{description} size mismatch")
    expected_sha256 = evidence_sha256(
        record["sha256"], f"{description} SHA-256"
    )
    if sha256_bytes(payload) != expected_sha256:
        raise ValueError(f"{description} SHA-256 mismatch")
    return path, payload, {
        "filename": expected_relative,
        "size": expected_size,
        "sha256": expected_sha256,
    }


def _verify_signed_origin_attestation(
    *,
    candidate: pathlib.Path,
    bundle: pathlib.Path,
    source_commit: str,
) -> dict[str, object]:
    """Verify one candidate audit against GitHub's official attestation roots."""

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
            if isinstance(error, subprocess.CalledProcessError) and error.stderr
            else str(error)
        )
        raise ValueError(
            "signed Quartus candidate provenance did not verify"
            + (f": {detail}" if detail else "")
        ) from error
    try:
        payload = strict_json_loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError, StrictJsonError) as error:
        raise ValueError("gh returned malformed attestation verification JSON") from error
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("expected exactly one verified candidate attestation")
    envelope = payload[0]
    result = (
        envelope.get("verificationResult") if isinstance(envelope, dict) else None
    )
    signature = result.get("signature") if isinstance(result, dict) else None
    certificate = signature.get("certificate") if isinstance(signature, dict) else None
    timestamps = result.get("verifiedTimestamps") if isinstance(result, dict) else None
    statement = result.get("statement") if isinstance(result, dict) else None
    if not isinstance(certificate, dict) or not isinstance(timestamps, list) or not timestamps:
        raise ValueError("verified attestation lacks certificate or timestamp evidence")
    subjects = statement.get("subject") if isinstance(statement, dict) else None
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise ValueError("verified attestation must bind exactly one subject")
    subject = subjects[0] if isinstance(subjects[0], dict) else None
    digest = subject.get("digest") if isinstance(subject, dict) else None
    candidate_sha256 = sha256_bytes(candidate.read_bytes())
    if (
        not isinstance(subject, dict)
        or subject.get("name") != QUARTUS_AUDIT_FILENAME
        or digest != {"sha256": candidate_sha256}
    ):
        raise ValueError("verified attestation subject is not the candidate audit")

    signer_uri = (
        "https://github.com/RegionallyFamous/swan-song/"
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
        "sourceRepositoryURI": "https://github.com/RegionallyFamous/swan-song",
        "sourceRepositoryDigest": source_commit,
        "sourceRepositoryRef": ATTESTATION_SOURCE_REF,
        "buildConfigURI": signer_uri,
        "buildConfigDigest": source_commit,
        "buildTrigger": "workflow_dispatch",
    }
    if any(
        certificate.get(name) != expected
        for name, expected in expected_certificate.items()
    ):
        raise ValueError("verified candidate certificate origin does not match release")
    invocation = certificate.get("runInvocationURI")
    match = (
        ATTESTATION_RUN_INVOCATION_PATTERN.fullmatch(invocation)
        if isinstance(invocation, str)
        else None
    )
    if match is None:
        raise ValueError("verified candidate certificate has no exact run invocation")
    return {
        "run_id": int(match.group(1)),
        "run_attempt": int(match.group(2)),
        "runner_environment": certificate["runnerEnvironment"],
    }


def validate_signed_build_origins(
    *,
    value: object,
    evidence_directory: pathlib.Path,
    source_commit: str,
    source_date_epoch: int,
    rbf: dict[str, object],
    build_id: dict[str, object],
    root_audit: dict[str, object],
) -> dict[str, object]:
    """Reverify and bind two distinct signed GitHub Quartus build origins."""

    pair = exact_members(
        value,
        "build evidence.signed_build_origins",
        {"magic", "source_commit", "source_date_epoch", "rbf", "build_id", "builds"},
    )
    if pair["magic"] != SIGNED_BUILD_PAIR_V1:
        raise ValueError(
            f"build evidence signed origins require {SIGNED_BUILD_PAIR_V1}"
        )
    if pair["source_commit"] != source_commit:
        raise ValueError("signed build origins source commit does not match evidence")
    if evidence_integer(
        pair["source_date_epoch"], "signed build origins source_date_epoch"
    ) != source_date_epoch:
        raise ValueError("signed build origins source epoch does not match evidence")
    expected_rbf = {
        "filename": "ap_core.rbf",
        "size": rbf["size"],
        "sha256": rbf["sha256"],
    }
    if exact_members(
        pair["rbf"], "signed build origins RBF", {"filename", "size", "sha256"}
    ) != expected_rbf:
        raise ValueError("signed build origins RBF does not match release evidence")
    expected_build_id = {
        "filename": "build_id.mif",
        "size": build_id["size"],
        "sha256": build_id["sha256"],
    }
    if exact_members(
        pair["build_id"],
        "signed build origins build ID",
        {"filename", "size", "sha256"},
    ) != expected_build_id:
        raise ValueError("signed build origins build ID does not match release evidence")

    builds = pair["builds"]
    if not isinstance(builds, list) or len(builds) != 2:
        raise ValueError("signed build origins must contain exactly two builds")
    expected_fields = {
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
    normalized: list[dict[str, object]] = []
    for index, label in enumerate(("a", "b")):
        build = exact_members(
            builds[index], f"signed build origin {label}", expected_fields
        )
        expected_static = {
            "label": label,
            "repository": ATTESTATION_REPOSITORY,
            "workflow_path": ATTESTATION_WORKFLOW_PATH,
            "source_ref": ATTESTATION_SOURCE_REF,
            "source_commit": source_commit,
            "job": "fit",
            "runner_environment": "self-hosted",
        }
        if any(build.get(name) != expected for name, expected in expected_static.items()):
            raise ValueError(f"signed build origin {label} identity is invalid")
        run_id = evidence_integer(build["run_id"], f"signed build origin {label} run_id")
        run_attempt = evidence_integer(
            build["run_attempt"], f"signed build origin {label} run_attempt"
        )
        if run_id == 0 or run_attempt == 0:
            raise ValueError(f"signed build origin {label} run identity must be positive")
        nonce = build["job_nonce"]
        if not isinstance(nonce, str) or JOB_NONCE_PATTERN.fullmatch(nonce) is None:
            raise ValueError(
                f"signed build origin {label} job_nonce must be 32 lowercase hex"
            )
        candidate_relative = (
            f"signed-builds/{label}/{QUARTUS_AUDIT_FILENAME}"
        )
        bundle_relative = f"signed-builds/{label}/{ATTESTATION_FILENAME}"
        candidate_path, candidate_bytes, candidate_identity = _bound_signed_build_file(
            evidence_directory=evidence_directory,
            value=build["candidate_audit"],
            expected_relative=candidate_relative,
            description=f"signed build origin {label} candidate audit",
        )
        bundle_path, _bundle_bytes, bundle_identity = _bound_signed_build_file(
            evidence_directory=evidence_directory,
            value=build["attestation_bundle"],
            expected_relative=bundle_relative,
            description=f"signed build origin {label} attestation bundle",
        )
        submitted_sha256 = evidence_sha256(
            build["submitted_audit_sha256"],
            f"signed build origin {label} submitted audit SHA-256",
        )
        if submitted_sha256 != candidate_identity["sha256"]:
            raise ValueError(
                f"signed build origin {label} submitted audit identity mismatch"
            )
        try:
            audit_document = strict_json_loads(candidate_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, StrictJsonError) as error:
            raise ValueError(
                f"signed build origin {label} candidate audit is invalid JSON"
            ) from error
        recomputed_sha256 = evidence_sha256(
            build["recomputed_audit_sha256"],
            f"signed build origin {label} recomputed audit SHA-256",
        )
        if recomputed_sha256 != _canonical_json_sha256(audit_document):
            raise ValueError(
                f"signed build origin {label} recomputed audit identity mismatch"
            )
        audit_top = exact_members(
            audit_document, f"signed build origin {label} audit", {"quartus_audit"}
        )
        audit = audit_top["quartus_audit"]
        if not isinstance(audit, dict):
            raise ValueError(f"signed build origin {label} audit body is invalid")
        if (
            audit.get("magic") != "SWAN_SONG_QUARTUS_AUDIT_V1"
            or audit.get("audit_pass") is not True
            or audit.get("release_eligible") is not False
        ):
            raise ValueError(f"signed build origin {label} audit is not a candidate pass")
        provenance = audit.get("provenance")
        expected_provenance = {
            "source_commit": source_commit,
            "source_date_epoch": str(source_date_epoch),
            "workflow_repository": ATTESTATION_REPOSITORY,
            "workflow_path": ATTESTATION_WORKFLOW_PATH,
            "workflow_sha": source_commit,
            "workflow_run_id": str(run_id),
            "workflow_run_attempt": str(run_attempt),
            "workflow_job": "fit",
            "workflow_job_nonce": nonce,
            "platform": "linux/amd64",
            "quartus": "21.1.1.850 Lite",
            "device": "5CEBA4F23C8",
        }
        if not isinstance(provenance, dict) or any(
            provenance.get(name) != expected
            for name, expected in expected_provenance.items()
        ):
            raise ValueError(
                f"signed build origin {label} workflow metadata does not match"
            )
        artifacts = audit.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ValueError(f"signed build origin {label} audit artifacts are missing")
        if artifacts.get("output_files/ap_core.rbf") != {
            "size": expected_rbf["size"],
            "sha256": expected_rbf["sha256"],
        }:
            raise ValueError(f"signed build origin {label} RBF binding does not match")
        if artifacts.get("build_id.mif") != {
            "size": expected_build_id["size"],
            "sha256": expected_build_id["sha256"],
        }:
            raise ValueError(
                f"signed build origin {label} build ID binding does not match"
            )
        candidate_gates = audit.get("candidate_gates")
        if not isinstance(candidate_gates, dict) or any(
            candidate_gates.get(gate) is not True
            for gate in AUDIT_REQUIRED_TRUE_GATES
        ):
            raise ValueError(
                f"signed build origin {label} audit has unaccepted candidate gates"
            )
        if candidate_gates.get("compressed_bitstream") is not None or any(
            candidate_gates.get(gate) is not False
            for gate in ("pocket_hardware", "dock_hardware")
        ):
            raise ValueError(
                f"signed build origin {label} audit makes invalid release claims"
            )
        verified_attestation = _verify_signed_origin_attestation(
            candidate=candidate_path,
            bundle=bundle_path,
            source_commit=source_commit,
        )
        if verified_attestation != {
            "run_id": run_id,
            "run_attempt": run_attempt,
            "runner_environment": "self-hosted",
        }:
            raise ValueError(
                f"signed build origin {label} certificate run identity does not match"
            )
        if label == "a" and (
            candidate_identity["size"] != root_audit["size"]
            or candidate_identity["sha256"] != root_audit["sha256"]
        ):
            raise ValueError(
                "signed build origin a is not the root recomputed Quartus audit"
            )
        normalized.append(
            {
                **expected_static,
                "run_id": run_id,
                "run_attempt": run_attempt,
                "job_nonce": nonce,
                "candidate_audit": candidate_identity,
                "attestation_bundle": bundle_identity,
                "recomputed_audit_sha256": recomputed_sha256,
                "submitted_audit_sha256": submitted_sha256,
            }
        )
    if normalized[0]["run_id"] == normalized[1]["run_id"]:
        raise ValueError("signed build origins must have distinct workflow run IDs")
    if normalized[0]["job_nonce"] == normalized[1]["job_nonce"]:
        raise ValueError("signed build origins must have distinct workflow job nonces")
    if normalized[0]["candidate_audit"]["sha256"] == normalized[1]["candidate_audit"]["sha256"]:
        raise ValueError("signed build origins must have distinct candidate audits")
    if normalized[0]["attestation_bundle"]["sha256"] == normalized[1]["attestation_bundle"]["sha256"]:
        raise ValueError("signed build origins must have distinct attestation bundles")
    return {
        "magic": SIGNED_BUILD_PAIR_V1,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "rbf": expected_rbf,
        "build_id": expected_build_id,
        "builds": normalized,
    }


def validate_quartus_audit_binding(
    *,
    entry_value: object,
    evidence_directory: pathlib.Path,
    source_commit: str,
    source_date_epoch: int,
    rbf: dict[str, object],
    build_id: dict[str, object],
    reports: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Recompute and bind the complete Quartus candidate to release evidence."""

    entry = exact_members(
        entry_value,
        "build evidence.quartus_audit",
        {"filename", "size", "sha256"},
    )
    filename = package_filename(
        entry["filename"], "build evidence Quartus audit filename"
    )
    if filename != QUARTUS_AUDIT_FILENAME:
        raise ValueError(
            f"build evidence Quartus audit filename must be {QUARTUS_AUDIT_FILENAME}"
        )
    audit_path = evidence_directory / filename
    if not audit_path.is_file() or audit_path.is_symlink():
        raise ValueError(f"build evidence Quartus audit is missing: {audit_path}")
    audit_bytes = audit_path.read_bytes()
    if evidence_integer(entry["size"], "build evidence Quartus audit size") != len(
        audit_bytes
    ):
        raise ValueError("build evidence Quartus audit size mismatch")
    audit_digest = evidence_sha256(
        entry["sha256"], "build evidence Quartus audit SHA-256"
    )
    if audit_digest != sha256_bytes(audit_bytes):
        raise ValueError("build evidence Quartus audit SHA-256 mismatch")
    try:
        document = strict_json_loads(audit_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, StrictJsonError) as error:
        raise ValueError(f"invalid Quartus audit {audit_path}: {error}") from error

    try:
        recomputed = fit_audit.audit(evidence_directory)
    except (fit_audit.AuditError, OSError) as error:
        raise ValueError(
            f"could not recompute Quartus audit from release evidence: {error}"
        ) from error
    if document != recomputed:
        raise ValueError(
            "build evidence Quartus audit does not match a fresh audit of its "
            "complete artifact bundle"
        )

    top = exact_members(document, "Quartus audit", {"quartus_audit"})
    audit = top["quartus_audit"]
    if not isinstance(audit, dict):
        raise ValueError("Quartus audit envelope must be an object")
    if audit.get("magic") != "SWAN_SONG_QUARTUS_AUDIT_V1":
        raise ValueError("Quartus audit magic must be SWAN_SONG_QUARTUS_AUDIT_V1")
    if audit.get("audit_pass") is not True:
        raise ValueError("Quartus audit must have audit_pass true")
    if audit.get("release_eligible") is not False:
        raise ValueError("candidate Quartus audit must retain release_eligible false")

    provenance = audit.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Quartus audit source provenance is missing")
    expected_provenance = {
        "source_commit": source_commit,
        "source_date_epoch": str(source_date_epoch),
        "platform": "linux/amd64",
        "quartus": "21.1.1.850 Lite",
        "device": "5CEBA4F23C8",
    }
    if any(
        provenance.get(key) != value
        for key, value in expected_provenance.items()
    ):
        raise ValueError("Quartus audit source identity does not match release evidence")
    if audit.get("identity") != {
        "revision": "ap_core",
        "top_level": "apf_top",
        "family": "Cyclone V",
        "device": "5CEBA4F23C8",
    }:
        raise ValueError("Quartus audit target identity is not the release target")

    artifacts = audit.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Quartus audit artifact identities are missing")
    expected_bindings = {
        "output_files/ap_core.rbf": {
            "size": rbf["size"],
            "sha256": rbf["sha256"],
        },
        "build_id.mif": {
            "size": build_id["size"],
            "sha256": build_id["sha256"],
        },
    }
    for report in reports.values():
        expected_bindings[report["filename"]] = {
            "size": report["size"],
            "sha256": report["sha256"],
        }
    for relative, identity in expected_bindings.items():
        if artifacts.get(relative) != identity:
            raise ValueError(
                f"Quartus audit {relative} identity does not match release evidence"
            )

    candidate_gates = audit.get("candidate_gates")
    if not isinstance(candidate_gates, dict):
        raise ValueError("Quartus audit candidate gates are missing")
    failed = sorted(
        gate for gate in AUDIT_REQUIRED_TRUE_GATES if candidate_gates.get(gate) is not True
    )
    if failed:
        raise ValueError(
            "Quartus audit has unaccepted candidate gates: " + ", ".join(failed)
        )
    if candidate_gates.get("compressed_bitstream") is not None:
        raise ValueError("candidate Quartus audit must not claim compressed-bitstream QA")
    for gate in ("pocket_hardware", "dock_hardware"):
        if candidate_gates.get(gate) is not False:
            raise ValueError(f"candidate Quartus audit must not claim {gate}")

    return {
        "filename": filename,
        "size": len(audit_bytes),
        "sha256": audit_digest,
        "magic": audit["magic"],
        "audit_pass": True,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "artifact_count": len(artifacts),
        "required_candidate_gates": {
            gate: True for gate in sorted(AUDIT_REQUIRED_TRUE_GATES)
        },
    }


def validate_hardware_qa_binding(
    *,
    entry_value: object,
    evidence_directory: pathlib.Path,
    rbf_filename: str,
    rbf_size: int,
    rbf_sha256: str,
) -> dict[str, object]:
    """Re-verify and bind the exact physical Pocket/Dock QA record.

    The private inventory is used during verification but is never copied into
    the release package. Its identity is retained in provenance so the review
    inputs cannot be silently swapped after the package is made.
    """

    entry = exact_members(
        entry_value,
        "build evidence.hardware_qa",
        {"manifest", "inventory"},
    )

    def bound_file(value: object, description: str) -> tuple[pathlib.Path, dict[str, object]]:
        record = exact_members(value, description, {"filename", "size", "sha256"})
        filename = package_filename(record["filename"], f"{description} filename")
        path = evidence_directory / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{description} is missing or not a regular file: {path}")
        if path.stat().st_nlink != 1:
            raise ValueError(f"{description} must not be a hard link: {path}")
        payload = path.read_bytes()
        size = evidence_integer(record["size"], f"{description} size")
        if not payload or size != len(payload):
            raise ValueError(f"{description} size mismatch")
        digest = evidence_sha256(record["sha256"], f"{description} SHA-256")
        if digest != sha256_bytes(payload):
            raise ValueError(f"{description} SHA-256 mismatch")
        return path, {"filename": filename, "size": size, "sha256": digest}

    manifest_path, manifest = bound_file(
        entry["manifest"], "build evidence hardware QA manifest"
    )
    inventory_path, inventory = bound_file(
        entry["inventory"], "build evidence hardware QA inventory"
    )
    if manifest["filename"].casefold() == inventory["filename"].casefold():
        raise ValueError("hardware QA manifest and inventory filenames must be distinct")

    try:
        summary = verify_hardware_qa_manifest(
            manifest_path, inventory_path, require_pass=True
        )
    except ValueError as error:
        raise ValueError(f"hardware QA verification failed: {error}") from error
    if summary.get("magic") != HARDWARE_QA_MANIFEST_MAGIC:
        raise ValueError("hardware QA verifier returned an unexpected manifest magic")
    if summary.get("manifest_sha256") != manifest["sha256"]:
        raise ValueError("hardware QA verifier manifest identity does not match evidence")
    if summary.get("inventory_sha256") != inventory["sha256"]:
        raise ValueError("hardware QA verifier inventory identity does not match evidence")
    if summary.get("cases") != len(HARDWARE_QA_CASE_SPECS):
        raise ValueError("hardware QA verifier returned an incomplete case catalogue")

    core = summary.get("core")
    if not isinstance(core, dict):
        raise ValueError("hardware QA verifier did not return a core identity")
    raw_rbf = core.get("raw_rbf")
    expected_raw_rbf = {
        "filename": rbf_filename,
        "size": rbf_size,
        "sha256": rbf_sha256,
    }
    if raw_rbf != expected_raw_rbf:
        raise ValueError("hardware QA raw RBF identity does not match release evidence")
    if core.get("core_id") != "RegionallyFamous.SwanSong":
        raise ValueError("hardware QA core identity is not RegionallyFamous.SwanSong")

    return {
        "manifest": manifest,
        "inventory": inventory,
        "magic": summary["magic"],
        "run_id": summary["run_id"],
        "case_count": len(HARDWARE_QA_CASE_SPECS),
        "artifact_count": summary["artifacts"],
        "firmware_version": summary["firmware_version"],
        "core": core,
        "pocket": summary["pocket"],
        "dock": summary["dock"],
    }


def validate_known_title_compatibility_binding(
    *,
    entry_value: object,
    evidence_directory: pathlib.Path,
    source_commit: str,
    rbf_sha256: str,
) -> dict[str, object]:
    """Re-verify the exact private known-title Pocket/Dock campaign."""

    entry = exact_members(
        entry_value,
        "build evidence.known_title_compatibility",
        {"catalogue", "manifest"},
    )

    def bound_file(value: object, description: str) -> tuple[pathlib.Path, dict[str, object]]:
        record = exact_members(value, description, {"filename", "size", "sha256"})
        filename = package_filename(record["filename"], f"{description} filename")
        path = evidence_directory / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{description} is missing or not a regular file: {path}")
        if path.stat().st_nlink != 1:
            raise ValueError(f"{description} must not be a hard link: {path}")
        payload = path.read_bytes()
        size = evidence_integer(record["size"], f"{description} size")
        if not payload or size != len(payload):
            raise ValueError(f"{description} size mismatch")
        digest = evidence_sha256(record["sha256"], f"{description} SHA-256")
        if digest != sha256_bytes(payload):
            raise ValueError(f"{description} SHA-256 mismatch")
        return path, {"filename": filename, "size": size, "sha256": digest}

    catalogue_path, catalogue = bound_file(
        entry["catalogue"], "build evidence known-title catalogue"
    )
    manifest_path, manifest = bound_file(
        entry["manifest"], "build evidence known-title manifest"
    )
    if catalogue["filename"].casefold() == manifest["filename"].casefold():
        raise ValueError("known-title catalogue and manifest filenames must be distinct")
    checked_in_catalogue = SOURCE_ROOT / "known-title-compatibility.json"
    if checked_in_catalogue.is_symlink() or not checked_in_catalogue.is_file():
        raise ValueError("checked-in known-title compatibility catalogue is unavailable")
    if catalogue["sha256"] != sha256_bytes(checked_in_catalogue.read_bytes()):
        raise ValueError(
            "build evidence known-title catalogue is not the exact checked-in catalogue"
        )
    try:
        summary = verify_known_title_compatibility_manifest(
            catalogue_path, manifest_path, require_pass=True
        )
    except ValueError as error:
        raise ValueError(f"known-title compatibility verification failed: {error}") from error
    expected_cases = len(KNOWN_TITLE_COMMERCIAL_IDS) + len(KNOWN_TITLE_OPEN_IDS)
    if summary.get("magic") != KNOWN_TITLE_COMPATIBILITY_MAGIC:
        raise ValueError("known-title verifier returned an unexpected manifest magic")
    if summary.get("catalogue_sha256") != catalogue["sha256"]:
        raise ValueError("known-title verifier catalogue identity does not match evidence")
    if summary.get("manifest_sha256") != manifest["sha256"]:
        raise ValueError("known-title verifier manifest identity does not match evidence")
    if summary.get("cases") != expected_cases:
        raise ValueError("known-title verifier returned an incomplete case catalogue")
    if summary.get("commercial_cases") != len(KNOWN_TITLE_COMMERCIAL_IDS):
        raise ValueError("known-title verifier returned an incomplete commercial catalogue")
    if summary.get("open_sanity_cases") != len(KNOWN_TITLE_OPEN_IDS):
        raise ValueError("known-title verifier returned an incomplete open-fixture catalogue")
    if summary.get("status") != {"pass": expected_cases * 2, "fail": 0, "pending": 0}:
        raise ValueError("known-title verifier did not return all Pocket and Dock passes")
    run = summary.get("run")
    if not isinstance(run, dict):
        raise ValueError("known-title verifier did not return a run identity")
    if run.get("core_commit") != source_commit:
        raise ValueError("known-title run source commit does not match release evidence")
    if run.get("raw_rbf_sha256") != rbf_sha256:
        raise ValueError("known-title run raw RBF does not match release evidence")

    return {
        "catalogue": catalogue,
        "manifest": manifest,
        "magic": summary["magic"],
        "run_id": run.get("run_id"),
        "case_count": expected_cases,
        "commercial_case_count": len(KNOWN_TITLE_COMMERCIAL_IDS),
        "open_sanity_case_count": len(KNOWN_TITLE_OPEN_IDS),
        "mode_pass_count": expected_cases * 2,
        "artifact_count": summary["artifacts"],
        "artifact_index_sha256": summary["artifact_index_sha256"],
        "firmware_version": run.get("firmware_version"),
    }


def validate_build_evidence(
    path: pathlib.Path, rbf_bytes: bytes, rbf_filename: str
) -> dict[str, object]:
    """Validate a reviewable release attestation and every file it hashes.

    Report parsing is deliberately not presented as a substitute for TimeQuest
    review.  The manifest records the accepted gates, while this function makes
    those claims tamper-evident by checking the exact report and RBF bytes.
    """

    path = path.absolute()
    if path.is_symlink():
        raise ValueError(f"build evidence must not be a symlink: {path}")
    if not path.is_file():
        raise ValueError(f"build evidence does not exist or is not a regular file: {path}")
    path = path.resolve()
    evidence_bytes = path.read_bytes()
    try:
        document = strict_json_loads(evidence_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, StrictJsonError) as error:
        raise ValueError(f"invalid build evidence {path}: {error}") from error
    top = exact_members(document, "build evidence", {"release_evidence"})
    raw_evidence = top["release_evidence"]
    if not isinstance(raw_evidence, dict):
        raise ValueError("build evidence.release_evidence must be an object")
    evidence_magic = raw_evidence.get("magic")
    if evidence_magic not in {RELEASE_EVIDENCE_V1, RELEASE_EVIDENCE_V2}:
        raise ValueError(
            "build evidence magic must be SWAN_SONG_RELEASE_EVIDENCE_V1 or "
            "SWAN_SONG_RELEASE_EVIDENCE_V2"
        )
    evidence_members = {
        "magic",
        "source_commit",
        "source_date_epoch",
        "quartus_version",
        "rbf",
        "build_id",
        "reports",
        "gates",
    }
    if evidence_magic == RELEASE_EVIDENCE_V2:
        evidence_members.update(
            {"quartus_audit", "hardware_qa", "signed_build_origins"}
        )
        if "known_title_compatibility" in raw_evidence:
            evidence_members.add("known_title_compatibility")
    evidence = exact_members(
        raw_evidence,
        "build evidence.release_evidence",
        evidence_members,
    )
    source_commit = evidence["source_commit"]
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise ValueError("build evidence source_commit must be a lowercase 40-hex commit")
    source_date_epoch = evidence_integer(
        evidence["source_date_epoch"], "build evidence source_date_epoch"
    )
    if source_date_epoch > 253_402_300_799:
        raise ValueError("build evidence source_date_epoch is later than 9999-12-31")
    quartus_version = evidence["quartus_version"]
    if quartus_version != RELEASE_QUARTUS_VERSION:
        raise ValueError(
            f"build evidence must identify exact Quartus {RELEASE_QUARTUS_VERSION}"
        )

    rbf = exact_members(
        evidence["rbf"], "build evidence.rbf", {"filename", "size", "sha256"}
    )
    evidence_rbf_filename = package_filename(
        rbf["filename"], "build evidence RBF filename"
    )
    if evidence_rbf_filename != rbf_filename:
        raise ValueError("build evidence RBF filename does not match --rbf")
    if evidence_integer(rbf["size"], "build evidence RBF size") != len(rbf_bytes):
        raise ValueError("build evidence RBF size does not match --rbf")
    if evidence_sha256(rbf["sha256"], "build evidence RBF SHA-256") != sha256_bytes(rbf_bytes):
        raise ValueError("build evidence RBF SHA-256 does not match --rbf")

    build_id = exact_members(
        evidence["build_id"],
        "build evidence.build_id",
        {"filename", "size", "sha256"},
    )
    build_id_filename = package_filename(
        build_id["filename"], "build evidence build ID filename"
    )
    if not build_id_filename.endswith(".mif"):
        raise ValueError("build evidence build ID filename must end in .mif")
    build_id_path = path.parent / build_id_filename
    if not build_id_path.is_file() or build_id_path.is_symlink():
        raise ValueError(f"build evidence build ID is missing: {build_id_path}")
    build_id_bytes = build_id_path.read_bytes()
    if evidence_integer(build_id["size"], "build evidence build ID size") != len(build_id_bytes):
        raise ValueError("build evidence build ID size mismatch")
    build_id_digest = evidence_sha256(
        build_id["sha256"], "build evidence build ID SHA-256"
    )
    if build_id_digest != sha256_bytes(build_id_bytes):
        raise ValueError("build evidence build ID SHA-256 mismatch")
    try:
        build_id_text = build_id_bytes.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("build evidence build ID is not UTF-8") from error
    source_time = datetime.datetime.fromtimestamp(
        source_date_epoch, tz=datetime.timezone.utc
    )
    required_build_id_lines = {
        f"-- Reproducible source commit: {source_commit}",
        f"-- SOURCE_DATE_EPOCH: {source_date_epoch}",
    }
    normalized_build_id_lines = {line.strip() for line in build_id_text.splitlines()}
    missing_build_id_lines = required_build_id_lines - normalized_build_id_lines
    if missing_build_id_lines:
        raise ValueError(
            "build evidence build ID does not match source identity: "
            + ", ".join(sorted(missing_build_id_lines))
        )
    expected_build_id_words = {
        "0E0": f"{source_time:%Y%m%d}",
        "0E1": f"00{source_time:%H%M%S}",
        "0E2": source_commit[:8],
    }
    build_id_words = parse_build_id_words(build_id_text)
    mismatched_build_id_words = {
        address: (build_id_words[address], expected)
        for address, expected in expected_build_id_words.items()
        if build_id_words[address] != expected
    }
    if mismatched_build_id_words:
        details = ", ".join(
            f"{address}={observed} (expected {expected})"
            for address, (observed, expected) in sorted(
                mismatched_build_id_words.items()
            )
        )
        raise ValueError(
            f"build evidence build ID does not match source identity: {details}"
        )

    reports = exact_members(
        evidence["reports"], "build evidence.reports", {"flow", "fit", "sta"}
    )
    expected_suffixes = {
        "flow": ".flow.rpt",
        "fit": ".fit.rpt",
        "sta": ".sta.rpt",
    }
    verified_reports: dict[str, dict[str, object]] = {}
    report_names: list[str] = []
    report_versions: dict[str, str] = {}
    for kind, suffix in expected_suffixes.items():
        report = exact_members(
            reports[kind],
            f"build evidence.reports.{kind}",
            {"filename", "size", "sha256"},
        )
        if evidence_magic == RELEASE_EVIDENCE_V2:
            filename = report["filename"]
            expected_filename = f"output_files/ap_core.{kind}.rpt"
            if filename != expected_filename:
                raise ValueError(
                    f"build evidence {kind} report filename must be "
                    f"{expected_filename} for V2"
                )
        else:
            filename = package_filename(
                report["filename"], f"build evidence {kind} report filename"
            )
        if not filename.endswith(suffix):
            raise ValueError(f"build evidence {kind} report must end in {suffix}")
        report_names.append(filename.casefold())
        report_path = path.parent / filename
        if not report_path.is_file() or report_path.is_symlink():
            raise ValueError(f"build evidence {kind} report is missing: {report_path}")
        report_bytes = report_path.read_bytes()
        if not report_bytes:
            raise ValueError(f"build evidence {kind} report is empty: {report_path}")
        if evidence_integer(report["size"], f"build evidence {kind} report size") != len(report_bytes):
            raise ValueError(f"build evidence {kind} report size mismatch")
        digest = evidence_sha256(
            report["sha256"], f"build evidence {kind} report SHA-256"
        )
        if digest != sha256_bytes(report_bytes):
            raise ValueError(f"build evidence {kind} report SHA-256 mismatch")
        report_versions[kind] = quartus_report_version(
            report_bytes, f"build evidence {kind} report"
        )
        verified_reports[kind] = {
            "filename": filename,
            "size": len(report_bytes),
            "sha256": digest,
        }
    if len(report_names) != len(set(report_names)):
        raise ValueError("build evidence report filenames must be distinct")
    if len(set(report_versions.values())) != 1:
        raise ValueError("build evidence report Quartus version lines disagree")

    gate_names = {
        "flow_success",
        "fit_success",
        "setup_timing",
        "hold_timing",
        "recovery_timing",
        "removal_timing",
        "no_unconstrained_paths",
        "no_critical_warnings",
        "compressed_bitstream",
        "pocket_hardware",
        "dock_hardware",
    }
    gates = exact_members(evidence["gates"], "build evidence.gates", gate_names)
    failed_gates = sorted(name for name in gate_names if gates[name] is not True)
    if failed_gates:
        raise ValueError("build evidence has unaccepted gates: " + ", ".join(failed_gates))

    verified_audit = None
    verified_hardware_qa = None
    verified_known_title_compatibility = None
    verified_signed_build_origins = None
    if evidence_magic == RELEASE_EVIDENCE_V2:
        verified_audit = validate_quartus_audit_binding(
            entry_value=evidence["quartus_audit"],
            evidence_directory=path.parent,
            source_commit=source_commit,
            source_date_epoch=source_date_epoch,
            rbf={
                "size": len(rbf_bytes),
                "sha256": rbf["sha256"],
            },
            build_id={
                "size": len(build_id_bytes),
                "sha256": build_id_digest,
            },
            reports=verified_reports,
        )
        verified_hardware_qa = validate_hardware_qa_binding(
            entry_value=evidence["hardware_qa"],
            evidence_directory=path.parent,
            rbf_filename=rbf_filename,
            rbf_size=len(rbf_bytes),
            rbf_sha256=rbf["sha256"],
        )
        if "known_title_compatibility" in evidence:
            verified_known_title_compatibility = validate_known_title_compatibility_binding(
                entry_value=evidence["known_title_compatibility"],
                evidence_directory=path.parent,
                source_commit=source_commit,
                rbf_sha256=rbf["sha256"],
            )
        verified_signed_build_origins = validate_signed_build_origins(
            value=evidence["signed_build_origins"],
            evidence_directory=path.parent,
            source_commit=source_commit,
            source_date_epoch=source_date_epoch,
            rbf={
                "size": len(rbf_bytes),
                "sha256": rbf["sha256"],
            },
            build_id={
                "size": len(build_id_bytes),
                "sha256": build_id_digest,
            },
            root_audit=verified_audit,
        )

    return {
        "magic": evidence_magic,
        "manifest_filename": path.name,
        "manifest_size": len(evidence_bytes),
        "manifest_sha256": sha256_bytes(evidence_bytes),
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "quartus_version": quartus_version,
        "build_id": {
            "filename": build_id_filename,
            "size": len(build_id_bytes),
            "sha256": build_id_digest,
        },
        "reports": verified_reports,
        "quartus_audit": verified_audit,
        "hardware_qa": verified_hardware_qa,
        "known_title_compatibility": verified_known_title_compatibility,
        "signed_build_origins": verified_signed_build_origins,
        "gates": {name: True for name in sorted(gate_names)},
    }


def release_policy_text(value: object, description: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(not 0x20 <= ord(character) <= 0x7E for character in value)
    ):
        raise ValueError(f"{description} must be a nonempty printable ASCII string")
    return value


def release_policy_date(value: object, description: str) -> str:
    date = release_policy_text(value, description, 10)
    try:
        if datetime.date.fromisoformat(date).isoformat() != date:
            raise ValueError
    except ValueError as error:
        raise ValueError(f"{description} must be YYYY-MM-DD") from error
    return date


def release_policy_semver(
    value: object, description: str
) -> tuple[str, tuple[int, int, int, tuple[str, ...] | None]]:
    version = release_policy_text(value, description, 31)
    match = SEMVER_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"{description} must be a Semantic Version")
    prerelease = match.group(4)
    prerelease_identifiers = (
        tuple(prerelease.split(".")) if prerelease is not None else None
    )
    if prerelease_identifiers is not None and any(
        identifier.isdigit()
        and len(identifier) > 1
        and identifier.startswith("0")
        for identifier in prerelease_identifiers
    ):
        raise ValueError(
            f"{description} has a numeric prerelease identifier with a leading zero"
        )
    return version, (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        prerelease_identifiers,
    )


def compare_semver(
    left: tuple[int, int, int, tuple[str, ...] | None],
    right: tuple[int, int, int, tuple[str, ...] | None],
) -> int:
    for left_number, right_number in zip(left[:3], right[:3]):
        if left_number != right_number:
            return 1 if left_number > right_number else -1

    left_prerelease = left[3]
    right_prerelease = right[3]
    if left_prerelease is None or right_prerelease is None:
        if left_prerelease is right_prerelease:
            return 0
        return 1 if left_prerelease is None else -1

    for left_identifier, right_identifier in zip(
        left_prerelease, right_prerelease
    ):
        if left_identifier == right_identifier:
            continue
        left_numeric = left_identifier.isdigit()
        right_numeric = right_identifier.isdigit()
        if left_numeric and right_numeric:
            return 1 if int(left_identifier) > int(right_identifier) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_identifier > right_identifier else -1
    if len(left_prerelease) == len(right_prerelease):
        return 0
    return 1 if len(left_prerelease) > len(right_prerelease) else -1


def validate_release_history(
    value: object,
    description: str,
    *,
    allow_empty: bool,
) -> tuple[
    list[tuple[str, str]],
    set[str],
    str | None,
    tuple[int, int, int, tuple[str, ...] | None] | None,
    str | None,
]:
    """Validate one identity's release history without merging namespaces."""

    if not isinstance(value, list):
        raise ValueError(f"{description} must be an array")
    if not value and not allow_empty:
        raise ValueError(f"{description} must not be empty")

    published: list[tuple[str, str]] = []
    published_semvers: list[
        tuple[str, tuple[int, int, int, tuple[str, ...] | None]]
    ] = []
    published_semver_precedences: set[
        tuple[int, int, int, tuple[str, ...] | None]
    ] = set()
    published_versions: set[str] = set()
    for index, release_value in enumerate(value):
        release = exact_members(
            release_value,
            f"{description}[{index}]",
            {"version", "date_release"},
        )
        version, parsed_version = release_policy_semver(
            release["version"], f"{description}[{index}].version"
        )
        release_date = release_policy_date(
            release["date_release"], f"{description}[{index}].date_release"
        )
        if version in published_versions:
            raise ValueError(f"{description} version is duplicated: {version}")
        if parsed_version in published_semver_precedences:
            raise ValueError(
                f"{description} Semantic Version precedence is duplicated: {version}"
            )
        published_versions.add(version)
        published_semver_precedences.add(parsed_version)
        published.append((version, release_date))
        published_semvers.append((version, parsed_version))

    latest_version: str | None = None
    latest_semver: tuple[int, int, int, tuple[str, ...] | None] | None = None
    for published_version, published_semver in published_semvers:
        if latest_semver is None or compare_semver(published_semver, latest_semver) > 0:
            latest_version = published_version
            latest_semver = published_semver

    return (
        published,
        published_versions,
        latest_version,
        latest_semver,
        max((date for _, date in published), default=None),
    )


def validate_release_policy(
    path: pathlib.Path, definition: ValidatedDistribution
) -> dict[str, object]:
    """Validate the reviewed public-inventory boundary for a release package."""

    path = path.absolute()
    if path.is_symlink():
        raise ValueError(f"release policy must not be a symlink: {path}")
    if not path.is_file():
        raise ValueError(
            f"release policy does not exist or is not a regular file: {path}"
        )
    path = path.resolve()
    policy_bytes = path.read_bytes()
    try:
        document = strict_json_loads(policy_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, StrictJsonError) as error:
        raise ValueError(f"invalid release policy {path}: {error}") from error

    top = exact_members(document, "release policy", {"release_policy"})
    policy = exact_members(
        top["release_policy"],
        "release policy.release_policy",
        {
            "magic",
            "publisher",
            "authorization",
            "predecessor",
            "published_releases",
        },
    )
    if policy["magic"] != "SWAN_SONG_RELEASE_POLICY_V2":
        raise ValueError("release policy magic must be SWAN_SONG_RELEASE_POLICY_V2")

    publisher = exact_members(
        policy["publisher"],
        "release policy.publisher",
        {"core_id", "repository_url"},
    )
    approved_core_id = release_policy_text(
        publisher["core_id"], "release policy publisher.core_id", 63
    )
    approved_repository_url = release_policy_text(
        publisher["repository_url"],
        "release policy publisher.repository_url",
        63,
    )

    authorization = exact_members(
        policy["authorization"],
        "release policy.authorization",
        {"identity_authorized", "distribution_and_licensing_authorized"},
    )
    identity_authorized = authorization["identity_authorized"]
    distribution_authorized = authorization[
        "distribution_and_licensing_authorized"
    ]
    if not isinstance(identity_authorized, bool):
        raise ValueError(
            "release policy authorization.identity_authorized must be boolean"
        )
    if not isinstance(distribution_authorized, bool):
        raise ValueError(
            "release policy authorization.distribution_and_licensing_authorized "
            "must be boolean"
        )

    predecessor = exact_members(
        policy["predecessor"],
        "release policy.predecessor",
        {"core_id", "repository_url", "inventory", "published_releases"},
    )
    predecessor_core_id = release_policy_text(
        predecessor["core_id"], "release policy predecessor.core_id", 63
    )
    predecessor_repository_url = release_policy_text(
        predecessor["repository_url"],
        "release policy predecessor.repository_url",
        63,
    )
    if predecessor_core_id == approved_core_id:
        raise ValueError("release policy predecessor must use a distinct core identity")
    inventory = exact_members(
        predecessor["inventory"],
        "release policy.predecessor.inventory",
        {"repository_url", "commit"},
    )
    inventory_repository_url = release_policy_text(
        inventory["repository_url"],
        "release policy predecessor.inventory.repository_url",
        100,
    )
    inventory_commit = inventory["commit"]
    if (
        not isinstance(inventory_commit, str)
        or len(inventory_commit) != 40
        or any(character not in "0123456789abcdef" for character in inventory_commit)
    ):
        raise ValueError(
            "release policy predecessor.inventory.commit must be a lowercase "
            "40-hex commit"
        )
    (
        predecessor_published,
        _,
        predecessor_latest_version,
        _,
        predecessor_latest_date,
    ) = validate_release_history(
        predecessor["published_releases"],
        "release policy predecessor.published_releases",
        allow_empty=False,
    )
    (
        published,
        published_versions,
        latest_published_version,
        latest_published_semver,
        latest_published_date,
    ) = validate_release_history(
        policy["published_releases"],
        "release policy published_releases",
        allow_empty=True,
    )

    if not identity_authorized:
        raise ValueError("release publisher identity is not authorized by release policy")
    if definition.core_id != approved_core_id:
        raise ValueError(
            f"release publisher identity {definition.core_id} does not match "
            f"approved policy {approved_core_id}"
        )
    if definition.repository_url != approved_repository_url:
        raise ValueError(
            f"release repository URL {definition.repository_url} does not match "
            f"approved policy {approved_repository_url}"
        )
    if not distribution_authorized:
        raise ValueError(
            "release distribution and licensing are not authorized by release policy"
        )

    candidate_version, candidate_semver = release_policy_semver(
        definition.version, "release metadata version"
    )
    if (definition.version, definition.release_date) in published:
        raise ValueError(
            f"release tuple is already published for {definition.core_id}: "
            f"version {definition.version}, date {definition.release_date}"
        )
    if definition.version in published_versions:
        raise ValueError(
            f"release version is already published for {definition.core_id}: "
            f"{definition.version}"
        )
    if (
        latest_published_semver is not None
        and compare_semver(candidate_semver, latest_published_semver) <= 0
    ):
        raise ValueError(
            "release version must be newer than latest published Semantic Version "
            f"{latest_published_version} for {definition.core_id}: {candidate_version}"
        )
    if (
        latest_published_date is not None
        and definition.release_date <= latest_published_date
    ):
        raise ValueError(
            "release date must be later than latest published date "
            f"{latest_published_date} for {definition.core_id}"
        )

    return {
        "manifest_filename": path.name,
        "manifest_size": len(policy_bytes),
        "manifest_sha256": sha256_bytes(policy_bytes),
        "magic": "SWAN_SONG_RELEASE_POLICY_V2",
        "core_id": approved_core_id,
        "repository_url": approved_repository_url,
        "identity_authorized": identity_authorized,
        "distribution_and_licensing_authorized": distribution_authorized,
        "predecessor": {
            "core_id": predecessor_core_id,
            "repository_url": predecessor_repository_url,
            "inventory": {
                "repository_url": inventory_repository_url,
                "commit": inventory_commit,
            },
            "published_release_count": len(predecessor_published),
            "latest_published_version": predecessor_latest_version,
            "latest_published_date": predecessor_latest_date,
        },
        "published_release_count": len(published),
        "latest_published_version": latest_published_version,
        "latest_published_date": latest_published_date,
    }


def write_atomic(path: pathlib.Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    ) as temporary_file:
        temporary_path = pathlib.Path(temporary_file.name)
        temporary_file.write(value)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def create_package(
    *,
    dist: pathlib.Path,
    rbf: pathlib.Path,
    output: pathlib.Path,
    chip32_assembly: pathlib.Path,
    chip32_encoded_image: pathlib.Path,
    build_evidence: pathlib.Path | None = None,
    release_policy: pathlib.Path | None = None,
    release: bool = False,
) -> None:
    dist = dist.resolve()
    rbf = rbf.resolve()
    output = output.resolve()
    provenance_output = output.with_name(output.name + ".provenance.json")
    evidence_argument = (
        build_evidence.absolute() if build_evidence is not None else None
    )
    policy_argument = (
        release_policy.absolute()
        if release and release_policy is not None
        else None
    )

    protected_inputs = [
        (rbf, "--rbf"),
        (chip32_assembly.resolve(), "--chip32-assembly"),
        (chip32_encoded_image.resolve(), "--chip32-encoded-image"),
    ]
    if evidence_argument is not None:
        protected_inputs.append((evidence_argument.resolve(), "--build-evidence"))
    if policy_argument is not None:
        protected_inputs.append((policy_argument.resolve(), "--release-policy"))
    for generated_path, generated_description in (
        (output, "--output"),
        (provenance_output, "package provenance output"),
    ):
        for protected_path, protected_description in protected_inputs:
            if generated_path == protected_path:
                raise ValueError(
                    f"{generated_description} must not overwrite "
                    f"{protected_description}"
                )
    try:
        output.relative_to(dist)
    except ValueError:
        pass
    else:
        raise ValueError("--output must be outside --dist to prevent package self-inclusion")

    # A failed current packaging attempt must not leave an older ZIP looking
    # like its result.
    for stale in (output, provenance_output):
        if stale.exists():
            if not stale.is_file():
                raise ValueError(f"package output exists and is not a file: {stale}")
            stale.unlink()

    if not rbf.is_file():
        raise ValueError(f"RBF does not exist or is not a file: {rbf}")
    if rbf.stat().st_size == 0:
        raise ValueError(f"RBF is empty: {rbf}")

    definition: ValidatedDistribution = validate_distribution(dist)
    bitstream_name = definition.bitstream_name
    chip32_name = definition.chip32_name
    core_directory = dist / definition.core_directory
    rbf_bytes = rbf.read_bytes()
    verified_evidence = (
        validate_build_evidence(evidence_argument, rbf_bytes, rbf.name)
        if evidence_argument is not None
        else None
    )
    if release and verified_evidence is None:
        raise ValueError("--release requires --build-evidence")
    if release and verified_evidence["magic"] != RELEASE_EVIDENCE_V2:
        raise ValueError(
            "--release requires SWAN_SONG_RELEASE_EVIDENCE_V2 with a recomputed "
            "Quartus audit binding"
        )
    if release and policy_argument is None:
        raise ValueError("--release requires --release-policy")
    verified_policy = (
        validate_release_policy(policy_argument, definition)
        if release
        else None
    )
    verified_licensing = validate_license_manifest(
        dist,
        source_root=SOURCE_ROOT if release else None,
        require_release_ready=release,
    )
    if release and verified_evidence.get("known_title_compatibility") is None:
        raise ValueError(
            "--release requires accepted known-title compatibility evidence for "
            "every Pocket and Dock case"
        )
    chip32 = (
        release_chip32_image(SOURCE_ROOT, verified_evidence["source_commit"])
        if release
        else chip32_image(chip32_assembly, chip32_encoded_image)
    )
    reversed_rbf = rbf_bytes.translate(REVERSE)
    if release and output.name != definition.recommended_archive_name:
        raise ValueError(
            "release package filename must be " + definition.recommended_archive_name
        )
    if release:
        hardware_core = verified_evidence["hardware_qa"]["core"]
        core_json_path = core_directory / "core.json"
        core_json_bytes = core_json_path.read_bytes()
        expected_core_json = {
            "filename": "core.json",
            "size": len(core_json_bytes),
            "sha256": sha256_bytes(core_json_bytes),
        }
        if hardware_core.get("core_json") != expected_core_json:
            raise ValueError(
                "hardware QA core.json identity does not match the release distribution"
            )
        interact_json_path = core_directory / "interact.json"
        interact_json_bytes = interact_json_path.read_bytes()
        expected_interact_json = {
            "filename": "interact.json",
            "size": len(interact_json_bytes),
            "sha256": sha256_bytes(interact_json_bytes),
        }
        if hardware_core.get("interact_json") != expected_interact_json:
            raise ValueError(
                "hardware QA interact.json identity does not match the release distribution"
            )
        if hardware_core.get("persistent_settings") != list(
            HARDWARE_QA_PERSISTENT_SETTING_NAMES
        ):
            raise ValueError(
                "hardware QA persistent-setting catalogue does not match release policy"
            )
        if hardware_core.get("version") != definition.version:
            raise ValueError("hardware QA core version does not match release metadata")
        if hardware_core.get("date_release") != definition.release_date:
            raise ValueError("hardware QA core date does not match release metadata")
        installed = hardware_core.get("installed_bitstream")
        if not isinstance(installed, dict) or installed.get("filename") != bitstream_name:
            raise ValueError(
                "hardware QA installed bitstream does not match release metadata"
            )
        expected_installed_payloads = installed_payload_records(
            dist=dist,
            bitstream_name=bitstream_name,
            bitstream=reversed_rbf,
            chip32_name=chip32_name,
            chip32=chip32,
        )
        if hardware_core.get("installed_payloads") != expected_installed_payloads:
            raise ValueError(
                "hardware QA installed payload inventory does not match the release distribution"
            )

    release_source_inputs = (
        validate_release_source_checkout(
            source_root=SOURCE_ROOT,
            dist=dist,
            chip32_assembly=chip32_assembly,
            chip32_encoded_image=chip32_encoded_image,
            rbf_filename=rbf.name,
            rbf_bytes=rbf_bytes,
            source_commit=verified_evidence["source_commit"],
        )
        if release
        else None
    )

    with tempfile.TemporaryDirectory(prefix="swan-song-") as temporary:
        stage = pathlib.Path(temporary)
        shutil.copytree(dist, stage, dirs_exist_ok=True)
        if release_source_inputs is not None:
            verify_release_dist_snapshot(stage, release_source_inputs)
        # Source-control placeholders are not Pocket SD assets.  Preserve the
        # empty directory entry but never expose .gitkeep in a release ZIP.
        for placeholder in stage.rglob(".gitkeep"):
            placeholder.unlink()
        stage_core_directory = stage / definition.core_directory
        bitstream = stage_core_directory / bitstream_name
        bitstream.write_bytes(reversed_rbf)
        (stage_core_directory / chip32_name).write_bytes(chip32)

        forbidden = {".ws", ".wsc", ".rom", ".sav"}
        leaked = [path for path in stage.rglob("*") if path.suffix.lower() in forbidden]
        if leaked:
            raise ValueError(
                "refusing to package ROM/BIOS/save files: " + ", ".join(map(str, leaked))
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
        ) as temporary_file:
            temporary_output = pathlib.Path(temporary_file.name)
        try:
            # Stored entries avoid zlib-version-dependent output bytes. The
            # APF bitstream is small enough that strict cross-host package
            # reproducibility is more valuable than ZIP compression here.
            with zipfile.ZipFile(
                temporary_output, "w", zipfile.ZIP_STORED
            ) as archive:
                for path in sorted(stage.rglob("*")):
                    relative = path.relative_to(stage).as_posix()
                    if path.is_dir():
                        relative += "/"
                    info = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
                    # ZipInfo otherwise records the current host OS, making Windows
                    # and Unix builds differ despite identical inputs.
                    info.create_system = 3
                    info.compress_type = zipfile.ZIP_STORED
                    if path.is_dir():
                        info.external_attr = (0o40755 << 16) | 0x10
                        archive.writestr(info, b"")
                    else:
                        info.external_attr = 0o100644 << 16
                        archive.writestr(info, path.read_bytes())
            temporary_output.replace(output)
        finally:
            temporary_output.unlink(missing_ok=True)

    try:
        with zipfile.ZipFile(output) as archive:
            entries = {
                info.filename: {
                    "size": info.file_size,
                    "sha256": sha256_bytes(archive.read(info.filename)),
                }
                for info in archive.infolist()
                if not info.is_dir()
            }
        package_provenance = {
            "magic": "SWAN_SONG_PACKAGE_PROVENANCE_V1",
            "release": release,
            "archive": {
                "filename": output.name,
                "size": output.stat().st_size,
                "sha256": sha256_bytes(output.read_bytes()),
            },
            "raw_rbf": {
                "filename": rbf.name,
                "size": len(rbf_bytes),
                "sha256": sha256_bytes(rbf_bytes),
            },
            "packaged_bitstream": {
                "filename": bitstream_name,
                "size": len(reversed_rbf),
                "sha256": sha256_bytes(reversed_rbf),
            },
            "chip32": {
                "filename": chip32_name,
                "size": len(chip32),
                "sha256": sha256_bytes(chip32),
            },
            "entries": entries,
            "build_evidence": verified_evidence,
            "license_manifest": verified_licensing,
        }
        if verified_policy is not None:
            package_provenance["release_policy"] = verified_policy
        if release_source_inputs is not None:
            package_provenance["source_inputs"] = release_source_inputs
        provenance = {"package_provenance": package_provenance}
        encoded_provenance = (
            json.dumps(provenance, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        write_atomic(provenance_output, encoded_provenance)
    except Exception:
        output.unlink(missing_ok=True)
        provenance_output.unlink(missing_ok=True)
        raise


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--rbf", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--dist", default=root / "dist", type=pathlib.Path)
    parser.add_argument(
        "--build-evidence",
        type=pathlib.Path,
        help="reviewed release evidence manifest with RBF/report hashes",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help=(
            "assembler-internal only; direct CLI release use is rejected (run "
            "scripts/assemble_stable_release.py)"
        ),
    )
    parser.add_argument(
        "--release-policy",
        default=root / "release-policy.json",
        type=pathlib.Path,
        help="reviewed public-inventory policy used only with --release",
    )
    parser.add_argument(
        "--chip32-assembly",
        default=root / "src/support/chip32.asm",
        type=pathlib.Path,
    )
    parser.add_argument(
        "--chip32-encoded-image",
        default=root / "src/support/chip32.bin.hex",
        type=pathlib.Path,
    )
    args = parser.parse_args()

    if args.release:
        parser.error(
            "public release packaging is assembler-only; use "
            "scripts/assemble_stable_release.py"
        )

    try:
        create_package(
            dist=args.dist,
            rbf=args.rbf,
            output=args.output,
            chip32_assembly=args.chip32_assembly,
            chip32_encoded_image=args.chip32_encoded_image,
            build_evidence=args.build_evidence,
            release_policy=args.release_policy if args.release else None,
            release=args.release,
        )
    except ValueError as error:
        parser.error(str(error))

    print(args.output.resolve())


if __name__ == "__main__":
    main()
