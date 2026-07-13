#!/usr/bin/env python3
"""Safely migrate a legacy Pocket type-01 save to the corrected 32 KiB layout."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import os
import pathlib
import stat
import sys
import tempfile
from dataclasses import dataclass


MIN_ROM_SIZE = 64 * 1024
ROM_RAM_TYPE_OFFSET = -5
ROM_CHECKSUM_SIZE = 2
TYPE01 = 0x01
LEGACY_SRAM_SIZE = 8 * 1024
CORRECTED_SRAM_SIZE = 32 * 1024
RTC_TRAILER_SIZE = 12
LEGACY_SAVE_SIZE = LEGACY_SRAM_SIZE + RTC_TRAILER_SIZE
MIGRATED_SAVE_SIZE = CORRECTED_SRAM_SIZE + RTC_TRAILER_SIZE
TEMP_PREFIX = ".swan-song-type01-save-"


@dataclass(frozen=True)
class MigrationReport:
    rom: pathlib.Path
    legacy_save: pathlib.Path
    output: pathlib.Path
    rom_sha256: str
    legacy_save_sha256: str
    rtc_sha256: str
    output_sha256: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _absolute(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(os.path.abspath(os.fspath(path)))


def _read_regular_file(path: pathlib.Path, description: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as error:
        raise ValueError(f"cannot open {description} {path}: {error}") from error

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{description} is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            descriptor = -1
            return source.read()
    except OSError as error:
        raise ValueError(f"cannot read {description} {path}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _entry_exists(path: pathlib.Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _ensure_output_available(
    output: pathlib.Path, sources: tuple[pathlib.Path, ...]
) -> None:
    output_absolute = _absolute(output)
    for source in sources:
        if output_absolute == _absolute(source):
            raise ValueError(f"output path aliases input: {output}")

    if not _entry_exists(output):
        return

    for source in sources:
        try:
            if os.path.samefile(output, source):
                raise ValueError(f"output inode aliases input {source}: {output}")
        except FileNotFoundError:
            pass
        except OSError:
            # A dangling or otherwise unreadable symlink is still an existing
            # output directory entry and is rejected below.
            pass
    raise ValueError(f"output already exists; refusing to overwrite: {output}")


def _validate_rom(rom: bytes) -> None:
    if len(rom) < MIN_ROM_SIZE:
        raise ValueError(
            f"ROM is too small for a WonderSwan cartridge image: "
            f"{len(rom)} < {MIN_ROM_SIZE} bytes"
        )

    ram_type = rom[ROM_RAM_TYPE_OFFSET]
    if ram_type != TYPE01:
        raise ValueError(
            f"ROM footer save type must be exactly 0x01, found 0x{ram_type:02x}"
        )

    stored_checksum = int.from_bytes(rom[-ROM_CHECKSUM_SIZE:], "little")
    computed_checksum = sum(memoryview(rom)[:-ROM_CHECKSUM_SIZE]) & 0xFFFF
    if stored_checksum != computed_checksum:
        raise ValueError(
            "ROM footer checksum mismatch: "
            f"stored 0x{stored_checksum:04x}, computed 0x{computed_checksum:04x}"
        )


def _validate_legacy_save(save: bytes) -> None:
    if len(save) != LEGACY_SAVE_SIZE:
        raise ValueError(
            "legacy type-01 Pocket save must be exactly "
            f"{LEGACY_SAVE_SIZE} bytes (8192-byte SRAM plus opaque 12-byte RTC), "
            f"found {len(save)}"
        )


def _native_rename_noreplace(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Use the host's atomic exclusive-rename primitive when available."""

    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    libc = ctypes.CDLL(None, use_errno=True)

    if sys.platform == "darwin":
        renamex = libc.renamex_np
        renamex.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        renamex.restype = ctypes.c_int
        # RENAME_EXCL from Darwin's <stdio.h> makes destination existence an
        # atomic EEXIST failure instead of replacing it.
        result = renamex(source_bytes, destination_bytes, 0x00000004)
    elif sys.platform.startswith("linux"):
        try:
            renameat2 = libc.renameat2
        except AttributeError as error:
            raise OSError(errno.ENOSYS, "renameat2 is unavailable") from error
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        # AT_FDCWD and RENAME_NOREPLACE from Linux <fcntl.h>.
        result = renameat2(-100, source_bytes, -100, destination_bytes, 0x1)
    elif os.name == "nt":
        # os.rename() is exclusive on Windows and raises FileExistsError when
        # the destination exists.
        os.rename(source, destination)
        return
    else:
        raise OSError(errno.ENOSYS, "atomic exclusive rename is unavailable")

    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)


