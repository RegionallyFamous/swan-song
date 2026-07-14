#!/usr/bin/env python3
"""Safely import owner-supplied WonderSwan ZIPs into the local private lab.

Dry-run is the default.  ROM/BIOS bytes are read only on this machine and are
written only below run_private_corpus.py's private lab root after ``--apply``.
Reports contain secret-keyed identities, never source paths, titles, or raw
content hashes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Any, Sequence
import zipfile

import run_private_corpus as corpus


IMPORT_SCHEMA = "SWAN_SONG_PRIVATE_CORPUS_IMPORT_V1"
REPORT_NAME = "corpus-import.json"
MAX_ARCHIVE_SIZE = 32 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 64
MAX_EXPANSION_RATIO = 1000
SUPPORTED_COMPRESSION = frozenset((zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED))
ROM_SUFFIXES = frozenset((".ws", ".wsc"))
BIOS_SPECS = {
    "bios-mono": ("mono", 4096, "bw.rom"),
    "bios-color": ("color", 8192, "color.rom"),
}


class ImportError(RuntimeError):
    """An expected path-free importer error."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SourceArchive:
    path: Path
    source_id: str


@dataclass(frozen=True)
class ImportCandidate:
    source: SourceArchive
    source_token: str
    case_id: str
    kind: str
    model: str
    size: int
    destination_name: str


@dataclass(frozen=True)
class ScanResult:
    candidates: tuple[ImportCandidate, ...]
    cases: tuple[dict[str, Any], ...]
    archives_discovered: int
    archives_selected: int
    duplicate_roms: int
    ignored_non_archives: int


def _source_id(key: bytes, root_index: int, relative: str) -> str:
    payload = root_index.to_bytes(8, "big") + b"\0" + relative.encode(
        "utf-8", "surrogateescape"
    )
    return "archive-" + corpus._opaque_bytes(key, b"import-source-path", payload)


def _archive_token(key: bytes, data: bytes) -> str:
    return "source-" + corpus._opaque_bytes(key, b"import-source-archive", data)


def _read_archive(path: Path) -> bytes:
    try:
        return corpus._read_regular(path, maximum=MAX_ARCHIVE_SIZE)
    except corpus.CorpusError as error:
        mapping = {
            "missing_input": "source_missing",
            "input_not_regular": "source_not_regular",
            "input_too_large": "archive_compressed_too_large",
            "input_changed_during_read": "source_changed_during_read",
        }
        raise ImportError(mapping.get(error.code, "source_read_failed")) from error


def _normalized_member_name(info: zipfile.ZipInfo) -> str:
    original = info.orig_filename
    name = info.filename
    if not original or "\x00" in original or not name or "\x00" in name:
        raise ImportError("archive_member_name_invalid")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ImportError("archive_member_traversal")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ImportError("archive_member_traversal")
    return "/".join(parts)


def _member_is_regular(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    if info.is_dir():
        if kind not in (0, stat.S_IFDIR):
            raise ImportError("archive_member_not_regular")
        return False
    if kind not in (0, stat.S_IFREG):
        raise ImportError(
            "archive_member_symlink" if kind == stat.S_IFLNK else "archive_member_not_regular"
        )
    return True


def _validated_regular_member(
    body: bytes, *, maximum_expanded: int, required_suffixes: frozenset[str] | None
) -> tuple[zipfile.ZipFile, zipfile.ZipInfo]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(body), "r")
        infos = archive.infolist()
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise ImportError("archive_invalid") from error
    try:
        if not infos or len(infos) > MAX_ARCHIVE_ENTRIES:
            raise ImportError("archive_entry_count_unsafe")
        regular: list[zipfile.ZipInfo] = []
        names: set[str] = set()
        expanded = 0
        for info in infos:
            name = _normalized_member_name(info)
            folded = name.casefold()
            if folded in names:
                raise ImportError("archive_member_name_duplicate")
            names.add(folded)
            if info.flag_bits & 0x1:
                raise ImportError("archive_encrypted")
            if info.compress_type not in SUPPORTED_COMPRESSION:
                raise ImportError("archive_compression_unsupported")
            if info.file_size < 0 or info.compress_size < 0:
                raise ImportError("archive_size_invalid")
            expanded += info.file_size
            if info.file_size and (
                info.compress_size == 0
                or info.file_size > info.compress_size * MAX_EXPANSION_RATIO
            ):
                raise ImportError("archive_expansion_ratio_unsafe")
            if _member_is_regular(info):
                regular.append(info)
        if len(regular) != 1:
            reason = (
                "archive_multi_rom"
                if required_suffixes is not None
                else "archive_member_count_invalid"
            )
            raise ImportError(reason)
        if expanded > maximum_expanded:
            raise ImportError("archive_expansion_too_large")
        selected = regular[0]
        if required_suffixes is not None:
            suffix = PurePosixPath(selected.filename.replace("\\", "/")).suffix.lower()
            if suffix not in required_suffixes:
                raise ImportError("archive_rom_member_missing")
        return archive, selected
    except Exception:
        archive.close()
        raise


