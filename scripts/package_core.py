#!/usr/bin/env python3
"""Create a deterministic APF package from dist/ and a compiled Quartus RBF."""

import argparse
import datetime
import hashlib
import json
import pathlib
import shutil
import tempfile
import zipfile

from build_chip32 import chip32_image
from package_validator import ValidatedDistribution, validate_distribution
from reverse_rbf import REVERSE


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

    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"build evidence does not exist or is not a regular file: {path}")
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
    release: bool = False,
) -> None:
    dist = dist.resolve()
    rbf = rbf.resolve()
    output = output.resolve()
    provenance_output = output.with_name(output.name + ".provenance.json")

    if output == rbf:
        raise ValueError("--output must not overwrite --rbf")
    if provenance_output == rbf:
        raise ValueError("package provenance output must not overwrite --rbf")
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
        validate_build_evidence(build_evidence, rbf_bytes)
        if build_evidence is not None
        else None
    )
    if release and verified_evidence is None:
        raise ValueError("--release requires --build-evidence")
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
        provenance = {
            "package_provenance": {
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
        }
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
            release=args.release,
        )
    except ValueError as error:
        parser.error(str(error))

    print(args.output.resolve())


if __name__ == "__main__":
    main()
