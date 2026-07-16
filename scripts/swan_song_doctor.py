#!/usr/bin/env python3
"""Diagnose a Swan Song Analogue Pocket SD card without reading game contents.

The default operation performs no content or namespace writes. Filesystem reads
may update access-time metadata. Selected repairs require both a specific fix
flag and ``--apply``. Game contents are never opened, read, or hashed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Iterable

import package_validator as validator
from migrate_swan_song_namespace import (
    MigrationError,
    MigrationPlan,
    MigrationResult,
    apply_migration,
    plan_migration,
)
from pocket_per_game_preset import (
    PresetError,
    PresetOptions,
    _open_bound_root,
    _open_parent_at,
    _read_regular_snapshot_at,
    _verify_bound_root,
    build_input_document,
    build_interact_document,
    generate_presets,
    preset_relative_path,
)


CORE_ID = "RegionallyFamous.SwanSong"
LEGACY_CORE_ID = "agg23.WonderSwan"
PLATFORM_ID = "wonderswan"
REPOSITORY = "https://github.com/RegionallyFamous/swansong-core"
CORE_RELATIVE = PurePosixPath("Cores") / CORE_ID
ASSET_RELATIVE = PurePosixPath("Assets/wonderswan/common")
DEFINITION_ENVELOPES = {
    "audio.json": "audio",
    "core.json": "core",
    "data.json": "data",
    "input.json": "input",
    "interact.json": "interact",
    "variants.json": "variants",
    "video.json": "video",
}
CONSOLE_SAVE_CONTRACT = {"mono.eeprom": 128, "color.eeprom": 2048}
USER_VISIBLE_PAYLOADS = {
    CORE_RELATIVE / "icon.bin": "core menu icon",
    CORE_RELATIVE / "info.txt": "core information text",
    PurePosixPath("Platforms/_images/wonderswan.bin"): "WonderSwan platform artwork",
}
ROM_BANK_BYTES = 64 * 1024
MIN_ROM_BYTES = ROM_BANK_BYTES
MAX_ROM_BYTES = 16 * 1024 * 1024
MAX_DEFINITION_BYTES = 1024 * 1024
MAX_SCAN_ENTRIES = 65536
MAX_SCAN_DEPTH = 32
IGNORED_METADATA = {".DS_Store"}


class DoctorError(ValueError):
    """The selected SD card or requested repair is unsafe."""


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    action: str = ""
    path: str = ""
    unsafe: bool = False


@dataclass(frozen=True)
class Inventory:
    games_by_preset: dict[PurePosixPath, tuple[PurePosixPath, ...]]
    interact_presets: frozenset[PurePosixPath]
    input_presets: frozenset[PurePosixPath]
    core_directory: Path | None


@dataclass(frozen=True)
class DoctorReport:
    root: Path
    root_identity: tuple[int, int]
    findings: tuple[Finding, ...]
    inventory: Inventory

    @property
    def errors(self) -> int:
        return sum(item.severity == "ERROR" for item in self.findings)

    @property
    def warnings(self) -> int:
        return sum(item.severity == "WARN" for item in self.findings)

    @property
    def unsafe(self) -> bool:
        return any(item.unsafe for item in self.findings)


@dataclass(frozen=True)
class PresetPlanItem:
    asset: PurePosixPath
    interact: PurePosixPath
    input: PurePosixPath


@dataclass(frozen=True)
class PresetPlan:
    root: Path
    root_identity: tuple[int, int]
    definitions: Path
    definitions_identity: tuple[int, int]
    items: tuple[PresetPlanItem, ...]


def _finding(
    findings: list[Finding],
    severity: str,
    code: str,
    message: str,
    *,
    action: str = "",
    path: PurePosixPath | str = "",
    unsafe: bool = False,
) -> None:
    findings.append(
        Finding(severity, code, message, action, str(path), unsafe)
    )


def _root(path: Path) -> tuple[Path, int, tuple[int, int]]:
    try:
        resolved, descriptor, identity = _open_bound_root(path)
    except PresetError as error:
        raise DoctorError(str(error).replace("non-symlink", "nonsymlink")) from error
    if resolved == Path(resolved.anchor):
        os.close(descriptor)
        raise DoctorError("refusing to inspect a filesystem root as an SD card")
    return resolved, descriptor, identity


def _ignored(name: str) -> bool:
    return name in IGNORED_METADATA or name.startswith("._")


def _checked_path(
    root: Path,
    relative: PurePosixPath,
    findings: list[Finding],
) -> Path | None:
    """Resolve an exact-case descendant without following symlinks."""

    current = root
    for index, component in enumerate(relative.parts):
        if component in {"", ".", ".."} or "/" in component or "\\" in component:
            _finding(
                findings,
                "ERROR",
                "unsafe-path",
                f"Unsafe managed path component {component!r}.",
                path=relative,
                unsafe=True,
            )
            return None
        try:
            parent_metadata = current.lstat()
        except FileNotFoundError:
            return current.joinpath(*relative.parts[index:])
        if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
            _finding(
                findings,
                "ERROR",
                "unsafe-parent",
                "A managed parent is a symlink or is not a directory.",
                path=relative,
                unsafe=True,
            )
            return None
        try:
            matches = sorted(
                entry.name
                for entry in os.scandir(current)
                if entry.name.casefold() == component.casefold()
            )
        except OSError as error:
            _finding(
                findings,
                "ERROR",
                "unreadable-path",
                f"Cannot inspect managed path: {error}",
                path=relative,
                unsafe=True,
            )
            return None
        if len(matches) > 1 or (matches and matches[0] != component):
            _finding(
                findings,
                "ERROR",
                "case-collision",
                "Managed path has the wrong case or a FAT/exFAT name collision.",
                action="Rename it to the exact displayed path on a case-safe filesystem.",
                path=relative,
                unsafe=True,
            )
            return None
        if not matches:
            return current.joinpath(*relative.parts[index:])
        current = current / component
        try:
            metadata = current.lstat()
        except OSError as error:
            _finding(
                findings,
                "ERROR",
                "unreadable-path",
                f"Cannot inspect managed path: {error}",
                path=relative,
                unsafe=True,
            )
            return None
        if stat.S_ISLNK(metadata.st_mode):
            _finding(
                findings,
                "ERROR",
                "symlink",
                "Managed Pocket paths must not contain symlinks.",
                action="Replace the link with an ordinary file or directory inside the SD card.",
                path=relative,
                unsafe=True,
            )
            return None
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            _finding(
                findings,
                "ERROR",
                "unsafe-parent",
                "A managed parent is not a directory.",
                path=relative,
                unsafe=True,
            )
            return None
    try:
        current.relative_to(root)
    except ValueError:
        _finding(
            findings,
            "ERROR",
            "path-escape",
            "Managed path escaped the selected SD root.",
            path=relative,
            unsafe=True,
        )
        return None
    return current


def _read_json_file(
    root_descriptor: int, relative: PurePosixPath
) -> dict[str, object]:
    parent_descriptor: int | None = None
    try:
        parent_descriptor = _open_parent_at(
            root_descriptor, relative, create=False
        )
        if parent_descriptor is None:
            raise DoctorError(f"invalid JSON in /{relative}: parent is missing")
        snapshot = _read_regular_snapshot_at(
            parent_descriptor, relative.name, maximum=MAX_DEFINITION_BYTES
        )
        if snapshot is None:
            raise DoctorError(f"invalid JSON in /{relative}: file is missing")
        payload = snapshot[0]
        document = validator.strict_json_loads(payload.decode("utf-8"))
    except (
        MigrationError,
        PresetError,
        UnicodeError,
        json.JSONDecodeError,
        validator.StrictJsonError,
    ) as error:
        raise DoctorError(f"invalid JSON in /{relative}: {error}") from error
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    if not isinstance(document, dict):
        raise DoctorError(f"invalid JSON in /{relative}: top level must be an object")
    return document


def _scan_tree(
    root: Path,
    base: Path,
    base_relative: PurePosixPath,
    findings: list[Finding],
) -> list[tuple[PurePosixPath, os.stat_result]]:
    files: list[tuple[PurePosixPath, os.stat_result]] = []
    entries_seen = 0

    def walk(directory: Path, relative: PurePosixPath, depth: int) -> None:
        nonlocal entries_seen
        if depth > MAX_SCAN_DEPTH:
            _finding(
                findings,
                "ERROR",
                "scan-depth",
                f"Tree is deeper than the {MAX_SCAN_DEPTH}-directory safety limit.",
                path=base_relative / relative,
                unsafe=True,
            )
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            _finding(
                findings,
                "ERROR",
                "unreadable-tree",
                f"Cannot inspect directory: {error}",
                path=base_relative / relative,
                unsafe=True,
            )
            return
        folded: dict[str, str] = {}
        for entry in entries:
            if _ignored(entry.name):
                continue
            entries_seen += 1
            if entries_seen > MAX_SCAN_ENTRIES:
                _finding(
                    findings,
                    "ERROR",
                    "scan-limit",
                    f"Tree exceeds the {MAX_SCAN_ENTRIES}-entry safety limit.",
                    path=base_relative,
                    unsafe=True,
                )
                return
            previous = folded.setdefault(entry.name.casefold(), entry.name)
            entry_relative = relative / entry.name
            display = base_relative / entry_relative
            if previous != entry.name:
                _finding(
                    findings,
                    "ERROR",
                    "case-collision",
                    f"Names {previous!r} and {entry.name!r} collide on FAT/exFAT.",
                    path=display,
                    unsafe=True,
                )
                continue
            if entry.is_symlink():
                _finding(
                    findings,
                    "ERROR",
                    "symlink",
                    "Tree contains a symlink; it was not followed.",
                    path=display,
                    unsafe=True,
                )
                continue
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                _finding(
                    findings,
                    "ERROR",
                    "unreadable-entry",
                    f"Cannot inspect entry: {error}",
                    path=display,
                    unsafe=True,
                )
                continue
            if stat.S_ISDIR(metadata.st_mode):
                walk(Path(entry.path), entry_relative, depth + 1)
            elif stat.S_ISREG(metadata.st_mode):
                files.append((entry_relative, metadata))
            else:
                _finding(
                    findings,
                    "ERROR",
                    "special-file",
                    "Tree contains a device, socket, FIFO, or other special file.",
                    path=display,
                    unsafe=True,
                )

    walk(base, PurePosixPath(), 0)
    return files


def _validate_definitions(
    root: Path,
    root_descriptor: int,
    findings: list[Finding],
) -> tuple[Path | None, dict[str, dict[str, object]]]:
    core_directory = _checked_path(root, CORE_RELATIVE, findings)
    if core_directory is None:
        return None, {}
    if not core_directory.exists():
        _finding(
            findings,
            "ERROR",
            "core-missing",
            f"Swan Song is not installed at /{CORE_RELATIVE}.",
            action="Merge the release ZIP into the SD root; do not rename the older core.",
            path=CORE_RELATIVE,
        )
        return core_directory, {}
    if not core_directory.is_dir():
        _finding(
            findings,
            "ERROR",
            "core-not-directory",
            "The Swan Song core path is not a directory.",
            path=CORE_RELATIVE,
            unsafe=True,
        )
        return None, {}

    documents: dict[str, dict[str, object]] = {}
    for filename, envelope in DEFINITION_ENVELOPES.items():
        relative = CORE_RELATIVE / filename
        path = _checked_path(root, relative, findings)
        if path is None:
            continue
        if not path.exists():
            _finding(
                findings,
                "ERROR",
                "definition-missing",
                f"Required definition {filename} is missing.",
                action="Reinstall Swan Song from a complete release ZIP.",
                path=relative,
            )
            continue
        try:
            document = _read_json_file(root_descriptor, relative)
        except DoctorError as error:
            _finding(
                findings,
                "ERROR",
                "definition-invalid",
                str(error),
                action="Reinstall Swan Song from a complete release ZIP.",
                path=relative,
            )
            continue
        if set(document) != {envelope}:
            _finding(
                findings,
                "ERROR",
                "definition-envelope",
                f"{filename} does not contain only the {envelope!r} definition.",
                action="Reinstall Swan Song from a complete release ZIP.",
                path=relative,
            )
            continue
        documents[envelope] = document

    platform_relative = PurePosixPath("Platforms/wonderswan.json")
    platform_path = _checked_path(root, platform_relative, findings)
    if platform_path is not None and platform_path.exists():
        try:
            documents["platform"] = _read_json_file(
                root_descriptor, platform_relative
            )
        except DoctorError as error:
            _finding(
                findings,
                "ERROR",
                "platform-invalid",
                str(error),
                action="Reinstall the Swan Song platform files.",
                path=platform_relative,
            )
    else:
        _finding(
            findings,
            "ERROR",
            "platform-missing",
            "WonderSwan platform metadata is missing; the core may not appear in openFPGA.",
            action="Reinstall the Swan Song platform files.",
            path=platform_relative,
        )

    bitstream_name: str | None = None
    chip32_name: str | None = None
    metadata: dict[str, object] | None = None
    if "core" in documents:
        try:
            metadata, bitstream_name, chip32_name = validator._validate_core(
                documents["core"], f"{CORE_RELATIVE}/core.json"
            )
            if metadata.get("author") != "RegionallyFamous" or metadata.get("shortname") != "SwanSong":
                raise ValueError(f"core identity must be {CORE_ID}")
            if metadata.get("url") != REPOSITORY:
                raise ValueError("core repository identity is stale or foreign")
        except (KeyError, TypeError, ValueError) as error:
            _finding(
                findings,
                "ERROR",
                "definition-contract",
                f"Installed core identity is incomplete, stale, or foreign: {error}",
                action="Reinstall Swan Song from a matching release ZIP.",
                path=CORE_RELATIVE / "core.json",
            )
            metadata = None
        else:
            _finding(
                findings,
                "OK",
                "core-identity",
                f"Installed core identity is {CORE_ID} {metadata['version']} ({metadata['date_release']}).",
                path=CORE_RELATIVE,
            )

    required = set(DEFINITION_ENVELOPES.values()) | {"platform"}
    if metadata is not None and required <= documents.keys():
        try:
            validator._validate_data(
                documents["data"], f"{CORE_RELATIVE}/data.json", 1
            )
            validator._validate_input(
                documents["input"], f"{CORE_RELATIVE}/input.json"
            )
            validator._validate_interact(
                documents["interact"], f"{CORE_RELATIVE}/interact.json"
            )
            validator._validate_video(
                documents["video"], f"{CORE_RELATIVE}/video.json"
            )
            validator._validate_simple_documents(documents)
            variables = documents["interact"]["interact"]["variables"]
            control = [item for item in variables if item.get("id") == 46]
            if len(control) != 1 or validator._integer(
                control[0].get("address"), "Control Layout address"
            ) != 0x214:
                raise ValueError("Control Layout definition is missing or stale")
        except (KeyError, TypeError, ValueError) as error:
            _finding(
                findings,
                "ERROR",
                "definition-contract",
                f"Installed definitions are incomplete, stale, or foreign: {error}",
                action="Reinstall Swan Song from a matching release ZIP.",
                path=CORE_RELATIVE,
            )

    for filename, description in (
        (bitstream_name, "FPGA bitstream"),
        (chip32_name, "Chip32 loader"),
    ):
        if filename is None:
            continue
        relative = CORE_RELATIVE / filename
        path = _checked_path(root, relative, findings)
        if path is None:
            continue
        if not path.exists():
            _finding(
                findings,
                "ERROR",
                "core-payload-missing",
                f"Referenced {description} {filename} is missing.",
                action="Reinstall Swan Song from a complete release ZIP.",
                path=relative,
            )
        else:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
                _finding(
                    findings,
                    "ERROR",
                    "core-payload-invalid",
                    f"Referenced {description} is not a nonempty ordinary file.",
                    path=relative,
                    unsafe=not stat.S_ISREG(metadata.st_mode),
                )

    valid_display_payloads = 0
    for relative, description in USER_VISIBLE_PAYLOADS.items():
        path = _checked_path(root, relative, findings)
        if path is None:
            continue
        if not path.exists():
            _finding(
                findings,
                "ERROR",
                "display-payload-missing",
                f"Required {description} is missing.",
                action="Reinstall Swan Song from a complete release ZIP.",
                path=relative,
            )
            continue
        payload_metadata = path.lstat()
        if not stat.S_ISREG(payload_metadata.st_mode) or payload_metadata.st_size == 0:
            _finding(
                findings,
                "ERROR",
                "display-payload-invalid",
                f"Required {description} is not a nonempty ordinary file.",
                action="Reinstall Swan Song from a complete release ZIP.",
                path=relative,
                unsafe=not stat.S_ISREG(payload_metadata.st_mode),
            )
        else:
            valid_display_payloads += 1
    if valid_display_payloads == len(USER_VISIBLE_PAYLOADS):
        _finding(
            findings,
            "OK",
            "display-payloads",
            "Core icon, information text, and WonderSwan platform artwork are installed.",
        )

    return core_directory, documents


def _inspect_assets(
    root: Path,
    findings: list[Finding],
) -> dict[PurePosixPath, tuple[PurePosixPath, ...]]:
    common = _checked_path(root, ASSET_RELATIVE, findings)
    games: dict[PurePosixPath, list[PurePosixPath]] = {}
    if common is None:
        return {}
    if not common.exists() or not common.is_dir():
        _finding(
            findings,
            "ERROR",
            "assets-missing",
            f"Game directory /{ASSET_RELATIVE} is missing.",
            action="Create it and place your legally obtained .ws/.wsc files there.",
            path=ASSET_RELATIVE,
        )
        return {}

    platform_relative = PurePosixPath("Assets/wonderswan")
    platform = _checked_path(root, platform_relative, findings)
    if platform is not None and platform.is_dir():
        platform_files = _scan_tree(root, platform, platform_relative, findings)
        files = [
            (PurePosixPath(*relative.parts[1:]), metadata)
            for relative, metadata in platform_files
            if relative.parts and relative.parts[0] == "common"
        ]
        misplaced_games = [
            relative
            for relative, _metadata in platform_files
            if relative.suffix.lower() in {".ws", ".wsc"}
            and (not relative.parts or relative.parts[0] != "common")
        ]
        if misplaced_games:
            _finding(
                findings,
                "WARN",
                "game-misplaced",
                f"Found {len(misplaced_games)} game file(s) outside Assets/wonderswan/common.",
                action="Move them below /Assets/wonderswan/common so Swan Song and save mirroring use the documented path.",
                path=platform_relative,
            )
    else:
        files = _scan_tree(root, common, ASSET_RELATIVE, findings)
    pc2_count = 0
    for relative, metadata in files:
        suffix = relative.suffix.lower()
        if suffix in {".ws", ".wsc"}:
            if not (
                MIN_ROM_BYTES <= metadata.st_size <= MAX_ROM_BYTES
                and metadata.st_size % ROM_BANK_BYTES == 0
            ):
                _finding(
                    findings,
                    "ERROR",
                    "game-size",
                    (
                        f"WonderSwan game file is {metadata.st_size:,} bytes; ROMs must "
                        "be 64 KiB through 16 MiB in whole 64 KiB banks."
                    ),
                    action=(
                        "Replace it with a complete, headerless .ws/.wsc "
                        "cartridge dump."
                    ),
                    path=ASSET_RELATIVE / relative,
                )
                continue
            preset = preset_relative_path(relative.as_posix())
            games.setdefault(preset, []).append(relative)
        elif suffix == ".pc2":
            pc2_count += 1
    collisions = {key: value for key, value in games.items() if len(value) > 1}
    if collisions:
        examples = ", ".join(key.as_posix() for key in sorted(collisions)[:3])
        _finding(
            findings,
            "ERROR",
            "preset-name-collision",
            f"{len(collisions)} game stem(s) map to the same per-game preset: {examples}.",
            action="Rename one of each same-folder .ws/.wsc pair before creating presets.",
        )
    if pc2_count:
        _finding(
            findings,
            "WARN",
            "pc2-unsupported",
            f"Found {pc2_count} .pc2 file(s); Swan Song supports only .ws and .wsc games.",
        )
    _finding(
        findings,
        "OK" if games else "INFO",
        "games-found",
        f"Found {sum(len(value) for value in games.values())} WonderSwan game file(s) under /{ASSET_RELATIVE}.",
        action="Add legally obtained .ws/.wsc files here." if not games else "",
        path=ASSET_RELATIVE,
    )
    return {key: tuple(value) for key, value in games.items()}


def _inspect_preset_kind(
    root: Path,
    root_descriptor: int,
    kind: str,
    games: dict[PurePosixPath, tuple[PurePosixPath, ...]],
    findings: list[Finding],
) -> frozenset[PurePosixPath]:
    base_relative = PurePosixPath("Presets") / CORE_ID / kind
    base = _checked_path(root, base_relative, findings)
    if base is None or not base.exists():
        return frozenset()
    if not base.is_dir():
        _finding(
            findings,
            "ERROR",
            "preset-root-invalid",
            f"Per-game {kind} preset root is not a directory.",
            path=base_relative,
            unsafe=True,
        )
        return frozenset()
    files = _scan_tree(root, base, base_relative, findings)
    result: set[PurePosixPath] = set()
    outside = 0
    orphan = 0
    for relative, _metadata in files:
        if relative.suffix.lower() != ".json":
            continue
        if tuple(relative.parts[:2]) != (PLATFORM_ID, "common"):
            outside += 1
            continue
        result.add(relative)
        path = base / Path(*relative.parts)
        try:
            document = _read_json_file(
                root_descriptor, base_relative / relative
            )
            if kind == "Interact":
                validator._validate_interact(document, (base_relative / relative).as_posix())
                variables = document["interact"]["variables"]
                if not any(item.get("id") == 46 for item in variables):
                    raise ValueError("per-game menu replaces the core menu but lacks Control Layout")
            else:
                validator._validate_input(document, (base_relative / relative).as_posix())
        except (DoctorError, KeyError, TypeError, ValueError) as error:
            _finding(
                findings,
                "ERROR",
                "preset-invalid",
                f"Invalid per-game {kind} preset: {error}",
                action="Regenerate it with pocket_per_game_preset.py or remove it after making a backup.",
                path=base_relative / relative,
            )
        if relative not in games:
            orphan += 1
    if outside:
        _finding(
            findings,
            "WARN",
            "preset-path",
            f"Found {outside} {kind} preset(s) outside the documented wonderswan/common mirror.",
            action="Move them to the path that mirrors the slot-0 game asset.",
            path=base_relative,
        )
    if orphan:
        _finding(
            findings,
            "INFO",
            "preset-orphan",
            f"Found {orphan} {kind} preset(s) without a matching game currently on this SD card; this can be intentional.",
            path=base_relative,
        )
    return frozenset(result)


def _inspect_legacy(root: Path, findings: list[Finding]) -> None:
    old_core = _checked_path(root, PurePosixPath("Cores") / LEGACY_CORE_ID, findings)
    if old_core is not None and old_core.exists():
        _finding(
            findings,
            "INFO",
            "legacy-core-installed",
            f"The older {LEGACY_CORE_ID} core is installed side by side; this is supported.",
            action="Keep the folders separate; do not rename either core.",
            path=PurePosixPath("Cores") / LEGACY_CORE_ID,
        )

    for namespace in ("Settings", "Presets"):
        relative = PurePosixPath(namespace) / LEGACY_CORE_ID
        path = _checked_path(root, relative, findings)
        if path is not None and path.exists():
            if not path.is_dir():
                _finding(
                    findings,
                    "ERROR",
                    "legacy-namespace-unsafe",
                    f"Legacy {namespace} namespace is not an ordinary directory.",
                    path=relative,
                    unsafe=True,
                )
            else:
                _finding(
                    findings,
                    "WARN",
                    f"legacy-{namespace.lower()}",
                    f"Legacy {namespace} data exists under {LEGACY_CORE_ID} and is not used by Swan Song.",
                    action="Preview --migrate-legacy, then add --apply only after reviewing the no-clobber plan.",
                    path=relative,
                )

    old_save_relative = PurePosixPath("Saves/wonderswan") / LEGACY_CORE_ID
    old_save = _checked_path(root, old_save_relative, findings)
    if old_save is not None and old_save.exists():
        if not old_save.is_dir():
            _finding(
                findings,
                "ERROR",
                "legacy-save-unsafe",
                "Legacy console-save namespace is not an ordinary directory.",
                path=old_save_relative,
                unsafe=True,
            )
        else:
            exact = 0
            for name, size in CONSOLE_SAVE_CONTRACT.items():
                candidate = old_save / name
                if candidate.exists() and not candidate.is_symlink():
                    metadata = candidate.lstat()
                    if stat.S_ISREG(metadata.st_mode) and metadata.st_size == size:
                        exact += 1
            _finding(
                findings,
                "WARN",
                "legacy-console-saves",
                f"Legacy console EEPROM namespace exists ({exact}/2 expected files have exact sizes).",
                action="Use --migrate-legacy to preview a copy; the source is never moved and destinations are never overwritten.",
                path=old_save_relative,
            )

    current_save_base = PurePosixPath("Saves/wonderswan") / CORE_ID
    for name, size in CONSOLE_SAVE_CONTRACT.items():
        relative = current_save_base / name
        path = _checked_path(root, relative, findings)
        if path is None or not path.exists():
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != size:
            _finding(
                findings,
                "ERROR",
                "console-save-invalid",
                f"Existing {name} is not an ordinary {size}-byte file. It was not changed.",
                action="Back it up before attempting any manual recovery.",
                path=relative,
                unsafe=not stat.S_ISREG(metadata.st_mode),
            )


def _inspect_cartridge_save_namespaces(root: Path, findings: list[Finding]) -> None:
    """Detect legacy shared cartridge saves without opening ROM or save data."""

    shared_relative = PurePosixPath("Saves/wonderswan/common")
    shared = _checked_path(root, shared_relative, findings)
    if shared is None or not shared.exists():
        return
    if not shared.is_dir():
        _finding(
            findings,
            "ERROR",
            "shared-cartridge-save-root-invalid",
            "The legacy shared cartridge-save path is not an ordinary directory.",
            path=shared_relative,
            unsafe=True,
        )
        return

    shared_saves = sorted(
        relative
        for relative, _metadata in _scan_tree(
            root, shared, shared_relative, findings
        )
        if relative.suffix.lower() == ".sav"
    )
    if not shared_saves:
        return

    missing_destination = 0
    destination_base = PurePosixPath("Saves/wonderswan") / CORE_ID
    for relative in shared_saves:
        destination_relative = destination_base / relative
        destination = _checked_path(root, destination_relative, findings)
        if destination is None:
            continue
        if not destination.exists():
            missing_destination += 1
        elif not stat.S_ISREG(destination.lstat().st_mode):
            _finding(
                findings,
                "ERROR",
                "cartridge-save-destination-invalid",
                "A Swan Song cartridge-save destination is not an ordinary file.",
                path=destination_relative,
                unsafe=True,
            )

    _finding(
        findings,
        "WARN" if missing_destination else "INFO",
        "shared-cartridge-saves",
        (
            f"Found {len(shared_saves)} legacy shared .sav file(s); "
            f"{missing_destination} have no same-path file in Swan Song's core-specific "
            "save namespace. Contents were not read."
        ),
        action=(
            "Make an SD backup, then preview the ROM-aware helper: "
            "python3 scripts/migrate_cartridge_save_namespace.py --sd-root <SD> --all. "
            "Do not copy these files by hand; save layouts can differ."
            if missing_destination
            else "Keep the shared originals until the migrated saves are verified on Pocket."
        ),
        path=shared_relative,
    )


def audit_sd(sd_root: Path) -> DoctorReport:
    root, root_descriptor, root_identity = _root(sd_root)
    findings: list[Finding] = []
    try:
        core_directory, _documents = _validate_definitions(
            root, root_descriptor, findings
        )
        games = _inspect_assets(root, findings)
        interact = _inspect_preset_kind(
            root, root_descriptor, "Interact", games, findings
        )
        input_presets = _inspect_preset_kind(
            root, root_descriptor, "Input", games, findings
        )
        _inspect_legacy(root, findings)
        _inspect_cartridge_save_namespaces(root, findings)
        try:
            _verify_bound_root(root, root_descriptor, root_identity)
        except PresetError as error:
            raise DoctorError(f"SD root changed during audit: {error}") from error
    finally:
        os.close(root_descriptor)

    mirrored = len(interact | input_presets)
    interact_only = interact - input_presets
    input_only = input_presets - interact
    _finding(
        findings,
        "INFO",
        "preset-summary",
        (
            f"Per-game mirrors: {len(interact)} Interact, {len(input_presets)} Input, "
            f"covering {mirrored}/{len(games)} game stem(s) "
            f"({len(interact_only)} Interact-only, {len(input_only)} Input-only)."
        ),
        action=(
            "Run with --fix-presets to preview creation of default per-game settings."
            if len(games) > mirrored
            else ""
        ),
    )
    if interact_only or input_only:
        _finding(
            findings,
            "INFO",
            "preset-one-sided",
            (
                "One-sided per-game overrides can be intentional; the Doctor will not "
                "overwrite them or infer a missing counterpart."
            ),
            action=(
                "If a generator was interrupted, rerun it only after backing up and "
                "reviewing the existing preset."
            ),
        )
    rank = {"ERROR": 0, "WARN": 1, "INFO": 2, "OK": 3}
    ordered = tuple(
        sorted(findings, key=lambda item: (rank[item.severity], item.code, item.path, item.message))
    )
    return DoctorReport(
        root=root,
        root_identity=root_identity,
        findings=ordered,
        inventory=Inventory(games, interact, input_presets, core_directory),
    )


def plan_presets(report: DoctorReport) -> PresetPlan:
    if report.unsafe:
        raise DoctorError("unsafe paths block every repair; resolve the ERROR findings first")
    definitions = report.inventory.core_directory
    if definitions is None or not definitions.is_dir():
        raise DoctorError("a valid Swan Song core installation is required to create presets")
    definitions_metadata = definitions.lstat()
    if not stat.S_ISDIR(definitions_metadata.st_mode):
        raise DoctorError("the installed definitions path is not an ordinary directory")
    definitions_identity = (
        definitions_metadata.st_dev,
        definitions_metadata.st_ino,
    )
    try:
        build_interact_document(
            definitions,
            PresetOptions(),
            expected_definitions_identity=definitions_identity,
        )
        build_input_document(
            definitions,
            expected_definitions_identity=definitions_identity,
        )
    except PresetError as error:
        raise DoctorError(f"installed definitions cannot generate presets: {error}") from error

    items: list[PresetPlanItem] = []
    for preset, assets in sorted(report.inventory.games_by_preset.items()):
        if len(assets) != 1:
            raise DoctorError(f"ambiguous preset mirror for {preset}")
        if preset in report.inventory.interact_presets or preset in report.inventory.input_presets:
            continue
        interact = PurePosixPath("Presets") / CORE_ID / "Interact" / preset
        input_path = PurePosixPath("Presets") / CORE_ID / "Input" / preset
        for destination in (interact, input_path):
            absolute = report.root / Path(*destination.parts)
            if absolute.exists() or absolute.is_symlink():
                raise DoctorError(f"preset destination already exists: /{destination}")
            current = report.root
            for component in destination.parts[:-1]:
                current = current / component
                if current.is_symlink():
                    raise DoctorError(f"preset destination contains a symlink: {current}")
                if current.exists() and not current.is_dir():
                    raise DoctorError(f"preset destination parent is not a directory: {current}")
        items.append(PresetPlanItem(assets[0], interact, input_path))
    return PresetPlan(
        report.root,
        report.root_identity,
        definitions,
        definitions_identity,
        tuple(items),
    )


def apply_presets(plan: PresetPlan) -> tuple[PurePosixPath, ...]:
    root, root_descriptor, root_identity = _root(plan.root)
    os.close(root_descriptor)
    if root != plan.root or root_identity != plan.root_identity:
        raise DoctorError("SD root is not the directory used for the preset plan")
    current = audit_sd(plan.root)
    refreshed = plan_presets(current)
    if refreshed != plan:
        raise DoctorError("SD card or preset plan changed after preflight")
    written: list[PurePosixPath] = []
    for item in plan.items:
        try:
            result = generate_presets(
                sd_root=plan.root,
                asset=item.asset.as_posix(),
                definitions=plan.definitions,
                options=PresetOptions(),
                expected_root_identity=plan.root_identity,
                expected_definitions_identity=plan.definitions_identity,
            )
        except PresetError as error:
            if written:
                raise DoctorError(
                    f"preset apply stopped after {len(written)} preset file(s) "
                    f"were already applied in verified pairs: {error}"
                ) from error
            raise DoctorError(
                f"preset apply stopped before any preset pair committed: {error}"
            ) from error
        written.extend(
            (
                PurePosixPath(result.interact_path.relative_to(plan.root).as_posix()),
                PurePosixPath(result.input_path.relative_to(plan.root).as_posix()),
            )
        )
    return tuple(written)


def _render(
    report: DoctorReport,
    *,
    fix_lines: Iterable[str] = (),
    applied: bool = False,
) -> str:
    if report.errors:
        result = "NEEDS ATTENTION"
    elif report.warnings:
        result = "READY WITH NOTES"
    else:
        result = "READY"
    lines = [
        (
            "Swan Song Doctor — SELECTED FIXES APPLIED"
            if applied
            else "Swan Song Doctor — READ ONLY (NO CONTENT OR NAMESPACE WRITES)"
        ),
        f"SD root: {report.root}",
        f"Result: {result} ({report.errors} errors, {report.warnings} warnings)",
    ]
    for item in report.findings:
        location = f" /{item.path}" if item.path else ""
        lines.append(f"[{item.severity}] {item.message}{location}")
        if item.action:
            lines.append(f"  Next: {item.action}")
    lines.extend(fix_lines)
    lines.append("No game contents were read, hashed, copied, or uploaded.")
    lines.append(
        "ROM filenames, file types, and sizes were inspected locally; reads may update access-time metadata."
    )
    return "\n".join(lines)


def _json_report(report: DoctorReport, *, fixes: dict[str, object]) -> str:
    document = {
        "doctor": {
            "magic": "SWAN_SONG_DOCTOR_V1",
            "mode": "read-only" if not fixes.get("applied") else "applied-selected-fixes",
            "write_policy": (
                "no-content-or-namespace-writes"
                if not fixes.get("applied")
                else "selected-fixes-applied"
            ),
            "sd_root": str(report.root),
            "errors": report.errors,
            "warnings": report.warnings,
            "unsafe": report.unsafe,
            "findings": [
                {
                    "severity": item.severity,
                    "code": item.code,
                    "path": item.path,
                    "message": item.message,
                    "action": item.action,
                    "unsafe": item.unsafe,
                }
                for item in report.findings
            ],
            "fixes": fixes,
        }
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check a Pocket SD card for Swan Song install, asset, "
            "preset, and legacy-namespace problems. By default it performs no "
            "content or namespace writes; reads may update access times."
        )
    )
    parser.add_argument("--sd-root", required=True, type=Path)
    parser.add_argument(
        "--fix-presets",
        action="store_true",
        help="preview creation of missing default per-game Interact/Input presets",
    )
    parser.add_argument(
        "--migrate-legacy",
        action="store_true",
        help=f"preview no-clobber user-data copies from {LEGACY_CORE_ID}",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply only the explicitly selected and fully preflighted fixes",
    )
    parser.add_argument("--json", action="store_true", help="emit stable JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.apply and not (arguments.fix_presets or arguments.migrate_legacy):
        print("swan_song_doctor.py: --apply requires an explicit fix flag", file=sys.stderr)
        return 2
    try:
        report = audit_sd(arguments.sd_root)
        if (arguments.fix_presets or arguments.migrate_legacy) and report.unsafe:
            raise DoctorError("unsafe path findings block every repair")

        preset_plan = plan_presets(report) if arguments.fix_presets else None
        migration_plan: MigrationPlan | None = None
        if arguments.migrate_legacy:
            try:
                migration_plan = plan_migration(report.root)
            except MigrationError as error:
                raise DoctorError(f"legacy migration is not safely available: {error}") from error

        if preset_plan is not None and migration_plan is not None:
            preset_destinations = {
                item.interact for item in preset_plan.items
            } | {item.input for item in preset_plan.items}
            migration_destinations = {item.destination for item in migration_plan.files}
            overlap = preset_destinations & migration_destinations
            if overlap:
                names = ", ".join(f"/{path}" for path in sorted(overlap))
                raise DoctorError(
                    "selected fixes target the same files; migrate legacy data first, "
                    f"then rerun the doctor: {names}"
                )

        fix_lines: list[str] = []
        fixes: dict[str, object] = {
            "applied": False,
            "preset_files": 0 if preset_plan is None else len(preset_plan.items) * 2,
            "legacy_files": 0 if migration_plan is None else len(migration_plan.copies),
        }
        if arguments.apply:
            migration_result: MigrationResult | None = None
            if migration_plan is not None:
                migration_result = apply_migration(migration_plan)
            try:
                preset_written = (
                    apply_presets(preset_plan) if preset_plan is not None else ()
                )
            except DoctorError as error:
                copied = 0 if migration_result is None else len(migration_result.copied)
                if copied:
                    raise DoctorError(
                        f"legacy migration already applied {copied} no-clobber "
                        f"copy/copies; preset repair then failed: {error}"
                    ) from error
                raise
            fixes = {
                "applied": True,
                "preset_files": len(preset_written),
                "legacy_files": 0 if migration_result is None else len(migration_result.copied),
            }
            fix_lines.append(
                f"APPLIED: {fixes['preset_files']} preset file(s), "
                f"{fixes['legacy_files']} no-clobber legacy copy/copies."
            )
            report = audit_sd(arguments.sd_root)
        elif preset_plan is not None or migration_plan is not None:
            fix_lines.append(
                f"FIX PLAN ONLY: {fixes['preset_files']} new preset file(s), "
                f"{fixes['legacy_files']} no-clobber legacy copy/copies."
            )
            fix_lines.append("Review the plan, then add --apply to perform only these fixes.")

        print(
            _json_report(report, fixes=fixes)
            if arguments.json
            else _render(report, fix_lines=fix_lines, applied=bool(fixes["applied"]))
        )
        return 1 if report.errors else 0
    except (DoctorError, MigrationError, OSError) as error:
        print(f"swan_song_doctor.py: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
