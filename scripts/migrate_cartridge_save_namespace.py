#!/usr/bin/env python3
"""Safely migrate shared WonderSwan cartridge saves into Swan Song's namespace.

The default operation is a read-only plan.  A ROM is the authority for the
save type and RTC flag; an inherited save is never copied by filename alone.
Writing requires ``--apply`` and uses atomic no-replace publication.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import sys

from migrate_swan_song_namespace import (
    MigrationError,
    MigrationFile,
    _atomic_write_new,
    _destination_state,
    _ensure_destination_parent,
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
    files: tuple[CartridgeMigrationFile, ...]
    copies: tuple[PurePosixPath, ...]
    identical: tuple[PurePosixPath, ...]
    no_save: tuple[PurePosixPath, ...]
    missing: tuple[PurePosixPath, ...]


@dataclass(frozen=True)
class CartridgeMigrationResult:
    copied: tuple[PurePosixPath, ...]
    identical: tuple[PurePosixPath, ...]


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
        files=tuple(files),
        copies=tuple(copies),
        identical=tuple(identical),
        no_save=tuple(no_save),
        missing=tuple(missing),
    )


def _identity(item: CartridgeMigrationFile) -> tuple[object, ...]:
    return (item.rom, item.source, item.destination, item.payload, item.conversion)


def apply_migration(
    plan: CartridgeMigrationPlan, *, selected: tuple[str, ...] = (), all_roms: bool = False
) -> CartridgeMigrationResult:
    """Revalidate and atomically copy a plan without replacing destinations."""

    root = _root(plan.root)
    if root != plan.root:
        raise MigrationError("SD root identity changed after planning")
    current = plan_migration(root, selected=selected, all_roms=all_roms)
    if (
        tuple(map(_identity, current.files)) != tuple(map(_identity, plan.files))
        or current.no_save != plan.no_save
        or current.missing != plan.missing
    ):
        raise MigrationError("cartridge-save source changed after planning")

    copied: list[PurePosixPath] = []
    identical: list[PurePosixPath] = []
    # Every entry records the exact inode created by this invocation.  If a
    # later exclusive publish fails, rollback removes only those unchanged
    # inodes; a destination that was replaced or altered is left for recovery
    # instead of risking deletion of someone else's file.
    created: list[tuple[Path, int, int, bytes]] = []
    try:
        for managed in current.files:
            namespace_file = managed.namespace_file()
            if _destination_state(root, namespace_file) == "identical":
                identical.append(managed.destination)
                continue
            destination = _ensure_destination_parent(root, managed.destination)
            if _destination_state(root, namespace_file) == "identical":
                identical.append(managed.destination)
                continue
            _atomic_write_new(destination, managed.payload)
            installed = destination.lstat()
            if not stat.S_ISREG(installed.st_mode):
                raise MigrationError(
                    f"copied destination is not a regular file: {managed.destination}"
                )
            created.append(
                (destination, installed.st_dev, installed.st_ino, managed.payload)
            )
            written = _read_plain_file(
                destination,
                description="migrated cartridge save",
                maximum=max(1, len(managed.payload)),
            )
            if written != managed.payload:
                raise MigrationError(
                    f"copied file verification failed: {managed.destination}"
                )
            copied.append(managed.destination)
    except Exception as error:
        leftovers: list[str] = []
        for destination, device, inode, payload in reversed(created):
            try:
                checked = _path_below(
                    root,
                    PurePosixPath(destination.relative_to(root).as_posix()),
                    description="rollback destination",
                )
                metadata = checked.lstat()
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_dev != device
                    or metadata.st_ino != inode
                ):
                    leftovers.append(str(checked.relative_to(root)))
                    continue
                observed = _read_plain_file(
                    checked,
                    description="rollback destination",
                    maximum=max(1, len(payload)),
                )
                if observed != payload:
                    leftovers.append(str(checked.relative_to(root)))
                    continue
                checked.unlink()
            except (MigrationError, OSError, ValueError):
                try:
                    leftovers.append(str(destination.relative_to(root)))
                except ValueError:
                    leftovers.append(str(destination))
        if leftovers:
            joined = ", ".join(leftovers)
            raise MigrationError(
                f"cartridge-save apply failed ({error}); rollback left "
                f"inode-changed or unverifiable file(s): {joined}"
            ) from error
        raise
    return CartridgeMigrationResult(tuple(copied), tuple(identical))


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
