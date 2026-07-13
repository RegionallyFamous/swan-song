#!/usr/bin/env python3
"""Safely validate and stage a Swan Song development package for Pocket.

The default CLI operation is a read-only plan. Writing requires ``--apply``;
writing below macOS ``/Volumes`` additionally requires ``--allow-volume``.
No ROM or BIOS is downloaded, and unrelated destination files are never
removed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import stat
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Iterable

from package_validator import ValidatedDistribution, validate_distribution


ROOT = pathlib.Path(__file__).resolve().parent.parent
CURRENT_DIST = ROOT / "dist"
DEFAULT_VOLUMES_ROOT = pathlib.Path("/Volumes")
EXPECTED_CORE_ID = "agg23.WonderSwan"
EXPECTED_PLATFORM_ID = "wonderswan"
EXPECTED_REPOSITORY = "https://github.com/agg23/openfpga-wonderswan"
CORE_DIRECTORY = pathlib.PurePosixPath("Cores") / EXPECTED_CORE_ID
CORE_JSON = CORE_DIRECTORY / "core.json"
DATA_JSON = CORE_DIRECTORY / "data.json"
ASSET_DIRECTORY = pathlib.PurePosixPath("Assets/wonderswan/common")
MAX_ARCHIVE_ENTRIES = 128
MAX_ARCHIVE_FILE_SIZE = 8 * 1024 * 1024
MAX_ARCHIVE_TOTAL_SIZE = 16 * 1024 * 1024
MAX_PROVENANCE_SIZE = 2 * 1024 * 1024


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
    files: tuple[ManagedFile, ...]
    package: pathlib.Path
    provenance: pathlib.Path
    package_sha256: str
    core_version: str
    release_date: str
    new_files: tuple[pathlib.PurePosixPath, ...]
    replaced_files: tuple[pathlib.PurePosixPath, ...]
    unchanged_files: tuple[pathlib.PurePosixPath, ...]
    is_volume: bool
    volumes_root: pathlib.Path


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_input(path: pathlib.Path, description: str, maximum: int | None = None) -> bytes:
    if path.is_symlink():
        raise StagingError(f"{description} must not be a symlink: {path}")
    if not path.is_file():
        raise StagingError(f"{description} does not exist or is not a file: {path}")
    size = path.stat().st_size
    if maximum is not None and size > maximum:
        raise StagingError(f"{description} exceeds {maximum} bytes: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise StagingError(f"cannot read {description} {path}: {error}") from error


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


def _read_archive(path: pathlib.Path) -> tuple[dict[pathlib.PurePosixPath, bytes], set[pathlib.PurePosixPath]]:
    _safe_input(path, "development package")
    payloads: dict[pathlib.PurePosixPath, bytes] = {}
    directories: set[pathlib.PurePosixPath] = set()
    folded: dict[str, pathlib.PurePosixPath] = {}
    total_size = 0
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise StagingError(
                    f"development package has more than {MAX_ARCHIVE_ENTRIES} entries"
                )
            for info in infos:
                relative = _safe_member_name(info.filename)
                _validate_member_type(info)
                folded_name = relative.as_posix().casefold()
                previous = folded.setdefault(folded_name, relative)
                if previous != relative or relative in payloads or relative in directories:
                    raise StagingError(
                        f"duplicate or case-colliding package path: {info.filename}"
                    )
                if info.is_dir():
                    directories.add(relative)
                    continue
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


def _validate_provenance(
    path: pathlib.Path,
    package: pathlib.Path,
    package_payload: bytes,
    payloads: dict[pathlib.PurePosixPath, bytes],
) -> None:
    document = _json(
        _safe_input(path, "package provenance", MAX_PROVENANCE_SIZE),
        "package provenance",
    )
    if set(document) != {"package_provenance"}:
        raise StagingError("package provenance has an unexpected envelope")
    body = _object(document["package_provenance"], "package provenance body")
    if body.get("magic") != "SWAN_SONG_PACKAGE_PROVENANCE_V1":
        raise StagingError("package provenance magic is invalid")
    if body.get("release") is not False:
        raise StagingError("this staging workflow accepts development packages only")
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
) -> ValidatedDistribution:
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
            return validate_distribution(root)
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


def _root(path: pathlib.Path) -> pathlib.Path:
    if path.is_symlink():
        raise StagingError(f"staging directory must not be a symlink: {path}")
    if not path.is_dir():
        raise StagingError(f"staging directory must already exist: {path}")
    result = path.resolve()
    if result == pathlib.Path(result.anchor):
        raise StagingError("refusing to use a filesystem root as the staging directory")
    return result


def _is_within(path: pathlib.Path, parent: pathlib.Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _case_safe_child(parent: pathlib.Path, name: str) -> pathlib.Path:
    if parent.is_symlink():
        raise StagingError(f"managed destination contains a symlink: {parent}")
    if parent.exists() and not parent.is_dir():
        raise StagingError(f"managed destination parent is not a directory: {parent}")
    if parent.is_dir():
        matches = [child.name for child in parent.iterdir() if child.name.casefold() == name.casefold()]
        if len(matches) > 1 or (matches and matches[0] != name):
            raise StagingError(
                f"stale or case-colliding destination identity: {parent / matches[0]}"
            )
    return parent / name


def _destination(root: pathlib.Path, relative: pathlib.PurePosixPath) -> pathlib.Path:
    current = root
    for part in relative.parts:
        current = _case_safe_child(current, part)
        if current.is_symlink():
            raise StagingError(f"managed destination must not be a symlink: {current}")
    try:
        current.relative_to(root)
    except ValueError as error:
        raise StagingError(f"managed destination escaped staging root: {relative}") from error
    return current


def _classify(root: pathlib.Path, files: Iterable[ManagedFile]) -> tuple[tuple, tuple, tuple]:
    new: list[pathlib.PurePosixPath] = []
    replaced: list[pathlib.PurePosixPath] = []
    unchanged: list[pathlib.PurePosixPath] = []
    for managed in files:
        destination = _destination(root, managed.relative)
        if destination.exists():
            if not destination.is_file():
                raise StagingError(f"managed destination is not a regular file: {destination}")
            if destination.read_bytes() == managed.payload:
                unchanged.append(managed.relative)
            else:
                replaced.append(managed.relative)
        else:
            new.append(managed.relative)
    return tuple(new), tuple(replaced), tuple(unchanged)


def plan_staging(
    *,
    staging_dir: pathlib.Path,
    package: pathlib.Path,
    provenance: pathlib.Path,
    bw_bios: pathlib.Path,
    color_bios: pathlib.Path,
    volumes_root: pathlib.Path = DEFAULT_VOLUMES_ROOT,
) -> StagingPlan:
    root = _root(staging_dir)
    package = package.absolute()
    provenance = provenance.absolute()
    package_payload = _safe_input(package, "development package")
    payloads, directories = _read_archive(package)
    _validate_provenance(provenance, package, package_payload, payloads)
    bitstream_name, chip32_name = _core_generated_names(payloads)
    definition = _materialize_source_snapshot(
        payloads, directories, bitstream_name, chip32_name
    )
    _validate_current_checkout(payloads, definition, bitstream_name, chip32_name)
    _validate_bios_contract(payloads)
    bw_payload = _validate_bios(bw_bios.absolute(), "bw.rom", 4096)
    color_payload = _validate_bios(color_bios.absolute(), "color.rom", 8192)

    managed = [
        ManagedFile(relative, payload, "development package")
        for relative, payload in sorted(payloads.items(), key=lambda item: item[0].as_posix())
    ]
    managed.extend(
        (
            ManagedFile(ASSET_DIRECTORY / "bw.rom", bw_payload, "user-supplied BIOS"),
            ManagedFile(ASSET_DIRECTORY / "color.rom", color_payload, "user-supplied BIOS"),
        )
    )
    files = tuple(managed)
    new, replaced, unchanged = _classify(root, files)
    resolved_volumes = volumes_root.resolve()
    is_volume = _is_within(root, resolved_volumes) and root != resolved_volumes
    return StagingPlan(
        root=root,
        files=files,
        package=package,
        provenance=provenance,
        package_sha256=sha256_bytes(package_payload),
        core_version=definition.version,
        release_date=definition.release_date,
        new_files=new,
        replaced_files=replaced,
        unchanged_files=unchanged,
        is_volume=is_volume,
        volumes_root=resolved_volumes,
    )


def _atomic_write(destination: pathlib.Path, payload: bytes) -> None:
    temporary: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = pathlib.Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def apply_staging(plan: StagingPlan, *, allow_volume: bool = False) -> None:
    root = _root(plan.root)
    if root != plan.root:
        raise StagingError("staging directory identity changed after validation")
    if plan.is_volume and not allow_volume:
        raise StagingError(
            f"refusing to write below {plan.volumes_root}; use --allow-volume only for an intentional SD write"
        )
    # Repeat all path/content classification immediately before mutation.
    _classify(root, plan.files)
    for managed in plan.files:
        destination = _destination(root, managed.relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = _destination(root, managed.relative)
        if destination.exists() and destination.read_bytes() == managed.payload:
            continue
        _atomic_write(destination, managed.payload)


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
        f"Core: {EXPECTED_CORE_ID} {plan.core_version} ({plan.release_date})",
        f"Package SHA-256: {plan.package_sha256}",
        (
            f"Managed files: {len(plan.new_files)} new, "
            f"{len(plan.replaced_files)} replace, {len(plan.unchanged_files)} unchanged"
        ),
        f"bw.rom: {bios['bw.rom'][0]} bytes, SHA-256 {bios['bw.rom'][1]}",
        f"color.rom: {bios['color.rom'][0]} bytes, SHA-256 {bios['color.rom'][1]}",
    ]
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
            "Validate and stage a Swan Song development ZIP plus user-supplied BIOS files. "
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
    parser.add_argument("--bw-bios", required=True, type=pathlib.Path)
    parser.add_argument("--color-bios", required=True, type=pathlib.Path)
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
