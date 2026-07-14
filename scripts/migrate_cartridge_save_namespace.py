#!/usr/bin/env python3
"""Safely migrate shared WonderSwan cartridge saves into Swan Song's namespace.

The default operation is a read-only plan.  A ROM is the authority for the
save type and RTC flag; an inherited save is never copied by filename alone.
Writing requires ``--apply`` and uses atomic no-replace publication.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys

from migrate_swan_song_namespace import (
    MigrationError,
    MigrationFile,
    _destination_state,
    _path_below,
    _read_plain_file,
    _root,
)


PLATFORM_ID = "wonderswan"
DESTINATION_CORE_ID = "RegionallyFamous.SwanSong"
ASSET_BASE = PurePosixPath("Assets", PLATFORM_ID, "common")
SOURCE_SAVE_BASE = PurePosixPath("Saves", PLATFORM_ID, "common")
DESTINATION_SAVE_BASE = PurePosixPath("Saves", PLATFORM_ID, DESTINATION_CORE_ID)

MIN_ROM_BYTES = 64 * 1024
MAX_ROM_BYTES = 16 * 1024 * 1024
ROM_BANK_BYTES = 64 * 1024
RTC_BYTES = 12
MAX_TREE_ENTRIES = 8192
MAX_SELECTED_ROMS = 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024

PAYLOAD_BYTES = {
    0x00: 0,
    0x01: 32 * 1024,
    0x02: 32 * 1024,
    0x03: 128 * 1024,
    0x04: 256 * 1024,
    0x05: 512 * 1024,
    0x10: 128,
    0x20: 2048,
    0x50: 1024,
}
SRAM_TRAILER_TYPES = frozenset((0x02, 0x03, 0x04, 0x05))
ROM_EXTENSIONS = frozenset((".ws", ".wsc"))


@dataclass(frozen=True)
class RomMetadata:
    relative: PurePosixPath
    save_type: int
    has_rtc: bool


@dataclass(frozen=True)
class CartridgeMigrationFile:
    rom: PurePosixPath
    source: PurePosixPath
    destination: PurePosixPath
    payload: bytes
    conversion: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()

    def namespace_file(self) -> MigrationFile:
        return MigrationFile(
            source=self.source,
            destination=self.destination,
            payload=self.payload,
            kind="cartridge save",
        )


@dataclass(frozen=True)
class CartridgeMigrationPlan:
    root: Path
    root_device: int
    root_inode: int
    files: tuple[CartridgeMigrationFile, ...]
    copies: tuple[PurePosixPath, ...]
    identical: tuple[PurePosixPath, ...]
    no_save: tuple[PurePosixPath, ...]
    missing: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class CartridgeMigrationResult:
    copied: tuple[PurePosixPath, ...]
    identical: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class _CreatedFile:
    parent_descriptor: int
    name: str
    relative: PurePosixPath
    device: int
    inode: int
    payload: bytes


def _safe_selected_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") for part in path.parts)
        or any("\\" in part for part in path.parts)
        or any(any(ord(character) < 0x20 or ord(character) == 0x7F for character in part)
               for part in path.parts)
    ):
        raise MigrationError(f"unsafe selected ROM path: {value!r}")
    if path.suffix.lower() not in ROM_EXTENSIONS:
        raise MigrationError(f"selected ROM must end in .ws or .wsc: {value!r}")
    return path


def _walk_roms(root: Path) -> tuple[PurePosixPath, ...]:
    base = _path_below(root, ASSET_BASE, description="asset tree")
    try:
        metadata = base.lstat()
    except FileNotFoundError as error:
        raise MigrationError(f"WonderSwan asset directory does not exist: {base}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MigrationError(f"asset tree must be a nonsymlink directory: {base}")

    result: list[PurePosixPath] = []
    entry_count = 0

    def walk(directory: Path, relative: PurePosixPath) -> None:
        nonlocal entry_count
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            raise MigrationError(f"cannot inspect asset tree {directory}: {error}") from error
        folded: set[str] = set()
        for entry in entries:
            if entry.name == ".DS_Store" or entry.name.startswith("._"):
                continue
            entry_count += 1
            if entry_count > MAX_TREE_ENTRIES:
                raise MigrationError(f"asset tree exceeds {MAX_TREE_ENTRIES} entries")
            key = entry.name.casefold()
            if key in folded:
                raise MigrationError(f"case-colliding asset path: {directory / entry.name}")
            folded.add(key)
            path = directory / entry.name
            child = relative / entry.name
            if entry.is_symlink():
                raise MigrationError(f"asset tree contains a symlink: {path}")
            if entry.is_dir(follow_symlinks=False):
                walk(path, child)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise MigrationError(f"asset tree contains a non-regular entry: {path}")
            if PurePosixPath(entry.name).suffix.lower() in ROM_EXTENSIONS:
                result.append(child)
                if len(result) > MAX_SELECTED_ROMS:
                    raise MigrationError(f"migration exceeds {MAX_SELECTED_ROMS} ROMs")

    walk(base, PurePosixPath())
    return tuple(result)


def _selected_roms(
    root: Path, *, selected: tuple[str, ...], all_roms: bool
) -> tuple[PurePosixPath, ...]:
    if all_roms == bool(selected):
        raise MigrationError("choose exactly one of --all or one or more --select paths")
    if all_roms:
        result = _walk_roms(root)
    else:
        result = tuple(_safe_selected_path(value) for value in selected)
        if len(result) > MAX_SELECTED_ROMS:
            raise MigrationError(f"migration exceeds {MAX_SELECTED_ROMS} ROMs")
    if len(set(result)) != len(result):
        raise MigrationError("selected ROM list contains duplicates")
    if len({item.as_posix().casefold() for item in result}) != len(result):
        raise MigrationError("selected ROM list contains case-colliding paths")
    return tuple(sorted(result, key=lambda item: item.as_posix()))


def _inspect_rom(root: Path, relative: PurePosixPath) -> RomMetadata:
    source_relative = ASSET_BASE / relative
    source = _path_below(root, source_relative, description="selected ROM")
    rom = _read_plain_file(source, description="selected ROM", maximum=MAX_ROM_BYTES)
    if len(rom) < MIN_ROM_BYTES or len(rom) % ROM_BANK_BYTES:
        raise MigrationError(
            f"ROM size must be whole 64 KiB banks from 64 KiB to 16 MiB: {source_relative}"
        )
    footer = rom[-16:]
    if footer[0] != 0xEA:
        raise MigrationError(f"ROM footer entry marker is invalid: {source_relative}")
    if footer[7] not in (0, 1):
        raise MigrationError(f"ROM footer color flag is invalid: {source_relative}")
    save_type = footer[11]
    if save_type not in PAYLOAD_BYTES:
        raise MigrationError(
            f"ROM footer save type 0x{save_type:02x} is unsupported: {source_relative}"
        )
    if not (footer[12] & 0x04):
        raise MigrationError(f"ROM footer bus flag is unsupported: {source_relative}")
    if footer[13] not in (0, 1):
        raise MigrationError(f"ROM footer RTC flag is invalid: {source_relative}")
    stored = int.from_bytes(rom[-2:], "little")
    computed = sum(memoryview(rom)[:-2]) & 0xFFFF
    if stored != computed:
        raise MigrationError(
            f"ROM footer checksum mismatch for {source_relative}: "
            f"stored 0x{stored:04x}, computed 0x{computed:04x}"
        )
    return RomMetadata(relative=relative, save_type=save_type, has_rtc=footer[13] == 1)


def _save_relative(rom_relative: PurePosixPath) -> PurePosixPath:
    return rom_relative.with_suffix(".sav")


def _convert_save(metadata: RomMetadata, inherited: bytes) -> tuple[bytes, str]:
    save_type = metadata.save_type
    payload_size = PAYLOAD_BYTES[save_type]
    canonical_size = payload_size + (RTC_BYTES if metadata.has_rtc else 0)
    if len(inherited) == canonical_size:
        return inherited, "canonical"

    if save_type == 0x01 and len(inherited) == 8 * 1024 + RTC_BYTES:
        output = inherited[: 8 * 1024] + bytes(24 * 1024)
        if metadata.has_rtc:
            output += inherited[-RTC_BYTES:]
        return output, "agg type-01 expansion"

    if save_type in (0x10, 0x50) and len(inherited) == 2048 + RTC_BYTES:
        output = inherited[:payload_size]
        if metadata.has_rtc:
            output += inherited[-RTC_BYTES:]
        return output, f"agg type-{save_type:02x} depadding"

    may_drop_agg_trailer = save_type == 0x20 or save_type in SRAM_TRAILER_TYPES
    if (
        may_drop_agg_trailer
        and not metadata.has_rtc
        and len(inherited) == payload_size + RTC_BYTES
    ):
        trailer = inherited[-RTC_BYTES:]
        if not trailer.startswith(b"RT"):
            raise MigrationError(
                f"unrecognized trailing data for non-RTC type 0x{save_type:02x}; "
                "the removable 12-byte agg trailer must begin with RT"
            )
        return inherited[:payload_size], "agg non-RTC trailer removal"

    raise MigrationError(
        f"unrecognized save layout for type 0x{save_type:02x} "
        f"({'RTC' if metadata.has_rtc else 'non-RTC'}): {len(inherited)} bytes"
    )


def _collect_file(root: Path, metadata: RomMetadata) -> CartridgeMigrationFile | None:
    mirrored = _save_relative(metadata.relative)
    source_relative = SOURCE_SAVE_BASE / mirrored
    source = _path_below(root, source_relative, description="shared cartridge save")
    try:
        source_metadata = source.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(source_metadata.st_mode) or not stat.S_ISREG(source_metadata.st_mode):
        raise MigrationError(
            f"shared cartridge save must be a regular nonsymlink file: {source}"
        )
    inherited = _read_plain_file(
        source,
        description="shared cartridge save",
        maximum=MAX_ROM_BYTES,
    )
    output, conversion = _convert_save(metadata, inherited)
    return CartridgeMigrationFile(
        rom=ASSET_BASE / metadata.relative,
        source=source_relative,
        destination=DESTINATION_SAVE_BASE / mirrored,
        payload=output,
        conversion=conversion,
    )


def plan_migration(
    sd_root: Path, *, selected: tuple[str, ...] = (), all_roms: bool = False
) -> CartridgeMigrationPlan:
    """Return a completely validated, read-only cartridge-save migration plan."""

    root = _root(sd_root)
    root_metadata = root.stat(follow_symlinks=False)
    roms = _selected_roms(root, selected=selected, all_roms=all_roms)
    files: list[CartridgeMigrationFile] = []
    no_save: list[PurePosixPath] = []
    missing: list[PurePosixPath] = []
    total = 0
    for relative in roms:
        metadata = _inspect_rom(root, relative)
        if metadata.save_type == 0x00:
            no_save.append(ASSET_BASE / relative)
            continue
        managed = _collect_file(root, metadata)
        if managed is None:
            missing.append(SOURCE_SAVE_BASE / _save_relative(relative))
            continue
        total += len(managed.payload)
        if total > MAX_OUTPUT_BYTES:
            raise MigrationError(f"planned output exceeds {MAX_OUTPUT_BYTES} bytes")
        files.append(managed)

    destinations = [item.destination for item in files]
    if len(set(destinations)) != len(destinations):
        raise MigrationError("multiple ROMs map to the same cartridge-save destination")
    if len({item.as_posix().casefold() for item in destinations}) != len(destinations):
        raise MigrationError("cartridge-save plan contains case-colliding destinations")
    copies: list[PurePosixPath] = []
    identical: list[PurePosixPath] = []
    for managed in files:
        state = _destination_state(root, managed.namespace_file())
        (copies if state == "copy" else identical).append(managed.destination)
    return CartridgeMigrationPlan(
        root=root,
        root_device=root_metadata.st_dev,
        root_inode=root_metadata.st_ino,
        files=tuple(files),
        copies=tuple(copies),
        identical=tuple(identical),
        no_save=tuple(no_save),
        missing=tuple(missing),
    )


def _identity(item: CartridgeMigrationFile) -> tuple[object, ...]:
    return (item.rom, item.source, item.destination, item.payload, item.conversion)


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_root_descriptor(root: Path, *, device: int, inode: int) -> int:
    try:
        descriptor = os.open(root, _directory_flags())
    except OSError as error:
        raise MigrationError("SD root became unsafe after planning") from error
    try:
        opened = os.fstat(descriptor)
        observed = os.stat(root, follow_symlinks=False)
        expected = (device, inode)
        if (
            (opened.st_dev, opened.st_ino) != expected
            or (observed.st_dev, observed.st_ino) != expected
        ):
            raise MigrationError("SD root identity changed after planning")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _case_safe_name_at(directory: int, name: str, *, description: str) -> bool:
    try:
        matches = [
            entry for entry in os.listdir(directory)
            if entry.casefold() == name.casefold()
        ]
    except OSError as error:
        raise MigrationError(f"cannot inspect {description}: {error}") from error
    if len(matches) > 1 or (matches and matches[0] != name):
        observed = matches[0] if matches else name
        raise MigrationError(f"case-colliding {description}: {observed}")
    return bool(matches)


def _open_parent_at(
    root_descriptor: int, relative: PurePosixPath, *, create: bool
) -> int | None:
    """Open one destination parent below a held root without following links."""

    current = os.dup(root_descriptor)
    walked: list[str] = []
    try:
        for part in relative.parts[:-1]:
            walked.append(part)
            description = "cartridge-save destination parent " + "/".join(walked)
            exists = _case_safe_name_at(current, part, description=description)
            if not exists:
                if not create:
                    os.close(current)
                    return None
                try:
                    os.mkdir(part, 0o755, dir_fd=current)
                except FileExistsError:
                    pass
                _case_safe_name_at(current, part, description=description)
            try:
                metadata = os.stat(part, dir_fd=current, follow_symlinks=False)
            except OSError as error:
                raise MigrationError(f"unsafe {description}") from error
            if stat.S_ISLNK(metadata.st_mode):
                raise MigrationError(f"{description} must not be a symlink")
            if not stat.S_ISDIR(metadata.st_mode):
                raise MigrationError(f"{description} is not a directory")
            try:
                child = os.open(part, _directory_flags(), dir_fd=current)
            except OSError as error:
                raise MigrationError(f"unsafe {description}") from error
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def _read_destination_at(
    directory: int, name: str, expected: bytes
) -> tuple[bytes, os.stat_result] | None:
    """Read a stable regular-file destination through a held parent descriptor."""

    if not _case_safe_name_at(
        directory, name, description="cartridge-save destination"
    ):
        return None
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except OSError as error:
        raise MigrationError(f"unsafe cartridge-save destination: {name}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise MigrationError(
                f"cartridge-save destination is not a regular file: {name}"
            )
        if before.st_size != len(expected):
            raise MigrationError(
                f"destination differs; refusing to overwrite: {name}"
            )
        payload = bytearray()
        while len(payload) <= len(expected):
            chunk = os.read(
                descriptor,
                min(1024 * 1024, len(expected) + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if not stable or len(payload) != after.st_size:
        raise MigrationError(
            f"cartridge-save destination changed while reading: {name}"
        )
    return bytes(payload), after


def _destination_state_at(directory: int, name: str, payload: bytes) -> str:
    observed = _read_destination_at(directory, name, payload)
    if observed is None:
        return "copy"
    if observed[0] != payload:
        raise MigrationError(f"destination differs; refusing to overwrite: {name}")
    return "identical"


def _native_rename_noreplace_at(directory: int, source: str, destination: str) -> None:
    """Atomically rename within a held directory without replacing a name."""

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        renameatx = libc.renameatx_np
        renameatx.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameatx.restype = ctypes.c_int
        result = renameatx(
            directory,
            os.fsencode(source),
            directory,
            os.fsencode(destination),
            0x00000004,
        )
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
            directory,
            os.fsencode(source),
            directory,
            os.fsencode(destination),
            0x00000001,
        )
    else:
        raise OSError(errno.ENOSYS, "atomic exclusive rename is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)


def _install_atomic_no_replace_at(directory: int, source: str, destination: str) -> bool:
    """Publish within a held directory; return whether rename consumed source."""

    try:
        _native_rename_noreplace_at(directory, source, destination)
        return True
    except OSError as error:
        if error.errno == errno.EEXIST:
            raise MigrationError(
                f"destination appeared before atomic no-clobber copy: {destination}"
            ) from error
        unsupported = {
            errno.ENOSYS,
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if error.errno not in unsupported:
            raise

    try:
        os.link(
            source,
            destination,
            src_dir_fd=directory,
            dst_dir_fd=directory,
            follow_symlinks=False,
        )
    except FileExistsError as error:
        raise MigrationError(
            f"destination appeared before atomic no-clobber copy: {destination}"
        ) from error
    except OSError as error:
        raise MigrationError(
            "destination filesystem does not support an atomic no-clobber "
            f"install: {destination} ({error})"
        ) from error
    return False


def _fsync_directory_best_effort(directory: int) -> None:
    try:
        os.fsync(directory)
    except OSError:
        # The complete file was fsynced before atomic publication. Directory
        # fsync is unavailable on some removable filesystems and must not turn
        # a successful publication into an untracked failure.
        pass


def _atomic_write_new_at(directory: int, name: str, payload: bytes) -> tuple[int, int]:
    """Create a complete file through a held parent and return its inode identity."""

    temporary_name: str | None = None
    descriptor: int | None = None
    published = False
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for _ in range(32):
            candidate = f".{name}.{secrets.token_hex(8)}.tmp"
            try:
                descriptor = os.open(candidate, flags, 0o600, dir_fd=directory)
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if descriptor is None or temporary_name is None:
            raise MigrationError(f"could not allocate a temporary file for {name}")
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
            metadata = os.fstat(stream.fileno())
        _case_safe_name_at(
            directory, name, description="cartridge-save destination"
        )
        consumed = _install_atomic_no_replace_at(directory, temporary_name, name)
        published = True
        if consumed:
            temporary_name = None
        else:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except OSError:
                # Publication already succeeded. A hidden temporary hard link is
                # safer than reporting failure after installing an untracked file.
                pass
            temporary_name = None
        _fsync_directory_best_effort(directory)
        return metadata.st_dev, metadata.st_ino
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
            except OSError:
                if not published:
                    raise


def _confirm_parent_identity(
    root_descriptor: int, relative: PurePosixPath, parent_descriptor: int
) -> None:
    reopened = _open_parent_at(root_descriptor, relative, create=False)
    if reopened is None:
        raise MigrationError(
            f"cartridge-save destination parent disappeared: {relative.parent}"
        )
    try:
        expected = os.fstat(parent_descriptor)
        observed = os.fstat(reopened)
        if (expected.st_dev, expected.st_ino) != (observed.st_dev, observed.st_ino):
            raise MigrationError(
                f"cartridge-save destination parent identity changed: {relative.parent}"
            )
    finally:
        os.close(reopened)


def _verify_created_at(created: _CreatedFile) -> None:
    observed = _read_destination_at(
        created.parent_descriptor, created.name, created.payload
    )
    if observed is None:
        raise MigrationError(f"copied file disappeared: {created.relative}")
    payload, metadata = observed
    if (metadata.st_dev, metadata.st_ino) != (created.device, created.inode):
        raise MigrationError(f"copied file identity changed: {created.relative}")
    if payload != created.payload:
        raise MigrationError(f"copied file verification failed: {created.relative}")


def _rollback_created_at(created: _CreatedFile) -> bool:
    """Quarantine by atomic rename, then remove only the created inode."""

    quarantine: str | None = None
    for _ in range(32):
        candidate = f".{created.name}.{secrets.token_hex(8)}.rollback"
        if _case_safe_name_at(
            created.parent_descriptor,
            candidate,
            description="rollback quarantine",
        ):
            continue
        try:
            _native_rename_noreplace_at(
                created.parent_descriptor, created.name, candidate
            )
        except OSError as error:
            if error.errno == errno.ENOENT:
                return True
            if error.errno == errno.EEXIST:
                continue
            return False
        quarantine = candidate
        break
    if quarantine is None:
        return False

    try:
        observed = _read_destination_at(
            created.parent_descriptor, quarantine, created.payload
        )
    except MigrationError:
        observed = None
    if observed is not None:
        payload, metadata = observed
        if (
            (metadata.st_dev, metadata.st_ino) == (created.device, created.inode)
            and payload == created.payload
        ):
            try:
                final = os.stat(
                    quarantine,
                    dir_fd=created.parent_descriptor,
                    follow_symlinks=False,
                )
                if (final.st_dev, final.st_ino) != (created.device, created.inode):
                    return False
                os.unlink(quarantine, dir_fd=created.parent_descriptor)
                _fsync_directory_best_effort(created.parent_descriptor)
                return True
            except OSError:
                return False

    # The destination name held someone else's inode. Restore it exclusively;
    # never delete or overwrite it as part of this invocation's rollback.
    try:
        _native_rename_noreplace_at(
            created.parent_descriptor, quarantine, created.name
        )
    except OSError:
        return False
    return False


def apply_migration(
    plan: CartridgeMigrationPlan, *, selected: tuple[str, ...] = (), all_roms: bool = False
) -> CartridgeMigrationResult:
    """Revalidate and atomically copy a plan without replacing destinations."""

    root = _root(plan.root)
    if root != plan.root:
        raise MigrationError("SD root identity changed after planning")
    root_descriptor = _open_root_descriptor(
        root, device=plan.root_device, inode=plan.root_inode
    )
    copied: list[PurePosixPath] = []
    identical: list[PurePosixPath] = []
    # Retain each exact parent descriptor until the transaction finishes. If a
    # later exclusive publish fails, rollback can remove only the unchanged
    # inode this invocation created, without resolving a possibly swapped path.
    created: list[_CreatedFile] = []
    try:
        try:
            current = plan_migration(root, selected=selected, all_roms=all_roms)
            if (
                (current.root_device, current.root_inode)
                != (plan.root_device, plan.root_inode)
                or tuple(map(_identity, current.files))
                != tuple(map(_identity, plan.files))
                or current.no_save != plan.no_save
                or current.missing != plan.missing
            ):
                raise MigrationError("cartridge-save source changed after planning")

            for managed in current.files:
                parent_descriptor = _open_parent_at(
                    root_descriptor, managed.destination, create=True
                )
                assert parent_descriptor is not None
                retain_parent = False
                try:
                    state = _destination_state_at(
                        parent_descriptor, managed.destination.name, managed.payload
                    )
                    if state == "identical":
                        identical.append(managed.destination)
                        continue
                    device, inode = _atomic_write_new_at(
                        parent_descriptor, managed.destination.name, managed.payload
                    )
                    installed = _CreatedFile(
                        parent_descriptor=parent_descriptor,
                        name=managed.destination.name,
                        relative=managed.destination,
                        device=device,
                        inode=inode,
                        payload=managed.payload,
                    )
                    created.append(installed)
                    retain_parent = True
                    _confirm_parent_identity(
                        root_descriptor, managed.destination, parent_descriptor
                    )
                    _verify_created_at(installed)
                    copied.append(managed.destination)
                finally:
                    if not retain_parent:
                        os.close(parent_descriptor)
        except Exception as error:
            leftovers: list[str] = []
            for installed in reversed(created):
                try:
                    if not _rollback_created_at(installed):
                        leftovers.append(str(installed.relative))
                except (MigrationError, OSError, ValueError):
                    leftovers.append(str(installed.relative))
            if leftovers:
                joined = ", ".join(leftovers)
                raise MigrationError(
                    f"cartridge-save apply failed ({error}); rollback left "
                    f"inode-changed or unverifiable file(s): {joined}"
                ) from error
            raise
        return CartridgeMigrationResult(tuple(copied), tuple(identical))
    finally:
        for installed in created:
            os.close(installed.parent_descriptor)
        os.close(root_descriptor)


def _summary(
    plan: CartridgeMigrationPlan, *, result: CartridgeMigrationResult | None
) -> str:
    copied = result.copied if result is not None else plan.copies
    identical = result.identical if result is not None else plan.identical
    lines = [
        "APPLIED" if result is not None else "VALIDATED ONLY — no files written",
        f"SD root: {plan.root}",
        f"Files: {len(copied)} {'copied' if result is not None else 'to copy'}, "
        f"{len(identical)} identical, {len(plan.missing)} without a shared save, "
        f"{len(plan.no_save)} no-save titles",
    ]
    copy_set = set(copied)
    for item in plan.files:
        action = "COPY" if item.destination in copy_set else "IDENTICAL"
        lines.append(
            f"{action} {item.source} -> {item.destination} "
            f"({item.conversion}, {len(item.payload)} bytes, SHA-256 {item.sha256}; "
            f"ROM {item.rom})"
        )
    for item in plan.no_save:
        lines.append(f"SKIP no-save ROM {item}")
    for item in plan.missing:
        lines.append(f"SKIP no shared save {item}")
    lines.append("Sources are never moved, deleted, renamed, or modified.")
    if result is None:
        lines.append("Next: review this plan, make an SD backup, then rerun with --apply.")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sd-root", required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--select",
        action="append",
        default=[],
        metavar="RELATIVE_ROM",
        help="select a .ws/.wsc path relative to Assets/wonderswan/common (repeatable)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help=f"inspect every ROM, bounded to {MAX_SELECTED_ROMS} ROMs",
    )
    parser.add_argument("--apply", action="store_true", help="perform atomic no-clobber copies")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    selected = tuple(arguments.select)
    try:
        plan = plan_migration(
            arguments.sd_root, selected=selected, all_roms=arguments.all
        )
        result = (
            apply_migration(plan, selected=selected, all_roms=arguments.all)
            if arguments.apply
            else None
        )
        print(_summary(plan, result=result))
        return 0
    except (MigrationError, OSError) as error:
        print(f"migrate_cartridge_save_namespace.py: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
