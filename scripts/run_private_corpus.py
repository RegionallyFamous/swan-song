#!/usr/bin/env python3
"""Run a privacy-preserving, local-only WonderSwan ROM smoke corpus.

The runner deliberately keeps ROMs, framebuffers, simulator output, and
filesystem paths below a private lab root outside this repository.
Only secret-key HMAC identifiers and coarse results enter its public summary.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAB_ROOT = (
    Path.home() / "Library" / "Application Support" / "Swan Song Test Lab"
)
DEFAULT_SIMULATOR = ROOT / "build" / "sim" / "obj_dir" / "VSwanTop"

INVENTORY_SCHEMA = "SWAN_SONG_PRIVATE_CORPUS_INVENTORY_V1"
RESULT_SCHEMA = "SWAN_SONG_PRIVATE_CORPUS_RESULT_V1"
SUMMARY_SCHEMA = "SWAN_SONG_PRIVATE_CORPUS_SUMMARY_V1"
OPEN_IPL_IDENTITY = "open-bootstrap-v3"
KEY_SIZE = 32
FRAME_SIZE = 224 * 144 * 3
MIN_ROM_SIZE = 64 * 1024
MAX_ROM_SIZE = 16 * 1024 * 1024
BANK_SIZE = 64 * 1024
SUPPORTED_SAVE_TYPES = frozenset((0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x10, 0x20, 0x50))
DECLARED_ROM_SIZES = {
    0x00: 128 * 1024,
    0x01: 256 * 1024,
    0x02: 512 * 1024,
    0x03: 1 * 1024 * 1024,
    0x04: 2 * 1024 * 1024,
    0x05: 3 * 1024 * 1024,
    0x06: 4 * 1024 * 1024,
    0x07: 6 * 1024 * 1024,
    0x08: 8 * 1024 * 1024,
    0x09: 16 * 1024 * 1024,
}


class CorpusError(RuntimeError):
    """An expected fail-closed error represented by a path-free code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LabPaths:
    root: Path
    private: Path
    roms: Path
    work: Path
    results: Path
    reports: Path
    key: Path


@dataclass(frozen=True)
class RomCase:
    path: Path
    case_id: str
    model: str
    save_type: int
    mapper: int
    rtc: bool
    size: int
    open_ipl_variant: str


@dataclass(frozen=True)
class Rejection:
    case_id: str
    reason: str


@dataclass(frozen=True)
class Inventory:
    cases: tuple[RomCase, ...]
    rejections: tuple[Rejection, ...]
    files_seen: int
    duplicates: int
    ignored_filesystem_metadata: int
    permission_warnings: int


@dataclass(frozen=True)
class Attempt:
    status: str
    reason: str
    completed_frames: int
    frame_chain_hmac: str | None


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _opaque_bytes(key: bytes, domain: bytes, data: bytes) -> str:
    digest = hmac.new(key, digestmod=hashlib.sha256)
    digest.update(b"swan-song/private-corpus/v1\0")
    digest.update(domain)
    digest.update(b"\0")
    digest.update(data)
    return digest.hexdigest()


def _rom_id(key: bytes, data: bytes) -> str:
    return "rom-" + _opaque_bytes(key, b"rom", data)


def _rejected_path_id(key: bytes, relative: Path) -> str:
    return "rejected-" + _opaque_bytes(
        key, b"rejected-relative-path", relative.as_posix().encode("utf-8", "surrogateescape")
    )


def _mode_is_broad(mode: int) -> bool:
    return bool(stat.S_IMODE(mode) & 0o077)


def _lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except FileNotFoundError as error:
        raise CorpusError("missing_input") from error
    except OSError as error:
        raise CorpusError("input_stat_failed") from error


