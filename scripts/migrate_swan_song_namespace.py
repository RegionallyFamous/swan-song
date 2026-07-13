#!/usr/bin/env python3
"""Safely copy Pocket user data from the upstream core ID to Swan Song.

The default operation is a read-only plan. Writing requires ``--apply``.
Only the two fixed console EEPROM files and valid JSON files below the old
Settings and Presets namespaces are eligible. Source files are never moved or
deleted, and cartridge saves and Memories are outside this tool's allowlist.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile


SOURCE_CORE_ID = "agg23.WonderSwan"
DESTINATION_CORE_ID = "RegionallyFamous.SwanSong"
PLATFORM_ID = "wonderswan"

MAX_JSON_FILE_BYTES = 1024 * 1024
MAX_JSON_TOTAL_BYTES = 16 * 1024 * 1024
MAX_JSON_FILES = 4096
MAX_TREE_ENTRIES = 8192
MAX_JSON_DEPTH = 16

EEPROM_FILES = (("mono.eeprom", 128), ("color.eeprom", 2048))
JSON_NAMESPACES = ("Settings", "Presets")
MACOS_FILESYSTEM_METADATA = {".DS_Store"}


class MigrationError(ValueError):
    """The requested namespace migration is unsafe or invalid."""


@dataclass(frozen=True)
class MigrationFile:
    source: PurePosixPath
    destination: PurePosixPath
    payload: bytes
    kind: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(frozen=True)
class MigrationPlan:
    root: Path
    files: tuple[MigrationFile, ...]
    copies: tuple[PurePosixPath, ...]
    identical: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class MigrationResult:
    copied: tuple[PurePosixPath, ...]
    identical: tuple[PurePosixPath, ...]


def _root(path: Path) -> Path:
    absolute = path.absolute()
    try:
        metadata = absolute.lstat()
    except FileNotFoundError as error:
        raise MigrationError(f"SD root does not exist: {absolute}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MigrationError(f"SD root must be an existing nonsymlink directory: {absolute}")
    return absolute.resolve()


def _validate_name(name: str, description: str) -> None:
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in name)
    ):
        raise MigrationError(f"unsafe {description} name: {name!r}")


def _case_safe_child(parent: Path, name: str, *, description: str) -> Path:
    _validate_name(name, description)
    try:
        metadata = parent.lstat()
    except FileNotFoundError:
        return parent / name
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MigrationError(f"{description} parent must be a nonsymlink directory: {parent}")
    try:
        matches = sorted(
            entry.name for entry in os.scandir(parent) if entry.name.casefold() == name.casefold()
        )
    except OSError as error:
        raise MigrationError(f"cannot inspect {description} parent {parent}: {error}") from error
    if len(matches) > 1 or (matches and matches[0] != name):
        observed = matches[0] if matches else name
        raise MigrationError(f"case-colliding {description} path: {parent / observed}")
    return parent / name


def _path_below(root: Path, relative: PurePosixPath, *, description: str) -> Path:
    current = root
    parts = relative.parts
    for index, component in enumerate(parts):
        current = _case_safe_child(current, component, description=description)
        if current.is_symlink():
            raise MigrationError(f"{description} path contains a symlink: {current}")
        if current.exists() and index < len(parts) - 1:
            try:
                metadata = current.lstat()
            except OSError as error:
                raise MigrationError(f"cannot inspect {description} path {current}: {error}") from error
            if not stat.S_ISDIR(metadata.st_mode):
                raise MigrationError(f"{description} parent is not a directory: {current}")
    try:
        current.relative_to(root)
    except ValueError as error:
        raise MigrationError(f"{description} path escaped SD root: {relative}") from error
    return current


def _read_plain_file(path: Path, *, description: str, maximum: int) -> bytes:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise MigrationError(f"missing {description}: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MigrationError(f"{description} must be a regular nonsymlink file: {path}")
    if metadata.st_size > maximum:
        raise MigrationError(f"{description} exceeds {maximum} bytes: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise MigrationError(f"cannot open {description} {path}: {error}") from error
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise MigrationError(f"{description} changed while opening: {path}")
        payload = bytearray()
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > maximum:
                raise MigrationError(f"{description} grew beyond {maximum} bytes: {path}")
        final = os.fstat(descriptor)
        if final.st_size != len(payload):
            raise MigrationError(f"{description} changed while reading: {path}")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise MigrationError(f"non-standard JSON constant: {value}")


def _is_filesystem_metadata(name: str) -> bool:
    """Return whether a path component is macOS filesystem metadata."""

    return name in MACOS_FILESYSTEM_METADATA or name.startswith("._")


def _validate_json(payload: bytes, source: PurePosixPath) -> None:
    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_object,
            parse_constant=_invalid_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise MigrationError(f"invalid JSON in {source}: {error}") from error
    if not isinstance(document, dict):
        raise MigrationError(f"Pocket JSON must contain a top-level object: {source}")


def _relative(*parts: str) -> PurePosixPath:
    return PurePosixPath(*parts)


def _collect_eeprom_files(root: Path) -> list[MigrationFile]:
    source_base = _relative("Saves", PLATFORM_ID, SOURCE_CORE_ID)
    source_directory = _path_below(root, source_base, description="source save")
    try:
        metadata = source_directory.lstat()
    except FileNotFoundError as error:
        raise MigrationError(f"source save namespace does not exist: {source_directory}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MigrationError(
            f"source save namespace must be a nonsymlink directory: {source_directory}"
        )

    result: list[MigrationFile] = []
    for filename, exact_size in EEPROM_FILES:
        source_relative = source_base / filename
        source = _path_below(root, source_relative, description="source EEPROM")
        payload = _read_plain_file(
            source, description=f"source {filename}", maximum=exact_size
        )
        if len(payload) != exact_size:
            raise MigrationError(
                f"source {filename} must be exactly {exact_size} bytes, got {len(payload)}"
            )
        result.append(
            MigrationFile(
                source=source_relative,
                destination=_relative("Saves", PLATFORM_ID, DESTINATION_CORE_ID, filename),
                payload=payload,
                kind="console EEPROM",
            )
        )
    return result


def _walk_json_tree(
    root: Path,
    namespace: str,
    source_directory: Path,
) -> list[MigrationFile]:
    files: list[MigrationFile] = []
    total_bytes = 0
    entry_count = 0
    source_base = _relative(namespace, SOURCE_CORE_ID)
    destination_base = _relative(namespace, DESTINATION_CORE_ID)

    def walk(directory: Path, relative: PurePosixPath, depth: int) -> None:
        nonlocal total_bytes, entry_count
        if depth > MAX_JSON_DEPTH:
            raise MigrationError(
                f"{namespace} JSON tree exceeds maximum depth {MAX_JSON_DEPTH}: {relative}"
            )
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise MigrationError(f"cannot inspect {namespace} tree {directory}: {error}") from error
        for entry in entries:
            # macOS writes AppleDouble ``._*`` sidecars and ``.DS_Store`` onto
            # FAT-family media. They are filesystem metadata, not Pocket JSON,
            # and an ignored directory component excludes its complete subtree.
            if _is_filesystem_metadata(entry.name):
                continue
            entry_count += 1
            if entry_count > MAX_TREE_ENTRIES:
                raise MigrationError(
                    f"{namespace} tree exceeds {MAX_TREE_ENTRIES} entries"
                )
            _validate_name(entry.name, f"{namespace} entry")
            entry_relative = relative / entry.name
            entry_path = directory / entry.name
            if entry.is_symlink():
                raise MigrationError(f"{namespace} tree contains a symlink: {entry_path}")
            if entry.is_dir(follow_symlinks=False):
                walk(entry_path, entry_relative, depth + 1)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise MigrationError(
                    f"{namespace} tree contains a non-regular entry: {entry_path}"
                )
            if not entry.name.endswith(".json"):
                continue
            if len(files) >= MAX_JSON_FILES:
                raise MigrationError(
                    f"JSON migration exceeds {MAX_JSON_FILES} files"
                )
            payload = _read_plain_file(
                entry_path,
                description=f"{namespace} JSON",
                maximum=MAX_JSON_FILE_BYTES,
            )
            total_bytes += len(payload)
            if total_bytes > MAX_JSON_TOTAL_BYTES:
                raise MigrationError(
                    f"{namespace} JSON exceeds {MAX_JSON_TOTAL_BYTES} total bytes"
                )
            source_relative = source_base / entry_relative
            _validate_json(payload, source_relative)
            files.append(
                MigrationFile(
                    source=source_relative,
                    destination=destination_base / entry_relative,
                    payload=payload,
                    kind=f"{namespace} JSON",
                )
            )

    walk(source_directory, PurePosixPath(), 0)
    return files


def _collect_json_files(root: Path) -> list[MigrationFile]:
    result: list[MigrationFile] = []
    for namespace in JSON_NAMESPACES:
        source_relative = _relative(namespace, SOURCE_CORE_ID)
        source = _path_below(root, source_relative, description=f"source {namespace}")
        if not source.exists():
            continue
        metadata = source.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise MigrationError(
                f"source {namespace} namespace must be a nonsymlink directory: {source}"
            )
        result.extend(_walk_json_tree(root, namespace, source))
        if len(result) > MAX_JSON_FILES:
            raise MigrationError(f"JSON migration exceeds {MAX_JSON_FILES} files")
        if sum(len(managed.payload) for managed in result) > MAX_JSON_TOTAL_BYTES:
            raise MigrationError(
                f"JSON migration exceeds {MAX_JSON_TOTAL_BYTES} total bytes"
            )
    return result


def _destination_state(root: Path, managed: MigrationFile) -> str:
    destination = _path_below(
        root, managed.destination, description="destination namespace"
    )
    if not destination.exists():
        return "copy"
    metadata = destination.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MigrationError(
            f"destination file must be a regular nonsymlink file: {destination}"
        )
    if metadata.st_size != len(managed.payload):
        raise MigrationError(
            f"destination differs; refusing to overwrite: {managed.destination}"
        )
    payload = _read_plain_file(
        destination,
        description="destination file",
        maximum=len(managed.payload),
    )
    if payload != managed.payload:
        raise MigrationError(
            f"destination differs; refusing to overwrite: {managed.destination}"
        )
    return "identical"


def plan_migration(sd_root: Path) -> MigrationPlan:
    """Validate source/destination trees and return a read-only copy plan."""

    root = _root(sd_root)
    files = tuple(
        sorted(
            (*_collect_eeprom_files(root), *_collect_json_files(root)),
            key=lambda item: item.destination.as_posix(),
        )
    )
    if len({managed.destination for managed in files}) != len(files):
        raise MigrationError("migration plan contains duplicate destination paths")
    folded_destinations = [
        managed.destination.as_posix().casefold() for managed in files
    ]
    if len(set(folded_destinations)) != len(folded_destinations):
        raise MigrationError("migration plan contains case-colliding destination paths")
    copies: list[PurePosixPath] = []
    identical: list[PurePosixPath] = []
    for managed in files:
        state = _destination_state(root, managed)
        (copies if state == "copy" else identical).append(managed.destination)
    return MigrationPlan(
        root=root,
        files=files,
        copies=tuple(copies),
        identical=tuple(identical),
    )


def _ensure_destination_parent(root: Path, relative: PurePosixPath) -> Path:
    current = root
    for component in relative.parts[:-1]:
        candidate = _case_safe_child(
            current, component, description="destination namespace"
        )
        if candidate.exists() or candidate.is_symlink():
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise MigrationError(
                    f"destination parent must be a nonsymlink directory: {candidate}"
                )
        else:
            try:
                candidate.mkdir(mode=0o755)
            except FileExistsError:
                pass
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise MigrationError(
                    f"destination parent changed while creating it: {candidate}"
                )
        current = candidate
    return current / relative.name


def _install_atomic_no_replace(source: Path, destination: Path) -> None:
    """Atomically install a complete file without replacing an existing name."""

    unsupported = {errno.ENOSYS, errno.EINVAL}
    for name in ("ENOTSUP", "EOPNOTSUPP"):
        value = getattr(errno, name, None)
        if value is not None:
            unsupported.add(value)

    libc = ctypes.CDLL(None, use_errno=True)
    result: int | None = None
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        renamex_np = libc.renamex_np
        renamex_np.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        renamex_np.restype = ctypes.c_int
        result = renamex_np(os.fsencode(source), os.fsencode(destination), 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        renameat2 = libc.renameat2
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            0x00000001,
        )

    if result == 0:
        return
    if result == -1:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise MigrationError(
                f"destination appeared before atomic no-clobber copy: {destination}"
            )
        if error_number not in unsupported:
            raise OSError(
                error_number,
                os.strerror(error_number),
                str(destination),
            )

    # A hard-link install has the same atomic/no-replace property and is a safe
    # fallback on filesystems that support links but not the native rename flag.
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as error:
        raise MigrationError(
            f"destination appeared before atomic no-clobber copy: {destination}"
        ) from error
    except OSError as error:
        raise MigrationError(
            "destination filesystem does not support an atomic no-clobber "
            f"install: {destination} ({error})"
        ) from error


def _atomic_write_new(destination: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        _install_atomic_no_replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _file_identity(managed: MigrationFile) -> tuple[str, str, bytes, str]:
    return (
        managed.source.as_posix(),
        managed.destination.as_posix(),
        managed.payload,
        managed.kind,
    )


def apply_migration(plan: MigrationPlan) -> MigrationResult:
    """Revalidate and apply a plan without overwriting any differing file."""

    root = _root(plan.root)
    if root != plan.root:
        raise MigrationError("SD root identity changed after planning")
    current = plan_migration(root)
    if tuple(map(_file_identity, current.files)) != tuple(map(_file_identity, plan.files)):
        raise MigrationError("migration source changed after planning")

    copied: list[PurePosixPath] = []
    identical: list[PurePosixPath] = []
    # plan_migration has already preflighted every destination. Recheck each
    # path immediately before its exclusive copy to catch ordinary media changes.
    for managed in current.files:
        state = _destination_state(root, managed)
        if state == "identical":
            identical.append(managed.destination)
            continue
        destination = _ensure_destination_parent(root, managed.destination)
        state = _destination_state(root, managed)
        if state == "identical":
            identical.append(managed.destination)
            continue
        _atomic_write_new(destination, managed.payload)
        written = _read_plain_file(
            destination,
            description="copied destination file",
            maximum=max(len(managed.payload), 1),
        )
        if written != managed.payload:
            raise MigrationError(f"copied file verification failed: {managed.destination}")
        copied.append(managed.destination)
    return MigrationResult(copied=tuple(copied), identical=tuple(identical))


def _summary(
    plan: MigrationPlan,
    *,
    result: MigrationResult | None,
) -> str:
    applied = result is not None
    copies = result.copied if result is not None else plan.copies
    identical = result.identical if result is not None else plan.identical
    lines = [
        "APPLIED" if applied else "VALIDATED ONLY — no files written",
        f"SD root: {plan.root}",
        f"Namespace: {SOURCE_CORE_ID} -> {DESTINATION_CORE_ID}",
        f"Files: {len(copies)} {'copied' if applied else 'to copy'}, {len(identical)} identical",
    ]
    copy_set = set(copies)
    for managed in plan.files:
        action = "COPY" if managed.destination in copy_set else "IDENTICAL"
        lines.append(
            f"{action} {managed.source} -> {managed.destination} "
            f"({len(managed.payload)} bytes, SHA-256 {managed.sha256})"
        )
    lines.append(
        "Excluded by design: Memories, Saves/wonderswan/common cartridge saves, "
        "and non-JSON Settings/Presets files."
    )
    if not applied:
        lines.append("Next: review this plan, then rerun with --apply to copy new files.")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            f"Copy safe Pocket user data from {SOURCE_CORE_ID} to "
            f"{DESTINATION_CORE_ID}. The default is a read-only plan."
        )
    )
    parser.add_argument("--sd-root", required=True, type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the validated no-clobber copies",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        plan = plan_migration(arguments.sd_root)
        result = apply_migration(plan) if arguments.apply else None
        print(_summary(plan, result=result))
        return 0
    except (MigrationError, OSError) as error:
        print(f"migrate_swan_song_namespace.py: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