def _rename_noreplace(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Atomically publish source without ever replacing destination."""

    try:
        _native_rename_noreplace(source, destination)
        return
    except OSError as error:
        unsupported = {
            errno.ENOSYS,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }
        if error.errno not in unsupported:
            raise

    # A same-directory hard link is also an atomic, no-clobber publication.
    # This fallback covers Unix hosts lacking an exclusive-rename API. If the
    # output filesystem supports neither primitive, fail closed rather than
    # weakening the no-overwrite contract.
    try:
        os.link(source, destination, follow_symlinks=False)
    except OSError as error:
        unsupported = {
            errno.EPERM,
            errno.ENOSYS,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }
        if error.errno in unsupported:
            raise ValueError(
                "output filesystem does not support atomic no-overwrite "
                "publication; choose another output directory"
            ) from error
        raise
    os.unlink(source)


def _atomic_create(
    output: pathlib.Path, data: bytes, sources: tuple[pathlib.Path, ...]
) -> None:
    _ensure_output_available(output, sources)
    parent = output.parent
    try:
        parent_metadata = parent.stat()
    except OSError as error:
        raise ValueError(f"cannot access output directory {parent}: {error}") from error
    if not stat.S_ISDIR(parent_metadata.st_mode):
        raise ValueError(f"output parent is not a directory: {parent}")

    descriptor = -1
    temporary: pathlib.Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=TEMP_PREFIX, suffix=".tmp", dir=parent
        )
        temporary = pathlib.Path(temporary_name)
        with os.fdopen(descriptor, "wb", closefd=True) as destination:
            descriptor = -1
            destination.write(data)
            destination.flush()
            os.fsync(destination.fileno())

        try:
            _rename_noreplace(temporary, output)
        except FileExistsError as error:
            raise ValueError(
                f"output appeared during migration; refusing to overwrite: {output}"
            ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def migrate_type01_save(
    rom_path: pathlib.Path, legacy_save_path: pathlib.Path, output_path: pathlib.Path
) -> MigrationReport:
    rom_path = pathlib.Path(rom_path)
    legacy_save_path = pathlib.Path(legacy_save_path)
    output_path = pathlib.Path(output_path)
    sources = (rom_path, legacy_save_path)

    # Reject all pre-existing output directory entries, including dangling
    # symlinks, before spending time reading or validating the inputs.
    _ensure_output_available(output_path, sources)
    rom = _read_regular_file(rom_path, "ROM")
    legacy_save = _read_regular_file(legacy_save_path, "legacy save")
    _validate_rom(rom)
    _validate_legacy_save(legacy_save)

    rtc = legacy_save[LEGACY_SRAM_SIZE:]
    migrated = (
        legacy_save[:LEGACY_SRAM_SIZE]
        + bytes(CORRECTED_SRAM_SIZE - LEGACY_SRAM_SIZE)
        + rtc
    )
    if len(migrated) != MIGRATED_SAVE_SIZE:
        raise AssertionError("internal migrated save size invariant failed")

    _atomic_create(output_path, migrated, sources)
    return MigrationReport(
        rom=_absolute(rom_path),
        legacy_save=_absolute(legacy_save_path),
        output=_absolute(output_path),
        rom_sha256=_sha256(rom),
        legacy_save_sha256=_sha256(legacy_save),
        rtc_sha256=_sha256(rtc),
        output_sha256=_sha256(migrated),
    )


def format_report(report: MigrationReport) -> str:
    return "\n".join(
        (
            f"ROM: {report.rom}",
            f"ROM SHA-256: {report.rom_sha256}",
            f"Legacy save: {report.legacy_save}",
            f"Legacy save SHA-256: {report.legacy_save_sha256}",
            "Layout: preserve SRAM [0,8192); zero-fill SRAM [8192,32768); "
            "relocate RTC [8192,8204) -> [32768,32780)",
            "RTC: opaque 12-byte copy; byte order and sentinel unchecked",
            f"RTC SHA-256: {report.rtc_sha256}",
            f"Output: {report.output}",
            f"Output size: {MIGRATED_SAVE_SIZE} bytes",
            f"Output SHA-256: {report.output_sha256}",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=pathlib.Path, help="type-01 WonderSwan ROM")
    parser.add_argument(
        "legacy_save", type=pathlib.Path, help="exact 8,204-byte legacy Pocket save"
    )
    parser.add_argument(
        "output", type=pathlib.Path, help="new output path (must not already exist)"
    )
    args = parser.parse_args()

    try:
        report = migrate_type01_save(args.rom, args.legacy_save, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(format_report(report))


if __name__ == "__main__":
    main()