def _ensure_private_directory(path: Path) -> bool:
    """Create one managed directory as 0700; return whether an existing mode is broad."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        try:
            path.mkdir(parents=True, mode=0o700)
            path.chmod(0o700)
            return False
        except OSError as error:
            raise CorpusError("private_directory_create_failed") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CorpusError("private_directory_not_real")
    return _mode_is_broad(info.st_mode)


def initialize_lab(root: Path) -> tuple[LabPaths, int]:
    root = root.expanduser().absolute()
    try:
        resolved_root = root.resolve(strict=False)
        resolved_repository = ROOT.resolve(strict=True)
    except OSError as error:
        raise CorpusError("lab_root_resolution_failed") from error
    if resolved_root == resolved_repository or resolved_repository in resolved_root.parents:
        raise CorpusError("lab_root_inside_repository")
    paths = LabPaths(
        root=root,
        private=root / "private",
        roms=root / "private" / "roms",
        work=root / "private" / "work",
        results=root / "private" / "results",
        reports=root / "reports",
        key=root / "private" / "corpus-hmac.key",
    )
    warnings = 0
    for directory in (
        paths.root,
        paths.private,
        paths.roms,
        paths.work,
        paths.results,
        paths.reports,
    ):
        warnings += int(_ensure_private_directory(directory))
    return paths, warnings


def _write_all(fd: int, data: bytes) -> None:
    position = 0
    while position < len(data):
        written = os.write(fd, data[position:])
        if written <= 0:
            raise CorpusError("private_file_write_failed")
        position += written


def load_or_create_key(path: Path) -> tuple[bytes, int]:
    """Return the 32-byte local HMAC key and a broad-mode warning count."""

    try:
        info = path.lstat()
    except FileNotFoundError:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(path, flags, 0o600)
            try:
                _write_all(fd, secrets.token_bytes(KEY_SIZE))
                os.fsync(fd)
            finally:
                os.close(fd)
            path.chmod(0o600)
            info = path.lstat()
        except FileExistsError:
            info = _lstat(path)
        except OSError as error:
            raise CorpusError("key_create_failed") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CorpusError("key_not_regular")
    try:
        data = _read_regular(path, exact_size=KEY_SIZE)
    except CorpusError as error:
        if error.code in {"input_wrong_size", "input_changed_during_read"}:
            raise CorpusError("key_wrong_size") from error
        raise CorpusError("key_read_failed") from error
    return data, int(_mode_is_broad(info.st_mode))


def _read_regular(
    path: Path, *, exact_size: int | None = None, maximum: int | None = None
) -> bytes:
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CorpusError("input_not_regular")
    if exact_size is not None and info.st_size != exact_size:
        raise CorpusError("input_wrong_size")
    if maximum is not None and info.st_size > maximum:
        raise CorpusError("input_too_large")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise CorpusError("input_read_failed") from error
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise CorpusError("input_not_regular")
        if exact_size is not None and opened.st_size != exact_size:
            raise CorpusError("input_wrong_size")
        if maximum is not None and opened.st_size > maximum:
            raise CorpusError("input_too_large")
        limit = exact_size if exact_size is not None else maximum
        if limit is None:
            limit = opened.st_size
        body = bytearray()
        while len(body) <= limit:
            block = os.read(fd, min(1024 * 1024, limit + 1 - len(body)))
            if not block:
                break
            body.extend(block)
        closed_size = os.fstat(fd).st_size
    except OSError as error:
        raise CorpusError("input_read_failed") from error
    finally:
        os.close(fd)
    if len(body) > limit:
        raise CorpusError("input_too_large")
    if opened.st_size != closed_size or len(body) != opened.st_size:
        raise CorpusError("input_changed_during_read")
    return bytes(body)


def _next_power_of_two(value: int) -> int:
    return 1 << (value - 1).bit_length()


def inspect_rom_bytes(data: bytes, key: bytes) -> tuple[str, str, int, int, bool]:
    """Validate one image and return opaque ID, model, save type, mapper, RTC."""

    case_id = _rom_id(key, data)
    size = len(data)
    if size < MIN_ROM_SIZE or size > MAX_ROM_SIZE:
        raise CorpusError("rom_size_unsupported")
    if size % BANK_SIZE:
        raise CorpusError("rom_not_bank_aligned")

    footer = data[-16:]
    if footer[0] != 0xEA:
        raise CorpusError("rom_footer_entry_invalid")
    if footer[5] & 0x0F:
        raise CorpusError("rom_footer_maintenance_invalid")
    if footer[7] not in (0, 1):
        raise CorpusError("rom_footer_color_invalid")
    if footer[11] not in SUPPORTED_SAVE_TYPES:
        raise CorpusError("rom_footer_save_unsupported")
    if footer[13] not in (0, 1):
        raise CorpusError("rom_footer_mapper_unsupported")
    if footer[10] not in DECLARED_ROM_SIZES:
        raise CorpusError("rom_footer_size_unsupported")

    stored_checksum = footer[14] | (footer[15] << 8)
    if (sum(data[:-2]) & 0xFFFF) != stored_checksum:
        raise CorpusError("rom_footer_checksum_invalid")

    is_power_of_two = size & (size - 1) == 0
    if not is_power_of_two:
        declared = DECLARED_ROM_SIZES.get(footer[10])
        aperture = _next_power_of_two(size)
        if declared is None or declared not in (size, aperture):
            raise CorpusError("rom_footer_size_mismatch")
        if aperture > MAX_ROM_SIZE:
            raise CorpusError("rom_mapper_aperture_unsupported")

    model = "color" if footer[7] == 1 else "mono"
    mapper = footer[13]
    return case_id, model, footer[11], mapper, mapper == 1


def inspect_rom(path: Path, key: bytes) -> tuple[RomCase, bytes]:
    data = _read_regular(path, maximum=MAX_ROM_SIZE)
    case_id, model, save_type, mapper, rtc = inspect_rom_bytes(data, key)
    footer = data[-16:]
    word_width = bool(footer[12] & 0x04)
    protect_owner_area = not bool(footer[9] & 0x80)
    variant = (
        f"{model}-{'word16' if word_width else 'word8'}-"
        f"owner-{'protected' if protect_owner_area else 'writable'}"
    )
    return RomCase(
        path, case_id, model, save_type, mapper, rtc, len(data), variant
    ), data


def _is_ignored_macos_metadata(name: str) -> bool:
    """Return whether Finder may have created this path component."""

    return name == ".DS_Store" or name.startswith("._")


def _walk_rom_tree(
    root: Path, key: bytes, initial_permission_warnings: int
) -> Inventory:
    cases: dict[str, RomCase] = {}
    rejections: list[Rejection] = []
    files_seen = 0
    duplicates = 0
    ignored_filesystem_metadata = 0
    permission_warnings = initial_permission_warnings

    def reject(relative: Path, reason: str, data: bytes | None = None) -> None:
        case_id = _rom_id(key, data) if data is not None else _rejected_path_id(key, relative)
        rejections.append(Rejection(case_id, reason))

    def visit(directory: Path, relative_directory: Path) -> None:
        nonlocal files_seen, duplicates, ignored_filesystem_metadata, permission_warnings
        info = _lstat(directory)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            reject(relative_directory, "rom_directory_not_real")
            return
        if relative_directory != Path(".") and _mode_is_broad(info.st_mode):
            permission_warnings += 1
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError:
            reject(relative_directory, "rom_directory_unreadable")
            return
        for entry in entries:
            relative = relative_directory / entry.name
            if _is_ignored_macos_metadata(entry.name):
                ignored_filesystem_metadata += 1
                continue
            try:
                entry_info = entry.stat(follow_symlinks=False)
            except OSError:
                reject(relative, "rom_entry_unreadable")
                continue
            if stat.S_ISLNK(entry_info.st_mode):
                files_seen += 1
                reject(relative, "rom_symlink_forbidden")
                continue
            if stat.S_ISDIR(entry_info.st_mode):
                visit(Path(entry.path), relative)
                continue
            files_seen += 1
            if not stat.S_ISREG(entry_info.st_mode):
                reject(relative, "rom_special_file_forbidden")
                continue
            if Path(entry.name).suffix.lower() not in (".ws", ".wsc"):
                reject(relative, "rom_extension_unsupported")
                continue
            if entry_info.st_size < MIN_ROM_SIZE or entry_info.st_size > MAX_ROM_SIZE:
                reject(relative, "rom_size_unsupported")
                continue
            try:
                case, data = inspect_rom(Path(entry.path), key)
            except CorpusError as error:
                try:
                    data = _read_regular(Path(entry.path), maximum=MAX_ROM_SIZE)
                except CorpusError:
                    data = None
                reject(relative, error.code, data)
                continue
            if _mode_is_broad(entry_info.st_mode):
                permission_warnings += 1
            if case.case_id in cases:
                duplicates += 1
            else:
                cases[case.case_id] = case

    visit(root, Path("."))
    return Inventory(
        tuple(sorted(cases.values(), key=lambda item: item.case_id)),
        tuple(sorted(rejections, key=lambda item: (item.case_id, item.reason))),
        files_seen,
        duplicates,
        ignored_filesystem_metadata,
        permission_warnings,
    )


def _atomic_write_json(path: Path, document: Any) -> None:
    if path.is_symlink():
        raise CorpusError("output_symlink_forbidden")
    payload = (
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        raise CorpusError("atomic_output_failed") from error


def _write_private_input(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as error:
        raise CorpusError("private_input_copy_failed") from error


def _validate_simulator(path: Path) -> tuple[Path, str]:
    path = path.expanduser().absolute()
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CorpusError("simulator_not_regular")
    if not os.access(path, os.X_OK):
        raise CorpusError("simulator_not_executable")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise CorpusError("simulator_read_failed") from error
    return path, digest.hexdigest()


def _run_process(argv: Sequence[str], cwd: Path, timeout: float) -> tuple[str, int | None]:
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return "simulator_launch_failed", None
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        return "simulator_timeout", None
    if return_code != 0:
        return "simulator_exit_nonzero", return_code
    return "pass", 0


def _frame_chain(output: Path, frames: int, key: bytes) -> tuple[str, int]:
    expected = {f"frame-{index}.rgb" for index in range(frames)}
    try:
        entries = list(output.iterdir())
    except OSError as error:
        raise CorpusError("frame_output_unreadable") from error
    if {entry.name for entry in entries} != expected:
        raise CorpusError("frame_output_set_invalid")
    digest = hmac.new(key, digestmod=hashlib.sha256)
    digest.update(b"swan-song/private-corpus/frame-chain/v1\0")
    for index in range(frames):
        path = output / f"frame-{index}.rgb"
        info = _lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise CorpusError("frame_output_not_regular")
        if info.st_size != FRAME_SIZE:
            raise CorpusError("frame_output_wrong_size")
        data = _read_regular(path, exact_size=FRAME_SIZE)
        digest.update(index.to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest(), frames


def _run_attempt(
    case: RomCase,
    rom_data: bytes,
    simulator: Path,
    lab: LabPaths,
    key: bytes,
    frames: int,
    max_cycles: int,
    wall_timeout: float,
) -> Attempt:
    try:
        with tempfile.TemporaryDirectory(
            prefix=f"case-{case.case_id[4:16]}-", dir=lab.work
        ) as temporary_name:
            temporary = Path(temporary_name)
            temporary.chmod(0o700)
            rom_path = temporary / ("cartridge.wsc" if case.model == "color" else "cartridge.ws")
            output = temporary / "frames"
            output.mkdir(mode=0o700)
            _write_private_input(rom_path, rom_data)
            reason, _return_code = _run_process(
                (
                    str(simulator),
                    "--rom",
                    str(rom_path),
                    "--frames",
                    str(frames),
                    "--max-cycles",
                    str(max_cycles),
                    "--out",
                    str(output),
                ),
                temporary,
                wall_timeout,
            )
            if reason != "pass":
                return Attempt("fail", reason, 0, None)
            try:
                frame_hmac, completed = _frame_chain(output, frames, key)
            except CorpusError as error:
                return Attempt("fail", error.code, 0, None)
            return Attempt("pass", "pass", completed, frame_hmac)
    except CorpusError as error:
        return Attempt("fail", error.code, 0, None)
    except OSError:
        return Attempt("fail", "private_work_failed", 0, None)


def _load_resume(
    path: Path,
    case_id: str,
    contract_id: str,
    frames: int,
    repeat: bool,
) -> dict[str, Any] | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
        raise CorpusError("resume_invalid")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorpusError("resume_invalid") from error
    required = {
        "schema",
        "case_id",
        "contract_id",
        "status",
        "reason",
        "attempts",
        "completed_frames",
        "deterministic_pair",
        "frame_chain_hmac",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise CorpusError("resume_invalid")
    if (
        document["schema"] != RESULT_SCHEMA
        or document["case_id"] != case_id
        or document["contract_id"] != contract_id
    ):
        return None
    if document["status"] == "pass" and document["reason"] == "pass":
        expected_attempts = 2 if repeat else 1
        expected_determinism = True if repeat else None
        frame_hmac = document["frame_chain_hmac"]
        if (
            type(document["attempts"]) is not int
            or document["attempts"] != expected_attempts
            or type(document["completed_frames"]) is not int
            or document["completed_frames"] != frames
            or document["deterministic_pair"] is not expected_determinism
            or not isinstance(frame_hmac, str)
            or len(frame_hmac) != 64
            or any(character not in "0123456789abcdef" for character in frame_hmac)
        ):
            raise CorpusError("resume_invalid")
        return document
    if not isinstance(document["reason"], str) or not document["reason"].replace("_", "").isalnum():
        raise CorpusError("resume_invalid")
    return None


def _public_case_result(document: dict[str, Any], resumed: bool) -> dict[str, Any]:
    return {
        "case_id": document["case_id"],
        "status": document["status"],
        "reason": document["reason"],
        "attempts": document["attempts"],
        "completed_frames": document["completed_frames"],
        "deterministic_pair": document["deterministic_pair"],
        "frame_chain_hmac": document["frame_chain_hmac"],
        "resumed": resumed,
    }


def _execute_case(
    case: RomCase,
    simulator: Path,
    lab: LabPaths,
    key: bytes,
    contract_id: str,
    frames: int,
    max_cycles: int,
    wall_timeout: float,
    repeat: bool,
) -> dict[str, Any]:
    result_path = lab.results / f"{case.case_id}.json"
    try:
        resumed = _load_resume(
            result_path, case.case_id, contract_id, frames, repeat
        )
    except CorpusError:
        return {
            "case_id": case.case_id,
            "status": "fail",
            "reason": "resume_invalid",
            "attempts": 0,
            "completed_frames": 0,
            "deterministic_pair": None,
            "frame_chain_hmac": None,
            "resumed": False,
        }
    if resumed is not None:
        return _public_case_result(resumed, True)

    try:
        current, rom_data = inspect_rom(case.path, key)
        if current.case_id != case.case_id or current.model != case.model:
            raise CorpusError("rom_changed_after_inventory")
    except CorpusError as error:
        document = {
            "schema": RESULT_SCHEMA,
            "case_id": case.case_id,
            "contract_id": contract_id,
            "status": "fail",
            "reason": error.code,
            "attempts": 0,
            "completed_frames": 0,
            "deterministic_pair": None,
            "frame_chain_hmac": None,
        }
        _atomic_write_json(result_path, document)
        return _public_case_result(document, False)

    first = _run_attempt(
        case,
        rom_data,
        simulator,
        lab,
        key,
        frames,
        max_cycles,
        wall_timeout,
    )
    attempts = 1
    deterministic_pair: bool | None = None
    final = first
    if first.status == "pass" and repeat:
        second = _run_attempt(
            case,
            rom_data,
            simulator,
            lab,
            key,
            frames,
            max_cycles,
            wall_timeout,
        )
        attempts = 2
        if second.status != "pass":
            final = second
        elif second.frame_chain_hmac != first.frame_chain_hmac:
            final = Attempt("fail", "frame_output_nondeterministic", frames, None)
            deterministic_pair = False
        else:
            deterministic_pair = True

    document = {
        "schema": RESULT_SCHEMA,
        "case_id": case.case_id,
        "contract_id": contract_id,
        "status": final.status,
        "reason": final.reason,
        "attempts": attempts,
        "completed_frames": final.completed_frames,
        "deterministic_pair": deterministic_pair,
        "frame_chain_hmac": final.frame_chain_hmac if final.status == "pass" else None,
    }
    _atomic_write_json(result_path, document)
    return _public_case_result(document, False)


def _inventory_document(
    inventory: Inventory,
    permission_warnings: int,
) -> dict[str, Any]:
    model_counts = {"mono": 0, "color": 0}
    save_type_counts: dict[str, int] = {}
    rtc_count = 0
    for case in inventory.cases:
        model_counts[case.model] += 1
        save_key = f"0x{case.save_type:02x}"
        save_type_counts[save_key] = save_type_counts.get(save_key, 0) + 1
        rtc_count += int(case.rtc)
    return {
        "schema": INVENTORY_SCHEMA,
        "generated_at": _utc_now(),
        "open_ipl": {
            "identity": OPEN_IPL_IDENTITY,
            "variants": sorted({case.open_ipl_variant for case in inventory.cases}),
        },
        "counts": {
            "files_seen": inventory.files_seen,
            "valid_unique_cases": len(inventory.cases),
            "duplicates": inventory.duplicates,
            "rejected": len(inventory.rejections),
            "ignored_filesystem_metadata": inventory.ignored_filesystem_metadata,
            "permission_warnings": permission_warnings,
            "rtc_cases": rtc_count,
        },
        "model_counts": model_counts,
        "save_type_counts": dict(sorted(save_type_counts.items())),
        "cases": [
            {
                "case_id": case.case_id,
                "status": "ready",
                "open_ipl_variant": case.open_ipl_variant,
            }
            for case in inventory.cases
        ]
        + [
            {"case_id": item.case_id, "status": "rejected", "reason": item.reason}
            for item in inventory.rejections
        ],
    }


def _print_and_store(document: dict[str, Any], path: Path) -> None:
    _atomic_write_json(path, document)
    print(json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True))


def _positive_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive decimal integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive decimal integer")
    return parsed


def _wall_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be within 0.1..86400 seconds") from error
    if not 0.1 <= parsed <= 86400:
        raise argparse.ArgumentTypeError("must be within 0.1..86400 seconds")
    return parsed


def _lab_argument(value: str) -> Path:
    return Path(value).expanduser()


def _prepare_inventory(
    root: Path,
) -> tuple[LabPaths, bytes, Inventory, int]:
    lab, lab_warnings = initialize_lab(root)
    key, key_warnings = load_or_create_key(lab.key)
    inventory = _walk_rom_tree(lab.roms, key, lab_warnings + key_warnings)
    return lab, key, inventory, inventory.permission_warnings


def inventory_command(args: argparse.Namespace) -> int:
    lab, _key, inventory, warnings = _prepare_inventory(args.lab_root)
    document = _inventory_document(inventory, warnings)
    _print_and_store(document, lab.reports / "corpus-inventory.json")
    if warnings:
        print(
            f"WARNING: {warnings} private input or lab item(s) permit group/other access",
            file=sys.stderr,
        )
    return int(not inventory.cases or bool(inventory.rejections))


def run_command(args: argparse.Namespace) -> int:
    lab, key, inventory, warnings = _prepare_inventory(args.lab_root)
    if args.dry_run:
        document = _inventory_document(inventory, warnings)
        _print_and_store(document, lab.reports / "corpus-inventory.json")
        return int(not inventory.cases or bool(inventory.rejections))
    try:
        simulator, simulator_sha256 = _validate_simulator(args.simulator)
    except CorpusError as error:
        document = _inventory_document(inventory, warnings)
        document["readiness_error"] = error.code
        _print_and_store(document, lab.reports / "corpus-summary.json")
        return 1

    contract = {
        "simulator_sha256": simulator_sha256,
        "open_ipl_identity": OPEN_IPL_IDENTITY,
        "open_ipl_variants": sorted(
            {case.open_ipl_variant for case in inventory.cases}
        ),
        "frames": args.frames,
        "max_cycles": args.max_cycles,
        "wall_timeout_seconds": args.wall_timeout,
        "repeat": args.repeat,
    }
    contract_id = "contract-" + _opaque_bytes(
        key, b"run-contract", _canonical_json(contract)
    )
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                _execute_case,
                case,
                simulator,
                lab,
                key,
                contract_id,
                args.frames,
                args.max_cycles,
                args.wall_timeout,
                args.repeat,
            )
            for case in inventory.cases
        ]
        for future in futures:
            try:
                results.append(future.result())
            except Exception:  # A programming/runtime failure must become a failing case.
                results.append(
                    {
                        "case_id": "runner-internal-error",
                        "status": "fail",
                        "reason": "runner_internal_error",
                        "attempts": 0,
                        "completed_frames": 0,
                        "deterministic_pair": None,
                        "frame_chain_hmac": None,
                        "resumed": False,
                    }
                )
    for rejection in inventory.rejections:
        results.append(
            {
                "case_id": rejection.case_id,
                "status": "fail",
                "reason": rejection.reason,
                "attempts": 0,
                "completed_frames": 0,
                "deterministic_pair": None,
                "frame_chain_hmac": None,
                "resumed": False,
            }
        )
    results.sort(key=lambda item: item["case_id"])
    passed = sum(item["status"] == "pass" for item in results)
    failed = len(results) - passed
    document = {
        "schema": SUMMARY_SCHEMA,
        "generated_at": _utc_now(),
        "contract_id": contract_id,
        "configuration": {
            "open_ipl_identity": OPEN_IPL_IDENTITY,
            "open_ipl_variants": contract["open_ipl_variants"],
            "frames": args.frames,
            "max_cycles": args.max_cycles,
            "wall_timeout_seconds": args.wall_timeout,
            "repeat": args.repeat,
            "workers": args.workers,
        },
        "counts": {
            "passed": passed,
            "failed": failed,
            "duplicates_not_rerun": inventory.duplicates,
            "ignored_filesystem_metadata": inventory.ignored_filesystem_metadata,
            "permission_warnings": warnings,
        },
        "cases": results,
        "limitations": [
            "translated_swantop_not_apf_or_pocket_wrapper",
            "no_cartridge_save_load_or_flush",
            "no_console_eeprom_persistence",
            "rtc_inputs_fixed_by_simulator",
            "no_audio_capture",
            "not_physical_pocket_or_dock_evidence",
        ],
    }
    _print_and_store(document, lab.reports / "corpus-summary.json")
    if warnings:
        print(
            f"WARNING: {warnings} private input or lab item(s) permit group/other access",
            file=sys.stderr,
        )
    return int(failed != 0 or passed == 0)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Inventory or smoke-test a private local WonderSwan corpus"
    )
    subparsers = result.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser(
        "inventory", help="validate and inventory inputs without starting the simulator"
    )
    inventory.add_argument("--lab-root", type=_lab_argument, default=DEFAULT_LAB_ROOT)
    inventory.set_defaults(handler=inventory_command)

    run = subparsers.add_parser("run", help="run the staged framebuffer smoke test")
    run.add_argument("--lab-root", type=_lab_argument, default=DEFAULT_LAB_ROOT)
    run.add_argument("--simulator", type=Path, default=DEFAULT_SIMULATOR)
    run.add_argument("--workers", type=_positive_int, default=min(4, os.cpu_count() or 1))
    run.add_argument("--frames", type=_positive_int, default=6)
    run.add_argument("--max-cycles", type=_positive_int, default=4_000_000)
    run.add_argument("--wall-timeout", type=_wall_timeout, default=30.0)
    run.add_argument(
        "--repeat", action="store_true", help="repeat and require identical frame hashes"
    )
    run.add_argument(
        "--dry-run", action="store_true", help="inventory only; do not start the simulator"
    )
    run.set_defaults(handler=run_command)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if getattr(args, "workers", 1) > 32:
            raise CorpusError("workers_above_safe_limit")
        if getattr(args, "frames", 1) > 600:
            raise CorpusError("frames_above_safe_limit")
        return args.handler(args)
    except CorpusError as error:
        print(f"ERROR: {error.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
