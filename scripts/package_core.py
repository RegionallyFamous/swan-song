#!/usr/bin/env python3
"""Create a deterministic APF package from dist/ and a compiled Quartus RBF."""

import argparse
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import tempfile
import zipfile

from build_chip32 import chip32_image
from package_validator import ValidatedDistribution, validate_distribution
from reverse_rbf import REVERSE


SEMVER_PATTERN = re.compile(
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


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


def validate_build_evidence(path: pathlib.Path, rbf_bytes: bytes) -> dict[str, object]:
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
        document = json.loads(evidence_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid build evidence {path}: {error}") from error
    top = exact_members(document, "build evidence", {"release_evidence"})
    evidence = exact_members(
        top["release_evidence"],
        "build evidence.release_evidence",
        {
            "magic",
            "source_commit",
            "source_date_epoch",
            "quartus_version",
            "rbf",
            "build_id",
            "reports",
            "gates",
        },
    )
    if evidence["magic"] != "SWAN_SONG_RELEASE_EVIDENCE_V1":
        raise ValueError("build evidence magic must be SWAN_SONG_RELEASE_EVIDENCE_V1")
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
    if not isinstance(quartus_version, str) or not quartus_version.startswith("21.1.1"):
        raise ValueError("build evidence must identify Quartus 21.1.1")

    rbf = exact_members(
        evidence["rbf"], "build evidence.rbf", {"filename", "size", "sha256"}
    )
    package_filename(rbf["filename"], "build evidence RBF filename")
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
        f"0E0 : {source_time:%Y%m%d};",
        f"0E1 : 00{source_time:%H%M%S};",
        f"0E2 : {source_commit[:8]};",
    }
    normalized_build_id_lines = {line.strip() for line in build_id_text.splitlines()}
    missing_build_id_lines = required_build_id_lines - normalized_build_id_lines
    if missing_build_id_lines:
        raise ValueError(
            "build evidence build ID does not match source identity: "
            + ", ".join(sorted(missing_build_id_lines))
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
    for kind, suffix in expected_suffixes.items():
        report = exact_members(
            reports[kind],
            f"build evidence.reports.{kind}",
            {"filename", "size", "sha256"},
        )
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
        if b"21.1.1" not in report_bytes:
            raise ValueError(f"build evidence {kind} report does not identify Quartus 21.1.1")
        verified_reports[kind] = {
            "filename": filename,
            "size": len(report_bytes),
            "sha256": digest,
        }
    if len(report_names) != len(set(report_names)):
        raise ValueError("build evidence report filenames must be distinct")

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

    return {
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
        document = json.loads(policy_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid release policy {path}: {error}") from error

    top = exact_members(document, "release policy", {"release_policy"})
    policy = exact_members(
        top["release_policy"],
        "release policy.release_policy",
        {"magic", "inventory_commit", "publisher", "published_releases"},
    )
    if policy["magic"] != "SWAN_SONG_RELEASE_POLICY_V1":
        raise ValueError("release policy magic must be SWAN_SONG_RELEASE_POLICY_V1")
    inventory_commit = policy["inventory_commit"]
    if (
        not isinstance(inventory_commit, str)
        or len(inventory_commit) != 40
        or any(character not in "0123456789abcdef" for character in inventory_commit)
    ):
        raise ValueError(
            "release policy inventory_commit must be a lowercase 40-hex commit"
        )

    publisher = exact_members(
        policy["publisher"],
        "release policy.publisher",
        {"authorized", "core_id", "repository_url"},
    )
    authorized = publisher["authorized"]
    if not isinstance(authorized, bool):
        raise ValueError("release policy publisher.authorized must be boolean")
    approved_core_id = release_policy_text(
        publisher["core_id"], "release policy publisher.core_id", 63
    )
    approved_repository_url = release_policy_text(
        publisher["repository_url"],
        "release policy publisher.repository_url",
        63,
    )

    releases_value = policy["published_releases"]
    if not isinstance(releases_value, list):
        raise ValueError("release policy published_releases must be an array")
    if not releases_value:
        raise ValueError("release policy published_releases must not be empty")
    published: list[tuple[str, str]] = []
    published_semvers: list[
        tuple[str, tuple[int, int, int, tuple[str, ...] | None]]
    ] = []
    published_semver_precedences: set[
        tuple[int, int, int, tuple[str, ...] | None]
    ] = set()
    published_versions: set[str] = set()
    for index, release_value in enumerate(releases_value):
        release = exact_members(
            release_value,
            f"release policy published_releases[{index}]",
            {"version", "date_release"},
        )
        version, parsed_version = release_policy_semver(
            release["version"],
            f"release policy published_releases[{index}].version",
        )
        release_date = release_policy_date(
            release["date_release"],
            f"release policy published_releases[{index}].date_release",
        )
        if version in published_versions:
            raise ValueError(
                f"release policy published version is duplicated: {version}"
            )
        if parsed_version in published_semver_precedences:
            raise ValueError(
                "release policy published Semantic Version precedence is duplicated: "
                f"{version}"
            )
        published_versions.add(version)
        published_semver_precedences.add(parsed_version)
        published.append((version, release_date))
        published_semvers.append((version, parsed_version))

    if not authorized:
        raise ValueError("release publisher is not authorized by release policy")
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
    latest_published_version: str | None = None
    latest_published_semver: tuple[int, int, int, tuple[str, ...] | None] | None = None
    for published_version, published_semver in published_semvers:
        if (
            latest_published_semver is None
            or compare_semver(published_semver, latest_published_semver) > 0
        ):
            latest_published_version = published_version
            latest_published_semver = published_semver
    if (
        latest_published_semver is not None
        and compare_semver(candidate_semver, latest_published_semver) <= 0
    ):
        raise ValueError(
            "release version must be newer than latest published Semantic Version "
            f"{latest_published_version} for {definition.core_id}: {candidate_version}"
        )
    latest_published_date = max((date for _, date in published), default=None)
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
        "inventory_commit": inventory_commit,
        "core_id": approved_core_id,
        "repository_url": approved_repository_url,
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
        validate_build_evidence(evidence_argument, rbf_bytes)
        if evidence_argument is not None
        else None
    )
    if release and verified_evidence is None:
        raise ValueError("--release requires --build-evidence")
    if release and policy_argument is None:
        raise ValueError("--release requires --release-policy")
    verified_policy = (
        validate_release_policy(policy_argument, definition)
        if release
        else None
    )
    if release and output.name != definition.recommended_archive_name:
        raise ValueError(
            "release package filename must be " + definition.recommended_archive_name
        )

    chip32 = chip32_image(chip32_assembly, chip32_encoded_image)

    with tempfile.TemporaryDirectory(prefix="swan-song-") as temporary:
        stage = pathlib.Path(temporary)
        shutil.copytree(dist, stage, dirs_exist_ok=True)
        # Source-control placeholders are not Pocket SD assets.  Preserve the
        # empty directory entry but never expose .gitkeep in a release ZIP.
        for placeholder in stage.rglob(".gitkeep"):
            placeholder.unlink()
        stage_core_directory = stage / definition.core_directory
        bitstream = stage_core_directory / bitstream_name
        reversed_rbf = rbf_bytes.translate(REVERSE)
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
        }
        if verified_policy is not None:
            package_provenance["release_policy"] = verified_policy
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
        help="require accepted evidence and the official archive naming convention",
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