def _read_member(
    body: bytes, *, maximum_expanded: int, required_suffixes: frozenset[str] | None
) -> bytes:
    archive, info = _validated_regular_member(
        body, maximum_expanded=maximum_expanded, required_suffixes=required_suffixes
    )
    try:
        try:
            with archive.open(info, "r") as stream:
                data = stream.read(maximum_expanded + 1)
                overflow = stream.read(1)
        except (EOFError, OSError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
            code = "archive_encrypted" if info.flag_bits & 0x1 else "archive_member_read_failed"
            raise ImportError(code) from error
    finally:
        archive.close()
    if overflow or len(data) > maximum_expanded:
        raise ImportError("archive_expansion_too_large")
    if len(data) != info.file_size:
        raise ImportError("archive_member_size_mismatch")
    return data


def _inspect_rom(source: SourceArchive, key: bytes) -> tuple[ImportCandidate, bytes]:
    archive_body = _read_archive(source.path)
    token = _archive_token(key, archive_body)
    try:
        rom = _read_member(
            archive_body,
            maximum_expanded=corpus.MAX_ROM_SIZE,
            required_suffixes=ROM_SUFFIXES,
        )
        case_id, model, _save_type, _mapper, _rtc = corpus.inspect_rom_bytes(rom, key)
    except corpus.CorpusError as error:
        raise ImportError(error.code) from error
    suffix = ".wsc" if model == "color" else ".ws"
    return (
        ImportCandidate(
            source=source,
            source_token=token,
            case_id=case_id,
            kind="rom",
            model=model,
            size=len(rom),
            destination_name=case_id + suffix,
        ),
        rom,
    )


def _inspect_bios(
    source: SourceArchive, key: bytes, kind: str
) -> tuple[ImportCandidate, bytes]:
    model, exact_size, destination = BIOS_SPECS[kind]
    archive_body = _read_archive(source.path)
    token = _archive_token(key, archive_body)
    bios = _read_member(
        archive_body, maximum_expanded=exact_size, required_suffixes=None
    )
    if len(bios) != exact_size:
        raise ImportError("bios_wrong_size")
    case_id = "bios-" + corpus._opaque_bytes(
        key, b"bios-" + model.encode("ascii"), bios
    )
    return (
        ImportCandidate(
            source=source,
            source_token=token,
            case_id=case_id,
            kind=kind,
            model=model,
            size=len(bios),
            destination_name=destination,
        ),
        bios,
    )


def _discover_root(
    path: Path, key: bytes, root_index: int
) -> tuple[list[SourceArchive], list[dict[str, Any]], int]:
    archives: list[SourceArchive] = []
    rejections: list[dict[str, Any]] = []
    ignored = 0
    absolute = path.expanduser().absolute()

    def reject(relative: str, reason: str) -> None:
        rejections.append(
            {
                "case_id": _source_id(key, root_index, relative),
                "kind": "source",
                "status": "rejected",
                "reason": reason,
            }
        )

    def visit(current: Path, relative: str) -> None:
        nonlocal ignored
        try:
            info = current.lstat()
        except OSError:
            reject(relative, "source_stat_failed")
            return
        if stat.S_ISLNK(info.st_mode):
            reject(relative, "source_symlink_forbidden")
            return
        if stat.S_ISREG(info.st_mode):
            if current.suffix.lower() == ".zip":
                archives.append(
                    SourceArchive(current, _source_id(key, root_index, relative))
                )
            else:
                ignored += 1
            return
        if not stat.S_ISDIR(info.st_mode):
            reject(relative, "source_not_regular")
            return
        try:
            entries = sorted(os.scandir(current), key=lambda item: item.name.casefold())
        except OSError:
            reject(relative, "source_directory_unreadable")
            return
        for entry in entries:
            if corpus._is_ignored_macos_metadata(entry.name):
                ignored += 1
                continue
            child_relative = entry.name if relative == "." else f"{relative}/{entry.name}"
            visit(Path(entry.path), child_relative)

    visit(absolute, ".")
    return archives, rejections, ignored


def _matches_selection(path: Path, includes: Sequence[str], excludes: Sequence[str]) -> bool:
    haystack = path.as_posix().casefold()
    return (not includes or any(value.casefold() in haystack for value in includes)) and not any(
        value.casefold() in haystack for value in excludes
    )


def _destination_state(path: Path, expected: bytes) -> str:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "new"
    except OSError as error:
        raise ImportError("destination_stat_failed") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ImportError("destination_not_regular")
    try:
        existing = corpus._read_regular(path, maximum=max(len(expected), 1))
    except corpus.CorpusError as error:
        raise ImportError("destination_read_failed") from error
    if existing != expected:
        raise ImportError("destination_content_conflict")
    return "already_present"


def _rescan(candidate: ImportCandidate, key: bytes) -> bytes:
    if candidate.kind == "rom":
        rescanned, data = _inspect_rom(candidate.source, key)
    else:
        rescanned, data = _inspect_bios(candidate.source, key, candidate.kind)
    if rescanned.source_token != candidate.source_token or rescanned.case_id != candidate.case_id:
        raise ImportError("source_changed_after_scan")
    return data


def _scan(args: argparse.Namespace, key: bytes) -> ScanResult:
    discovered: list[SourceArchive] = []
    cases: list[dict[str, Any]] = []
    ignored = 0
    bios_paths = {
        value.expanduser().absolute()
        for value in (args.bios_mono, args.bios_color)
        if value is not None
    }
    for root_index, root in enumerate(args.sources):
        found, rejected, root_ignored = _discover_root(root, key, root_index)
        discovered.extend(item for item in found if item.path not in bios_paths)
        cases.extend(rejected)
        ignored += root_ignored
    discovered.sort(key=lambda item: item.path.as_posix().casefold())
    selected = [
        item
        for item in discovered
        if _matches_selection(item.path, args.select, args.exclude)
    ]
    if args.limit is not None:
        selected = selected[: args.limit]

    candidates: dict[str, ImportCandidate] = {}
    duplicate_roms = 0
    for source in selected:
        try:
            candidate, _data = _inspect_rom(source, key)
        except ImportError as error:
            cases.append(
                {
                    "case_id": source.source_id,
                    "kind": "rom",
                    "status": "rejected",
                    "reason": error.code,
                }
            )
            continue
        if candidate.case_id in candidates:
            duplicate_roms += 1
            continue
        candidates[candidate.case_id] = candidate

    for kind, path in (("bios-mono", args.bios_mono), ("bios-color", args.bios_color)):
        if path is None:
            continue
        source = SourceArchive(
            path.expanduser().absolute(),
            _source_id(key, len(args.sources) + len(candidates), kind),
        )
        try:
            candidate, _data = _inspect_bios(source, key, kind)
        except ImportError as error:
            cases.append(
                {
                    "case_id": source.source_id,
                    "kind": kind,
                    "status": "rejected",
                    "reason": error.code,
                }
            )
            continue
        candidates[candidate.case_id] = candidate

    return ScanResult(
        candidates=tuple(sorted(candidates.values(), key=lambda item: item.case_id)),
        cases=tuple(cases),
        archives_discovered=len(discovered),
        archives_selected=len(selected),
        duplicate_roms=duplicate_roms,
        ignored_non_archives=ignored,
    )


def _apply_or_plan(
    scan: ScanResult, lab: corpus.LabPaths, key: bytes, apply: bool
) -> tuple[list[dict[str, Any]], int, int]:
    cases = list(scan.cases)
    if any(item["status"] == "rejected" for item in cases):
        return cases, 0, 0
    planned: list[tuple[ImportCandidate, Path]] = []
    already_present = 0
    for candidate in scan.candidates:
        destination_root = lab.roms if candidate.kind == "rom" else lab.bios
        destination = destination_root / candidate.destination_name
        try:
            destination_info = destination.lstat()
        except FileNotFoundError:
            destination_info = None
        except OSError as error:
            cases.append(
                {
                    "case_id": candidate.case_id,
                    "kind": candidate.kind,
                    "status": "rejected",
                    "reason": "destination_stat_failed",
                }
            )
            continue
        try:
            state = (
                _destination_state(destination, _rescan(candidate, key))
                if destination_info is not None
                else "new"
            )
        except ImportError as error:
            cases.append(
                {
                    "case_id": candidate.case_id,
                    "kind": candidate.kind,
                    "status": "rejected",
                    "reason": error.code,
                }
            )
            continue
        if state == "already_present":
            already_present += 1
            cases.append(
                {
                    "case_id": candidate.case_id,
                    "kind": candidate.kind,
                    "model": candidate.model,
                    "size": candidate.size,
                    "status": "already_present",
                }
            )
        else:
            planned.append((candidate, destination))
    if any(item["status"] == "rejected" for item in cases):
        return cases, len(planned), already_present

    status = "would_import"
    if apply and planned:
        linked: list[tuple[Path, os.stat_result]] = []
        try:
            with tempfile.TemporaryDirectory(prefix="import-", dir=lab.work) as temporary_name:
                staging = Path(temporary_name)
                staging.chmod(0o700)
                staged: list[tuple[ImportCandidate, Path, Path]] = []
                for index, (candidate, destination) in enumerate(planned):
                    # A final source pass binds committed bytes to the scan.
                    final_data = _rescan(candidate, key)
                    temporary = staging / f"item-{index:05d}"
                    corpus._write_private_input(temporary, final_data)
                    staged.append((candidate, temporary, destination))
                for _candidate, temporary, destination in staged:
                    try:
                        os.link(temporary, destination, follow_symlinks=False)
                    except FileExistsError as error:
                        raise ImportError("destination_changed_during_apply") from error
                    except OSError as error:
                        raise ImportError("destination_commit_failed") from error
                    linked.append((destination, destination.lstat()))
                for destination, _info in linked:
                    destination.chmod(0o600)
            status = "imported"
        except Exception:
            for destination, committed in reversed(linked):
                try:
                    current = destination.lstat()
                    if current.st_dev == committed.st_dev and current.st_ino == committed.st_ino:
                        destination.unlink()
                except OSError:
                    pass
            raise

    for candidate, _destination in planned:
        cases.append(
            {
                "case_id": candidate.case_id,
                "kind": candidate.kind,
                "model": candidate.model,
                "size": candidate.size,
                "status": status,
            }
        )
    return cases, len(planned), already_present


def _positive_limit(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive decimal integer") from error
    if parsed <= 0 or parsed > 10000:
        raise argparse.ArgumentTypeError("must be within 1..10000")
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Dry-run or import local WonderSwan ZIPs into the private test lab"
    )
    result.add_argument("sources", nargs="+", type=Path, help="ZIP file or directory root")
    result.add_argument("--lab-root", type=Path, default=corpus.DEFAULT_LAB_ROOT)
    result.add_argument(
        "--apply", action="store_true", help="write validated ROM/BIOS bytes to the private lab"
    )
    result.add_argument(
        "--select", action="append", default=[], metavar="TEXT", help="include matching ZIP paths"
    )
    result.add_argument(
        "--exclude", action="append", default=[], metavar="TEXT", help="exclude matching ZIP paths"
    )
    result.add_argument("--limit", type=_positive_limit, help="inspect at most this many ROM ZIPs")
    result.add_argument("--bios-mono", type=Path, help="explicit 4-KiB mono BIOS ZIP")
    result.add_argument("--bios-color", type=Path, help="explicit 8-KiB Color BIOS ZIP")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        lab, _warnings = corpus.initialize_lab(args.lab_root)
        key, _key_warnings = corpus.load_or_create_key(lab.key)
        scan = _scan(args, key)
        cases, planned, already_present = _apply_or_plan(scan, lab, key, args.apply)
        rejected = sum(item["status"] == "rejected" for item in cases)
        imported = sum(item["status"] == "imported" for item in cases)
        document = {
            "schema": IMPORT_SCHEMA,
            "generated_at": corpus._utc_now(),
            "mode": "apply" if args.apply else "dry_run",
            "selection": {
                "include_terms": len(args.select),
                "exclude_terms": len(args.exclude),
                "limit": args.limit,
            },
            "counts": {
                "source_roots": len(args.sources),
                "archives_discovered": scan.archives_discovered,
                "archives_selected": scan.archives_selected,
                "valid_unique_roms": sum(item.kind == "rom" for item in scan.candidates),
                "duplicate_roms": scan.duplicate_roms,
                "bios_images": sum(item.kind != "rom" for item in scan.candidates),
                "ignored_non_archives": scan.ignored_non_archives,
                "planned_new_files": planned,
                "already_present": already_present,
                "imported": imported,
                "rejected": rejected,
            },
            "cases": sorted(cases, key=lambda item: (item["case_id"], item["kind"])),
        }
        corpus._atomic_write_json(lab.reports / REPORT_NAME, document)
        print(json.dumps(document, indent=2, sort_keys=True))
        return int(rejected != 0 or not scan.candidates)
    except (corpus.CorpusError, ImportError) as error:
        code = error.code
        print(f"ERROR: {code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
