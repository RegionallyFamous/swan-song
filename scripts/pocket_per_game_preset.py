#!/usr/bin/env python3
"""Generate APF per-asset presets for the Swan Song WonderSwan core.

The files contain only APF menu definitions.  The selected ROM is never opened,
hashed, copied, catalogued, or named inside either JSON document; its path is
used solely to derive the location APF documents for per-asset overrides.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import errno
import json
import os
import pathlib
import re
import secrets
import stat
import sys
from dataclasses import dataclass
from typing import Any


DEFAULT_CORE_ID = "RegionallyFamous.SwanSong"
DEFAULT_DEFINITIONS = (
    pathlib.Path(__file__).resolve().parents[1]
    / "dist"
    / "Cores"
    / DEFAULT_CORE_ID
)
ASSET_PREFIX = ("Assets", "wonderswan", "common")
ROM_EXTENSIONS = {".ws", ".wsc"}
CORE_ID_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_-]*\.[A-Za-z0-9][A-Za-z0-9_-]*\Z"
)

# Stable interact IDs and BRIDGE addresses are part of this core's APF contract.
SETTING_CONTRACT = {
    "cpu_turbo": (14, "check", "0x110", {0, 1}),
    "triple_buffer": (41, "check", "0x200", {0, 1}),
    "flicker": (42, "list", "0x204", {0, 1, 2, 3}),
    "orientation": (43, "list", "0x208", {0, 1, 2}),
    "landscape_180": (44, "check", "0x20C", {0, 1}),
    "color_profile": (45, "list", "0x210", {0, 1}),
    "control_layout": (46, "list", "0x214", {0, 1, 2}),
    "fast_forward_audio": (81, "check", "0x300", {0, 1}),
}

ORIENTATION_VALUES = {"auto": 0, "horizontal": 1, "vertical": 2}
CONTROL_LAYOUT_VALUES = {"auto": 0, "horizontal": 1, "vertical": 2}
# "3-frame" remains an explicit compatibility alias for the old menu wording.
# Mode 2 is a finite three-frame LCD-response model, not infinite persistence.
FLICKER_VALUES = {
    "off": 0,
    "2-frame": 1,
    "persistence": 2,
    "3-frame": 2,
    "complete-60.9": 3,
}
COLOR_PROFILE_VALUES = {"raw": 0, "ares": 1}
SWITCH_VALUES = {"off": 0, "on": 1}

EXPECTED_INPUT_MAPPINGS = (
    (0, "Horz A/Vert X3", "pad_btn_a"),
    (1, "Horz B/Vert X4", "pad_btn_b"),
    (2, "Horz Y3/Vert X2", "pad_btn_x"),
    (3, "Horz Y4/Vert X1", "pad_btn_y"),
    (10, "Horz Y1/Vert A", "pad_trig_l"),
    (11, "Horz Y2/Vert B", "pad_trig_r"),
    (20, "Start", "pad_btn_start"),
    (30, "Fast Forward", "pad_btn_select"),
)


class PresetError(ValueError):
    """An invalid or unsafe preset request."""


@dataclass(frozen=True)
class PresetOptions:
    orientation: str = "auto"
    control_layout: str = "auto"
    landscape_180: str = "off"
    color_profile: str = "raw"
    triple_buffer: str = "on"
    flicker: str = "off"
    cpu_turbo: str = "off"
    fast_forward_audio: str = "on"
    controls: str = "per-game"


@dataclass(frozen=True)
class PresetResult:
    interact_path: pathlib.Path
    input_path: pathlib.Path | None


@dataclass
class _PreparedOutput:
    destination: pathlib.Path
    relative: pathlib.PurePosixPath
    payload: bytes
    parent_descriptor: int
    parent_identity: tuple[int, int]
    original_payload: bytes | None
    original_identity: tuple[int, int] | None
    temporary_name: str | None = None
    temporary_identity: tuple[int, int] | None = None
    backup_name: str | None = None
    installed_identity: tuple[int, int] | None = None


def _read_json(
    path: pathlib.Path,
    envelope: str,
    *,
    expected_parent_identity: tuple[int, int] | None = None,
) -> dict[str, Any]:
    parent_descriptor: int | None = None
    try:
        parent_descriptor = os.open(path.parent, _directory_flags())
        parent_metadata = os.stat(path.parent, follow_symlinks=False)
        opened_parent_identity = _identity(os.fstat(parent_descriptor))
        if opened_parent_identity != _identity(parent_metadata):
            raise PresetError(f"definition directory identity changed: {path.parent}")
        if (
            expected_parent_identity is not None
            and opened_parent_identity != expected_parent_identity
        ):
            raise PresetError(
                f"definition directory is not the directory used for the plan: {path.parent}"
            )
        snapshot = _read_regular_snapshot_at(
            parent_descriptor, path.name, maximum=1024 * 1024
        )
        if snapshot is None:
            raise PresetError(f"definition is missing: {path}")
        document = json.loads(snapshot[0].decode("utf-8"))
    except (OSError, PresetError, UnicodeError, json.JSONDecodeError) as error:
        raise PresetError(f"cannot read valid JSON from {path}: {error}") from error
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    if not isinstance(document, dict) or set(document) != {envelope}:
        raise PresetError(f"{path} must contain only the {envelope!r} envelope")
    body = document[envelope]
    if not isinstance(body, dict) or body.get("magic") != "APF_VER_1":
        raise PresetError(f"{path} must contain {envelope}.magic = APF_VER_1")
    return document


def _canonical_asset_parts(asset: str) -> tuple[str, ...]:
    if not isinstance(asset, str) or not asset:
        raise PresetError("asset path must not be empty")
    if "\\" in asset:
        raise PresetError("asset path must use forward slashes")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in asset):
        raise PresetError("asset path contains a control character")

    pocket_absolute = asset.startswith("/")
    normalized = asset[1:] if pocket_absolute else asset
    raw_parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise PresetError("asset path has an empty, current, or parent component")

    if raw_parts[0] == "Assets":
        if tuple(raw_parts[:3]) != ASSET_PREFIX:
            raise PresetError(
                "asset must be below /Assets/wonderswan/common/ for slot 0"
            )
        relative = raw_parts[3:]
    else:
        if pocket_absolute:
            raise PresetError(
                "absolute asset paths must start with /Assets/wonderswan/common/"
            )
        relative = raw_parts

    if not relative:
        raise PresetError("asset path must name a WonderSwan ROM")
    filename = relative[-1]
    suffix = pathlib.PurePosixPath(filename).suffix.lower()
    if suffix not in ROM_EXTENSIONS or filename[: -len(suffix)] == "":
        raise PresetError("asset filename must end in .ws or .wsc")
    return (*ASSET_PREFIX[1:], *relative)


def preset_relative_path(asset: str) -> pathlib.PurePosixPath:
    """Return the APF-documented path below the Interact/Input directory."""

    parts = list(_canonical_asset_parts(asset))
    final = pathlib.PurePosixPath(parts[-1])
    parts[-1] = final.with_suffix(".json").name
    return pathlib.PurePosixPath(*parts)


def _validate_core_id(core_id: str) -> None:
    if not CORE_ID_PATTERN.fullmatch(core_id):
        raise PresetError(
            "core ID must be AuthorName.CoreName using letters, digits, _ or -"
        )


def _variables_by_id(document: dict[str, Any], source: pathlib.Path) -> dict[int, dict[str, Any]]:
    variables = document["interact"].get("variables")
    if not isinstance(variables, list):
        raise PresetError(f"{source} interact.variables must be an array")
    result: dict[int, dict[str, Any]] = {}
    for index, variable in enumerate(variables):
        if not isinstance(variable, dict):
            raise PresetError(f"{source} interact.variables[{index}] must be an object")
        identifier = variable.get("id")
        if isinstance(identifier, bool) or not isinstance(identifier, int):
            raise PresetError(f"{source} interact.variables[{index}].id must be an integer")
        if identifier in result:
            raise PresetError(f"{source} has duplicate interact ID {identifier}")
        result[identifier] = variable
    return result


def build_interact_document(
    definitions: pathlib.Path,
    options: PresetOptions,
    *,
    expected_definitions_identity: tuple[int, int] | None = None,
) -> dict[str, Any]:
    source = definitions / "interact.json"
    document = _read_json(
        source,
        "interact",
        expected_parent_identity=expected_definitions_identity,
    )
    generated = copy.deepcopy(document)
    variables = _variables_by_id(generated, source)

    selected = {
        "cpu_turbo": SWITCH_VALUES[options.cpu_turbo],
        "triple_buffer": SWITCH_VALUES[options.triple_buffer],
        "flicker": FLICKER_VALUES[options.flicker],
        "orientation": ORIENTATION_VALUES[options.orientation],
        "control_layout": CONTROL_LAYOUT_VALUES[options.control_layout],
        "landscape_180": SWITCH_VALUES[options.landscape_180],
        "color_profile": COLOR_PROFILE_VALUES[options.color_profile],
        "fast_forward_audio": SWITCH_VALUES[options.fast_forward_audio],
    }
    if options.orientation == "vertical" and options.landscape_180 == "on":
        raise PresetError(
            "Landscape 180 degrees has no effect in forced vertical mode; "
            "choose --landscape-180 off"
        )

    for setting, (identifier, kind, address, allowed) in SETTING_CONTRACT.items():
        variable = variables.get(identifier)
        if variable is None:
            raise PresetError(f"{source} is missing required interact ID {identifier}")
        if variable.get("type") != kind or variable.get("address") != address:
            raise PresetError(
                f"{source} interact ID {identifier} no longer matches the "
                f"expected {kind} at {address}"
            )
        if (
            variable.get("persist") is not True
            or variable.get("writeonly", False) is not False
        ):
            raise PresetError(
                f"{source} interact ID {identifier} must remain persistent and readable"
            )
        if variable.get("defaultval") not in allowed:
            raise PresetError(
                f"{source} interact ID {identifier} has an unsupported default value"
            )
        if kind == "list":
            options_list = variable.get("options")
            if not isinstance(options_list, list) or any(
                not isinstance(option, dict) for option in options_list
            ):
                raise PresetError(
                    f"{source} interact ID {identifier} options must be objects"
                )
            option_values = [option.get("value") for option in options_list]
            if len(option_values) != len(set(option_values)) or set(option_values) != allowed:
                raise PresetError(
                    f"{source} interact ID {identifier} no longer exposes the "
                    "expected option values"
                )
        elif variable.get("value") != 1:
            raise PresetError(
                f"{source} interact ID {identifier} check value must remain 1"
            )
        value = selected[setting]
        if value not in allowed:
            raise PresetError(f"unsupported {setting} value {value}")
        variable["defaultval"] = value
    return generated


def build_input_document(
    definitions: pathlib.Path,
    *,
    expected_definitions_identity: tuple[int, int] | None = None,
) -> dict[str, Any]:
    source = definitions / "input.json"
    document = _read_json(
        source,
        "input",
        expected_parent_identity=expected_definitions_identity,
    )
    controllers = document["input"].get("controllers")
    if not isinstance(controllers, list) or len(controllers) != 1:
        raise PresetError(f"{source} must define exactly one controller")
    controller = controllers[0]
    if not isinstance(controller, dict) or controller.get("type") != "default":
        raise PresetError(f"{source} controller type must be default")
    mappings = controller.get("mappings")
    if not isinstance(mappings, list):
        raise PresetError(f"{source} controller mappings must be an array")
    actual = []
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise PresetError(f"{source} contains a non-object input mapping")
        actual.append((mapping.get("id"), mapping.get("name"), mapping.get("key")))
    if tuple(actual) != EXPECTED_INPUT_MAPPINGS:
        raise PresetError(
            f"{source} no longer matches the eight verified WonderSwan mappings"
        )
    return copy.deepcopy(document)


def _json_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _sync_directory(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as error:
        unsupported = {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL)}
        if error.errno not in unsupported:
            raise


def _open_bound_root(
    requested: pathlib.Path,
) -> tuple[pathlib.Path, int, tuple[int, int]]:
    absolute = requested.absolute()
    try:
        descriptor = os.open(absolute, _directory_flags())
    except OSError as error:
        raise PresetError(
            f"SD root must be an existing, non-symlink directory: {requested}"
        ) from error
    try:
        opened = os.fstat(descriptor)
        root = absolute.resolve(strict=True)
        observed = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(opened.st_mode) or _identity(opened) != _identity(observed):
            raise PresetError("SD root identity changed during validation")
        return root, descriptor, _identity(opened)
    except Exception:
        os.close(descriptor)
        raise


def _verify_bound_root(
    root: pathlib.Path, descriptor: int, expected: tuple[int, int]
) -> None:
    try:
        observed = os.stat(root, follow_symlinks=False)
    except OSError as error:
        raise PresetError("SD root detached during preset transaction") from error
    if _identity(os.fstat(descriptor)) != expected or _identity(observed) != expected:
        raise PresetError("SD root identity changed during preset transaction")


def _case_safe_name_at(directory: int, name: str) -> bool:
    matches = [entry for entry in os.listdir(directory) if entry.casefold() == name.casefold()]
    if len(matches) > 1 or (matches and matches[0] != name):
        observed = matches[0] if matches else name
        raise PresetError(f"case-colliding preset path component: {observed}")
    return bool(matches)


def _open_parent_at(
    root_descriptor: int,
    relative: pathlib.PurePosixPath,
    *,
    create: bool,
) -> int | None:
    current = os.dup(root_descriptor)
    walked: list[str] = []
    try:
        for component in relative.parts[:-1]:
            walked.append(component)
            exists = _case_safe_name_at(current, component)
            if not exists:
                if not create:
                    os.close(current)
                    return None
                try:
                    os.mkdir(component, 0o755, dir_fd=current)
                except FileExistsError:
                    pass
                else:
                    _sync_directory(current)
                _case_safe_name_at(current, component)
            metadata = os.stat(component, dir_fd=current, follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode):
                raise PresetError(
                    "preset output parent is not a nonsymlink directory: "
                    + "/".join(walked)
                )
            try:
                child = os.open(component, _directory_flags(), dir_fd=current)
            except OSError as error:
                raise PresetError(
                    "preset output parent became unsafe: " + "/".join(walked)
                ) from error
            if _identity(os.fstat(child)) != _identity(metadata):
                os.close(child)
                raise PresetError(
                    "preset output parent identity changed: " + "/".join(walked)
                )
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def _read_regular_snapshot_at(
    directory: int, name: str, *, maximum: int | None = None
) -> tuple[bytes, tuple[int, int]] | None:
    if not _case_safe_name_at(directory, name):
        return None
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except OSError as error:
        raise PresetError(f"preset destination is unsafe: {name}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise PresetError(f"preset destination is not a regular file: {name}")
        payload = bytearray()
        limit = maximum if maximum is not None else max(before.st_size, 0) + 1
        while True:
            request = 1024 * 1024
            if maximum is not None:
                request = min(request, maximum + 1 - len(payload))
                if request <= 0:
                    raise PresetError(f"managed file exceeds {maximum} bytes: {name}")
            chunk = os.read(descriptor, request)
            if not chunk:
                break
            payload.extend(chunk)
            if maximum is not None and len(payload) > maximum:
                raise PresetError(f"managed file exceeds {maximum} bytes: {name}")
        after = os.fstat(descriptor)
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
            raise PresetError(f"managed file changed while being read: {name}")
        return bytes(payload), _identity(after)
    finally:
        os.close(descriptor)


def _rename_noreplace_at(
    source_directory: int,
    source: str,
    destination_directory: int,
    destination: str,
) -> None:
    """Atomically rename without replacing an existing destination."""

    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        function = getattr(library, "renameatx_np", None)
        flag = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        function = getattr(library, "renameat2", None)
        flag = 0x00000001  # RENAME_NOREPLACE
    else:
        function = None
        flag = 0
    if function is None:
        raise PresetError("target platform lacks atomic no-replace rename support")
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    result = function(
        source_directory,
        os.fsencode(source),
        destination_directory,
        os.fsencode(destination),
        flag,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL)}:
            raise PresetError(
                "target filesystem lacks atomic no-replace rename support"
            )
        raise OSError(error_number, os.strerror(error_number), destination)


def _allocate_temporary(item: _PreparedOutput) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for _ in range(32):
        name = f".swansong-{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=item.parent_descriptor)
        except FileExistsError:
            continue
        item.temporary_name = name
        item.temporary_identity = _identity(os.fstat(descriptor))
        try:
            view = memoryview(item.payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write while creating preset temporary")
                view = view[written:]
            os.fchmod(descriptor, 0o644)
            os.fsync(descriptor)
            item.temporary_identity = _identity(os.fstat(descriptor))
            _sync_directory(item.parent_descriptor)
            return
        finally:
            os.close(descriptor)
    raise PresetError(f"could not allocate a temporary preset for {item.relative}")


def _unlink_owned_at(directory: int, name: str, expected: tuple[int, int]) -> None:
    metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if _identity(metadata) != expected:
        raise PresetError(f"transaction artifact identity changed: {name}")
    os.unlink(name, dir_fd=directory)
    _sync_directory(directory)


def _restore_backup(item: _PreparedOutput) -> None:
    if item.backup_name is None:
        return
    _rename_noreplace_at(
        item.parent_descriptor,
        item.backup_name,
        item.parent_descriptor,
        item.relative.name,
    )
    item.backup_name = None
    _sync_directory(item.parent_descriptor)


def _rollback_outputs(prepared: list[_PreparedOutput]) -> list[str]:
    failures: list[str] = []
    for item in reversed(prepared):
        try:
            if item.installed_identity is not None:
                quarantine = f".swansong-{secrets.token_hex(16)}.rollback"
                _rename_noreplace_at(
                    item.parent_descriptor,
                    item.relative.name,
                    item.parent_descriptor,
                    quarantine,
                )
                snapshot = _read_regular_snapshot_at(item.parent_descriptor, quarantine)
                if (
                    snapshot is None
                    or snapshot[1] != item.installed_identity
                    or snapshot[0] != item.payload
                ):
                    try:
                        _rename_noreplace_at(
                            item.parent_descriptor,
                            quarantine,
                            item.parent_descriptor,
                            item.relative.name,
                        )
                    finally:
                        raise PresetError(
                            f"installed preset changed before rollback: {item.relative}"
                        )
                item.installed_identity = None
                _restore_backup(item)
                _unlink_owned_at(item.parent_descriptor, quarantine, snapshot[1])
            else:
                _restore_backup(item)
            if item.temporary_name is not None and item.temporary_identity is not None:
                _unlink_owned_at(
                    item.parent_descriptor,
                    item.temporary_name,
                    item.temporary_identity,
                )
                item.temporary_name = None
        except Exception as error:
            failures.append(f"{item.relative}: {type(error).__name__}: {error}")
    return failures


def generate_presets(
    *,
    sd_root: pathlib.Path,
    asset: str,
    definitions: pathlib.Path = DEFAULT_DEFINITIONS,
    core_id: str = DEFAULT_CORE_ID,
    options: PresetOptions = PresetOptions(),
    force: bool = False,
    expected_root_identity: tuple[int, int] | None = None,
    expected_definitions_identity: tuple[int, int] | None = None,
) -> PresetResult:
    _validate_core_id(core_id)
    if not definitions.is_dir():
        raise PresetError(f"core definitions directory does not exist: {definitions}")

    # Validate enum-like dataclass fields even when called as a library.
    choices = {
        "orientation": ORIENTATION_VALUES,
        "control_layout": CONTROL_LAYOUT_VALUES,
        "landscape_180": SWITCH_VALUES,
        "color_profile": COLOR_PROFILE_VALUES,
        "triple_buffer": SWITCH_VALUES,
        "flicker": FLICKER_VALUES,
        "cpu_turbo": SWITCH_VALUES,
        "fast_forward_audio": SWITCH_VALUES,
        "controls": {"per-game": 1, "inherit": 0},
    }
    for field, allowed in choices.items():
        value = getattr(options, field)
        if value not in allowed:
            raise PresetError(
                f"unsupported {field.replace('_', '-')} value {value!r}; "
                f"choose one of {', '.join(allowed)}"
            )

    relative = preset_relative_path(asset)
    interact_relative = pathlib.PurePosixPath("Presets") / core_id / "Interact" / relative
    input_relative = (
        pathlib.PurePosixPath("Presets") / core_id / "Input" / relative
        if options.controls == "per-game"
        else None
    )
    payloads = [
        (
            interact_relative,
            _json_bytes(
                build_interact_document(
                    definitions,
                    options,
                    expected_definitions_identity=expected_definitions_identity,
                )
            ),
        )
    ]
    if input_relative is not None:
        payloads.append(
            (
                input_relative,
                _json_bytes(
                    build_input_document(
                        definitions,
                        expected_definitions_identity=expected_definitions_identity,
                    )
                ),
            )
        )

    root, root_descriptor, root_identity = _open_bound_root(sd_root)
    if (
        expected_root_identity is not None
        and root_identity != expected_root_identity
    ):
        os.close(root_descriptor)
        raise PresetError("SD root is not the directory used for the preset plan")
    interact_path = root.joinpath(*interact_relative.parts)
    input_path = (
        root.joinpath(*input_relative.parts) if input_relative is not None else None
    )
    prepared: list[_PreparedOutput] = []
    committed = False
    transaction_error: BaseException | None = None
    try:
        # Prepare every destination before publishing either member of the pair.
        for output_relative, payload in payloads:
            parent_descriptor = _open_parent_at(
                root_descriptor, output_relative, create=True
            )
            assert parent_descriptor is not None
            try:
                parent_metadata = os.fstat(parent_descriptor)
                snapshot = _read_regular_snapshot_at(
                    parent_descriptor, output_relative.name
                )
                if snapshot is not None and not force:
                    raise PresetError(
                        f"preset already exists: {root.joinpath(*output_relative.parts)} "
                        "(use --force to replace it)"
                    )
            except Exception:
                os.close(parent_descriptor)
                raise
            prepared.append(
                _PreparedOutput(
                    destination=root.joinpath(*output_relative.parts),
                    relative=output_relative,
                    payload=payload,
                    parent_descriptor=parent_descriptor,
                    parent_identity=_identity(parent_metadata),
                    original_payload=None if snapshot is None else snapshot[0],
                    original_identity=None if snapshot is None else snapshot[1],
                )
            )

        for item in prepared:
            _allocate_temporary(item)

        for item in prepared:
            if item.original_identity is not None:
                item.backup_name = (
                    f".swansong-{secrets.token_hex(16)}.original"
                )
                _rename_noreplace_at(
                    item.parent_descriptor,
                    item.relative.name,
                    item.parent_descriptor,
                    item.backup_name,
                )
                backup = _read_regular_snapshot_at(
                    item.parent_descriptor, item.backup_name
                )
                if (
                    backup is None
                    or backup[1] != item.original_identity
                    or backup[0] != item.original_payload
                ):
                    _restore_backup(item)
                    raise PresetError(
                        f"preset changed after preflight: {item.destination}"
                    )
            assert item.temporary_name is not None
            assert item.temporary_identity is not None
            _rename_noreplace_at(
                item.parent_descriptor,
                item.temporary_name,
                item.parent_descriptor,
                item.relative.name,
            )
            item.temporary_name = None
            item.installed_identity = item.temporary_identity
            _sync_directory(item.parent_descriptor)

        _verify_bound_root(root, root_descriptor, root_identity)
        for item in prepared:
            current_parent = _open_parent_at(
                root_descriptor, item.relative, create=False
            )
            if current_parent is None:
                raise PresetError(
                    f"preset parent detached during transaction: {item.relative}"
                )
            try:
                if _identity(os.fstat(current_parent)) != item.parent_identity:
                    raise PresetError(
                        f"preset parent identity changed during transaction: {item.relative}"
                    )
                snapshot = _read_regular_snapshot_at(
                    current_parent, item.relative.name
                )
                if (
                    snapshot is None
                    or snapshot[1] != item.installed_identity
                    or snapshot[0] != item.payload
                ):
                    raise PresetError(
                        f"preset changed during transaction: {item.relative}"
                    )
            finally:
                os.close(current_parent)
        committed = True
    except BaseException as error:
        transaction_error = error
        rollback_failures = _rollback_outputs(prepared)
        if rollback_failures:
            raise PresetError(
                "preset transaction failed and rollback was incomplete: "
                + "; ".join(rollback_failures)
            ) from error
        if isinstance(error, FileExistsError):
            raise PresetError(
                f"preset destination was created concurrently: {error.filename}"
            ) from error
        raise
    finally:
        if committed:
            cleanup_failures: list[str] = []
            for item in prepared:
                if item.backup_name is None or item.original_identity is None:
                    continue
                try:
                    _unlink_owned_at(
                        item.parent_descriptor,
                        item.backup_name,
                        item.original_identity,
                    )
                    item.backup_name = None
                except Exception as error:
                    cleanup_failures.append(
                        f"{item.relative}: {type(error).__name__}: {error}"
                    )
            if cleanup_failures and transaction_error is None:
                transaction_error = PresetError(
                    "presets were installed and verified but cleanup was incomplete: "
                    + "; ".join(cleanup_failures)
                )
        for item in prepared:
            os.close(item.parent_descriptor)
        os.close(root_descriptor)
    if transaction_error is not None:
        raise transaction_error
    return PresetResult(interact_path=interact_path, input_path=input_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create path-mirrored APF Interact/Input presets for one WonderSwan ROM. "
            "The ROM is never opened or copied."
        )
    )
    parser.add_argument("--sd-root", required=True, type=pathlib.Path)
    parser.add_argument(
        "--asset",
        required=True,
        help=(
            "ROM path below Assets/wonderswan/common, or a full Pocket-style "
            "/Assets/wonderswan/common/... path"
        ),
    )
    parser.add_argument("--definitions", type=pathlib.Path, default=DEFAULT_DEFINITIONS)
    parser.add_argument("--core-id", default=DEFAULT_CORE_ID)
    parser.add_argument("--orientation", choices=ORIENTATION_VALUES, default="auto")
    parser.add_argument(
        "--control-layout",
        choices=CONTROL_LAYOUT_VALUES,
        default="auto",
        help=(
            "WonderSwan keypad mapping only; Auto follows the game's native "
            "horizontal/vertical mode without changing display orientation"
        ),
    )
    parser.add_argument("--landscape-180", choices=SWITCH_VALUES, default="off")
    parser.add_argument(
        "--color-profile", choices=COLOR_PROFILE_VALUES, default="raw"
    )
    parser.add_argument("--triple-buffer", choices=SWITCH_VALUES, default="on")
    parser.add_argument(
        "--motion-mode",
        "--lcd-response",
        "--flicker",
        dest="flicker",
        choices=FLICKER_VALUES,
        default="off",
        help=(
            "display motion mode; complete-60.9 selects experimental tear-free "
            "60.9 Hz output (--lcd-response/--flicker are compatibility aliases)"
        ),
    )
    parser.add_argument("--cpu-turbo", choices=SWITCH_VALUES, default="off")
    parser.add_argument(
        "--fast-forward-audio", choices=SWITCH_VALUES, default="on"
    )
    parser.add_argument(
        "--controls",
        choices=("per-game", "inherit"),
        default="per-game",
        help=(
            "per-game creates a per-asset APF Controls definition/namespace; "
            "it does not pre-remap buttons (remap them in Pocket OS). "
            "inherit creates no Input file"
        ),
    )
    parser.add_argument(
        "--force", action="store_true", help="replace existing generated preset files"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    options = PresetOptions(
        orientation=arguments.orientation,
        control_layout=arguments.control_layout,
        landscape_180=arguments.landscape_180,
        color_profile=arguments.color_profile,
        triple_buffer=arguments.triple_buffer,
        flicker=arguments.flicker,
        cpu_turbo=arguments.cpu_turbo,
        fast_forward_audio=arguments.fast_forward_audio,
        controls=arguments.controls,
    )
    try:
        result = generate_presets(
            sd_root=arguments.sd_root,
            asset=arguments.asset,
            definitions=arguments.definitions,
            core_id=arguments.core_id,
            options=options,
            force=arguments.force,
        )
    except PresetError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Interact: {result.interact_path}")
    if result.input_path is not None:
        print(f"Input: {result.input_path}")
    else:
        print("Input: inherited from the core (no file written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
