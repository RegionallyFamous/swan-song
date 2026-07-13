#!/usr/bin/env python3
"""Strict, offline validation for the Swan Song Analogue Pocket SD tree.

This is intentionally a release-profile validator, not a permissive APF parser.
Unknown files and unknown JSON members fail closed so a typo cannot silently ship.
The limits below come from Analogue's APF_VER_1 developer documentation.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any


CORE_RELATIVE = pathlib.PurePosixPath("Cores/agg23.WonderSwan")
PLATFORM_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_]{0,14}\Z")
HEX_PATTERN = re.compile(r"0[xX][0-9a-fA-F]+\Z")
VERSION_REQUIRED_PATTERN = re.compile(r"[0-9]+\.[0-9]+\Z")

REQUIRED_DIRECTORIES = {
    "Assets",
    "Assets/wonderswan",
    "Assets/wonderswan/common",
    "Cores",
    CORE_RELATIVE.as_posix(),
    "Platforms",
    "Platforms/_images",
}
REQUIRED_FILES = {
    *(f"{CORE_RELATIVE}/{name}" for name in (
        "audio.json",
        "core.json",
        "data.json",
        "info.txt",
        "input.json",
        "interact.json",
        "variants.json",
        "video.json",
    )),
    "Platforms/wonderswan.json",
    "Platforms/_images/wonderswan.bin",
}
OPTIONAL_FILES = {
    "Assets/wonderswan/common/.gitkeep",
    f"{CORE_RELATIVE}/icon.bin",
}
JSON_FILES = {
    "audio": f"{CORE_RELATIVE}/audio.json",
    "core": f"{CORE_RELATIVE}/core.json",
    "data": f"{CORE_RELATIVE}/data.json",
    "input": f"{CORE_RELATIVE}/input.json",
    "interact": f"{CORE_RELATIVE}/interact.json",
    "variants": f"{CORE_RELATIVE}/variants.json",
    "video": f"{CORE_RELATIVE}/video.json",
    "platform": "Platforms/wonderswan.json",
}
KEYCODES = {
    "pad_btn_a",
    "pad_btn_b",
    "pad_btn_x",
    "pad_btn_y",
    "pad_trig_l",
    "pad_trig_r",
    "pad_btn_start",
    "pad_btn_select",
}
DISPLAY_MODE_IDS = {
    0x10,
    0x20,
    0x21,
    0x22,
    0x23,
    0x30,
    0x31,
    0x32,
    0x40,
    0x41,
    0x42,
    0x51,
    0x52,
    0x61,
    0x62,
    0x63,
    0x71,
    0x72,
    0x81,
    0x82,
    0xE0,
    0xE1,
}


@dataclass(frozen=True)
class ValidatedDistribution:
    core_directory: pathlib.PurePosixPath
    bitstream_name: str
    chip32_name: str
    author: str
    shortname: str
    repository_url: str
    version: str
    release_date: str

    @property
    def core_id(self) -> str:
        return f"{self.author}.{self.shortname}"

    @property
    def recommended_archive_name(self) -> str:
        return (
            f"{self.author}.{self.shortname}_{self.version}_"
            f"{self.release_date}.zip"
        )


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{where} has a non-string member name")
    return value


def _array(value: Any, where: str, maximum: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{where} has {len(value)} entries; maximum is {maximum}")
    return value


def _keys(
    value: dict[str, Any],
    where: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - optional
    if missing:
        raise ValueError(f"{where} is missing members: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{where} has unknown members: {', '.join(sorted(unknown))}")


def _text(value: Any, where: str, maximum: int, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{where} must be a string")
    if nonempty and not value:
        raise ValueError(f"{where} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{where} exceeds {maximum} characters")
    if any(ord(character) < 0x20 for character in value):
        raise ValueError(f"{where} contains a control character")
    return value


def _boolean(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be a boolean")
    return value


def _integer(value: Any, where: str, maximum: int = 0xFFFFFFFF) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{where} must be an integer or hexadecimal string")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and HEX_PATTERN.fullmatch(value):
        result = int(value, 16)
    else:
        raise ValueError(f"{where} must be an integer or hexadecimal string")
    if not 0 <= result <= maximum:
        raise ValueError(f"{where} is outside 0..{maximum}")
    return result


def _filename(value: Any, where: str, maximum: int) -> str:
    result = _text(value, where, maximum)
    path = pathlib.PurePosixPath(result)
    if (
        "\\" in result
        or path.is_absolute()
        or len(path.parts) != 1
        or path.parts[0] in {".", ".."}
    ):
        raise ValueError(f"{where} must be a plain filename")
    return result


def _unique(values: list[Any], where: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{where} must be unique")


def _read_json(dist: pathlib.Path, relative: str) -> dict[str, Any]:
    path = dist / relative
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), relative)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON {relative}: {error}") from error


def _envelope(document: dict[str, Any], name: str, relative: str) -> dict[str, Any]:
    _keys(document, relative, {name})
    body = _object(document[name], f"{relative}.{name}")
    if body.get("magic") != "APF_VER_1":
        raise ValueError(f"{relative}.{name}.magic must be APF_VER_1")
    return body


def _validate_tree(dist: pathlib.Path) -> None:
    if not dist.is_dir():
        raise ValueError(f"distribution does not exist or is not a directory: {dist}")

    directories: set[str] = set()
    files: set[str] = set()
    folded: dict[str, str] = {}
    for path in dist.rglob("*"):
        relative = path.relative_to(dist).as_posix()
        if path.is_symlink():
            raise ValueError(f"distribution must not contain symlinks: {relative}")
        if "\\" in relative or any(ord(character) < 0x20 for character in relative):
            raise ValueError(f"unsafe distribution path: {relative!r}")
        previous = folded.setdefault(relative.casefold(), relative)
        if previous != relative:
            raise ValueError(f"case-insensitive path collision: {previous}, {relative}")
        if path.is_dir():
            directories.add(relative)
        elif path.is_file():
            files.add(relative)
        else:
            raise ValueError(f"distribution contains a special file: {relative}")

    missing_directories = REQUIRED_DIRECTORIES - directories
    extra_directories = directories - REQUIRED_DIRECTORIES
    missing_files = REQUIRED_FILES - files
    extra_files = files - REQUIRED_FILES - OPTIONAL_FILES
    if missing_directories:
        raise ValueError(
            "distribution is missing directories: "
            + ", ".join(sorted(missing_directories))
        )
    if extra_directories:
        raise ValueError(
            "distribution has non-release directories: "
            + ", ".join(sorted(extra_directories))
        )
    if missing_files:
        raise ValueError(
            "distribution is missing files: " + ", ".join(sorted(missing_files))
        )
    if extra_files:
        raise ValueError(
            "distribution has non-release files: " + ", ".join(sorted(extra_files))
        )


def _validate_core(document: dict[str, Any], relative: str) -> tuple[dict[str, Any], str, str]:
    core = _envelope(document, "core", relative)
    _keys(core, f"{relative}.core", {"magic", "metadata", "framework", "cores"})

    metadata = _object(core["metadata"], f"{relative}.core.metadata")
    _keys(
        metadata,
        f"{relative}.core.metadata",
        {
            "platform_ids",
            "shortname",
            "description",
            "author",
            "url",
            "version",
            "date_release",
        },
    )
    platforms = _array(metadata["platform_ids"], f"{relative}.core.metadata.platform_ids", 4)
    if not platforms:
        raise ValueError(f"{relative}.core.metadata.platform_ids must not be empty")
    for index, platform in enumerate(platforms):
        if not isinstance(platform, str) or not PLATFORM_ID_PATTERN.fullmatch(platform):
            raise ValueError(f"{relative}.core.metadata.platform_ids[{index}] is invalid")
    _unique(platforms, f"{relative}.core.metadata.platform_ids")
    shortname = _text(metadata["shortname"], f"{relative}.core.metadata.shortname", 31)
    _text(metadata["description"], f"{relative}.core.metadata.description", 63)
    author = _text(metadata["author"], f"{relative}.core.metadata.author", 31)
    _text(metadata["url"], f"{relative}.core.metadata.url", 63)
    _text(metadata["version"], f"{relative}.core.metadata.version", 31)
    release_date = _text(metadata["date_release"], f"{relative}.core.metadata.date_release", 10)
    try:
        if datetime.date.fromisoformat(release_date).isoformat() != release_date:
            raise ValueError
    except ValueError as error:
        raise ValueError(f"{relative}.core.metadata.date_release must be YYYY-MM-DD") from error
    if platforms != ["wonderswan"]:
        raise ValueError(f"{relative}.core.metadata.platform_ids must be ['wonderswan']")
    if f"{author}.{shortname}" != CORE_RELATIVE.name:
        raise ValueError(
            f"{relative} metadata author/shortname do not match {CORE_RELATIVE}"
        )

    framework = _object(core["framework"], f"{relative}.core.framework")
    _keys(
        framework,
        f"{relative}.core.framework",
        {"target_product", "version_required", "sleep_supported", "dock", "hardware", "chip32_vm"},
    )
    if framework["target_product"] != "Analogue Pocket":
        raise ValueError(f"{relative}.core.framework.target_product must be Analogue Pocket")
    firmware = _text(framework["version_required"], f"{relative}.core.framework.version_required", 15)
    if not VERSION_REQUIRED_PATTERN.fullmatch(firmware):
        raise ValueError(f"{relative}.core.framework.version_required is invalid")
    _boolean(framework["sleep_supported"], f"{relative}.core.framework.sleep_supported")
    chip32_name = _filename(framework["chip32_vm"], f"{relative}.core.framework.chip32_vm", 15)

    dock = _object(framework["dock"], f"{relative}.core.framework.dock")
    _keys(dock, f"{relative}.core.framework.dock", {"supported", "analog_output"})
    if _boolean(dock["supported"], f"{relative}.core.framework.dock.supported") is not True:
        raise ValueError(f"{relative}.core.framework.dock.supported must be true")
    _boolean(dock["analog_output"], f"{relative}.core.framework.dock.analog_output")

    hardware = _object(framework["hardware"], f"{relative}.core.framework.hardware")
    _keys(hardware, f"{relative}.core.framework.hardware", {"link_port", "cartridge_adapter"})
    _boolean(hardware["link_port"], f"{relative}.core.framework.hardware.link_port")
    cartridge_adapter = hardware["cartridge_adapter"]
    if cartridge_adapter != -1:
        _integer(cartridge_adapter, f"{relative}.core.framework.hardware.cartridge_adapter")

    cores = _array(core["cores"], f"{relative}.core.cores", 8)
    if not cores:
        raise ValueError(f"{relative}.core.cores must not be empty")
    ids: list[int] = []
    names: list[str] = []
    filenames: list[str] = []
    for index, value in enumerate(cores):
        where = f"{relative}.core.cores[{index}]"
        item = _object(value, where)
        _keys(item, where, {"id", "filename"}, {"name"})
        ids.append(_integer(item["id"], f"{where}.id", 0xFFFF))
        filenames.append(_filename(item["filename"], f"{where}.filename", 15))
        if "name" in item:
            names.append(_text(item["name"], f"{where}.name", 15))
    _unique(ids, f"{relative}.core.cores ids")
    _unique([value.casefold() for value in names], f"{relative}.core.cores names")
    _unique([value.casefold() for value in filenames], f"{relative}.core.cores filenames")
    if len(cores) != 1:
        raise ValueError(f"{relative}.core.cores must contain the single implemented core")
    return metadata, filenames[0], chip32_name


def _validate_data(document: dict[str, Any], relative: str, platform_count: int) -> None:
    data = _envelope(document, "data", relative)
    _keys(data, f"{relative}.data", {"magic", "data_slots"})
    slots = _array(data["data_slots"], f"{relative}.data.data_slots", 32)
    ids: list[int] = []
    allowed_parameter_bits = 0x030003FF
    for index, value in enumerate(slots):
        where = f"{relative}.data.data_slots[{index}]"
        slot = _object(value, where)
        _keys(
            slot,
            where,
            {"name", "id", "required", "parameters", "extensions", "address"},
            {
                "nonvolatile",
                "deferload",
                "secondary",
                "filename",
                "size_exact",
                "size_maximum",
            },
        )
        _text(slot["name"], f"{where}.name", 15)
        ids.append(_integer(slot["id"], f"{where}.id", 0xFFFF))
        _boolean(slot["required"], f"{where}.required")
        parameters = _integer(slot["parameters"], f"{where}.parameters")
        if parameters & ~allowed_parameter_bits:
            raise ValueError(f"{where}.parameters sets undocumented APF_VER_1 bits")
        platform_index = (parameters >> 24) & 3
        if platform_index >= platform_count:
            raise ValueError(f"{where}.parameters selects absent platform {platform_index}")
        for name in ("nonvolatile", "deferload", "secondary"):
            if name in slot:
                _boolean(slot[name], f"{where}.{name}")
        if "filename" in slot:
            _filename(slot["filename"], f"{where}.filename", 31)
        extensions = _array(slot["extensions"], f"{where}.extensions", 4)
        if not extensions:
            raise ValueError(f"{where}.extensions must not be empty")
        for extension_index, extension in enumerate(extensions):
            extension_where = f"{where}.extensions[{extension_index}]"
            extension = _text(extension, extension_where, 7)
            if not re.fullmatch(r"[A-Za-z0-9]+", extension):
                raise ValueError(f"{extension_where} must omit dots and paths")
        _unique([extension.casefold() for extension in extensions], f"{where}.extensions")
        sizes: dict[str, int] = {}
        for name in ("size_exact", "size_maximum"):
            if name in slot:
                size = _integer(slot[name], f"{where}.{name}")
                if size == 0:
                    raise ValueError(f"{where}.{name} must be nonzero when present")
                sizes[name] = size
        if len(sizes) == 2 and sizes["size_exact"] > sizes["size_maximum"]:
            raise ValueError(f"{where}.size_exact exceeds size_maximum")
        _integer(slot["address"], f"{where}.address")
        if slot.get("nonvolatile", False) and "size_maximum" not in slot:
            raise ValueError(f"{where} nonvolatile slot requires size_maximum")
    _unique(ids, f"{relative}.data.data_slots ids")
    if sorted(ids) != [0, 9, 10, 11]:
        raise ValueError(f"{relative}.data.data_slots must define exactly IDs 0, 9, 10, 11")


def _validate_input(document: dict[str, Any], relative: str) -> None:
    body = _envelope(document, "input", relative)
    _keys(body, f"{relative}.input", {"magic", "controllers"})
    controllers = _array(body["controllers"], f"{relative}.input.controllers", 4)
    if not controllers:
        raise ValueError(f"{relative}.input.controllers must not be empty")
    for controller_index, value in enumerate(controllers):
        where = f"{relative}.input.controllers[{controller_index}]"
        controller = _object(value, where)
        _keys(controller, where, {"type", "mappings"})
        if controller["type"] != "default":
            raise ValueError(f"{where}.type must be default")
        mappings = _array(controller["mappings"], f"{where}.mappings", 8)
        ids: list[int] = []
        keys: list[str] = []
        for mapping_index, mapping_value in enumerate(mappings):
            mapping_where = f"{where}.mappings[{mapping_index}]"
            mapping = _object(mapping_value, mapping_where)
            _keys(mapping, mapping_where, {"id", "name", "key"})
            ids.append(_integer(mapping["id"], f"{mapping_where}.id", 0xFFFF))
            _text(mapping["name"], f"{mapping_where}.name", 19)
            key = mapping["key"]
            if key not in KEYCODES:
                raise ValueError(f"{mapping_where}.key is not an APF gamepad keycode")
            keys.append(key)
        _unique(ids, f"{where}.mappings ids")
        _unique(keys, f"{where}.mappings keys")
    if len(controllers) != 1:
        raise ValueError(f"{relative}.input.controllers must contain one controller")


def _validate_interact(document: dict[str, Any], relative: str) -> None:
    body = _envelope(document, "interact", relative)
    _keys(body, f"{relative}.interact", {"magic", "variables", "messages"})
    variables = _array(body["variables"], f"{relative}.interact.variables", 16)
    messages = _array(body["messages"], f"{relative}.interact.messages")
    if messages:
        raise ValueError(f"{relative}.interact.messages must be empty for this release")
    ids: list[int] = []
    common = {"name", "id", "type", "enabled"}
    allowed_by_type = {
        "action": {"address", "value"},
        "check": {"address", "persist", "writeonly", "defaultval", "value", "value_off", "mask"},
        "list": {"address", "persist", "writeonly", "defaultval", "options", "mask"},
    }
    for index, value in enumerate(variables):
        where = f"{relative}.interact.variables[{index}]"
        item = _object(value, where)
        kind = item.get("type")
        if kind not in allowed_by_type:
            raise ValueError(f"{where}.type is not implemented by this release profile")
        _keys(item, where, common, allowed_by_type[kind])
        _text(item["name"], f"{where}.name", 23)
        ids.append(_integer(item["id"], f"{where}.id", 0xFFFF))
        _boolean(item["enabled"], f"{where}.enabled")
        if "address" in item:
            address = _integer(item["address"], f"{where}.address")
            if address & 3:
                raise ValueError(f"{where}.address must be 32-bit aligned")
        for name in ("persist", "writeonly"):
            if name in item:
                _boolean(item[name], f"{where}.{name}")
        for name in ("defaultval", "value", "value_off", "mask"):
            if name in item:
                _integer(item[name], f"{where}.{name}")
        if item.get("persist", False):
            if "address" not in item or "defaultval" not in item:
                raise ValueError(f"{where} persistent item requires address and defaultval")
        if kind == "action":
            if ("address" in item) != ("value" in item):
                raise ValueError(f"{where} action must define both address and value or neither")
        elif kind == "check":
            for name in ("address", "defaultval", "value"):
                if name not in item:
                    raise ValueError(f"{where} check is missing {name}")
            if _integer(item["defaultval"], f"{where}.defaultval") not in (0, 1):
                raise ValueError(f"{where}.defaultval must be 0 or 1")
        elif kind == "list":
            for name in ("address", "defaultval", "options"):
                if name not in item:
                    raise ValueError(f"{where} list is missing {name}")
            options = _array(item["options"], f"{where}.options", 16)
            if not options:
                raise ValueError(f"{where}.options must not be empty")
            option_values: list[int] = []
            for option_index, option_value in enumerate(options):
                option_where = f"{where}.options[{option_index}]"
                option = _object(option_value, option_where)
                _keys(option, option_where, {"value", "name"})
                option_values.append(_integer(option["value"], f"{option_where}.value"))
                _text(option["name"], f"{option_where}.name", 23)
            _unique(option_values, f"{where}.options values")
            if _integer(item["defaultval"], f"{where}.defaultval") not in option_values:
                raise ValueError(f"{where}.defaultval is not one of its options")
    _unique(ids, f"{relative}.interact.variables ids")


def _validate_video(document: dict[str, Any], relative: str) -> None:
    body = _envelope(document, "video", relative)
    _keys(body, f"{relative}.video", {"magic", "scaler_modes", "display_modes", "defaults"})
    scalers = _array(body["scaler_modes"], f"{relative}.video.scaler_modes", 8)
    if not scalers:
        raise ValueError(f"{relative}.video.scaler_modes must not be empty")
    for index, value in enumerate(scalers):
        where = f"{relative}.video.scaler_modes[{index}]"
        scaler = _object(value, where)
        _keys(
            scaler,
            where,
            {"width", "height", "aspect_w", "aspect_h", "rotation", "mirror"},
            {"dock_aspect_w", "dock_aspect_h"},
        )
        for name in ("width", "height", "aspect_w", "aspect_h"):
            if _integer(scaler[name], f"{where}.{name}") == 0:
                raise ValueError(f"{where}.{name} must be nonzero")
        if ("dock_aspect_w" in scaler) != ("dock_aspect_h" in scaler):
            raise ValueError(f"{where} must define both Dock aspect members or neither")
        for name in ("dock_aspect_w", "dock_aspect_h"):
            if name in scaler and _integer(scaler[name], f"{where}.{name}") == 0:
                raise ValueError(f"{where}.{name} must be nonzero")
        if _integer(scaler["rotation"], f"{where}.rotation") not in (0, 90, 180, 270):
            raise ValueError(f"{where}.rotation must be 0, 90, 180, or 270")
        if _integer(scaler["mirror"], f"{where}.mirror") > 3:
            raise ValueError(f"{where}.mirror must be a two-bit value")
    display_modes = _array(body["display_modes"], f"{relative}.video.display_modes", 16)
    mode_ids: list[int] = []
    for index, value in enumerate(display_modes):
        where = f"{relative}.video.display_modes[{index}]"
        mode = _object(value, where)
        _keys(mode, where, {"id"})
        mode_id = _integer(mode["id"], f"{where}.id")
        if mode_id not in DISPLAY_MODE_IDS:
            raise ValueError(f"{where}.id is not a documented display mode")
        mode_ids.append(mode_id)
    _unique(mode_ids, f"{relative}.video.display_modes ids")
    defaults = _object(body["defaults"], f"{relative}.video.defaults")
    _keys(defaults, f"{relative}.video.defaults", set(), {"sharpness"})
    if "sharpness" in defaults and _integer(defaults["sharpness"], f"{relative}.video.defaults.sharpness") > 3:
        raise ValueError(f"{relative}.video.defaults.sharpness must be 0..3")


def _validate_simple_documents(documents: dict[str, dict[str, Any]]) -> None:
    audio_relative = JSON_FILES["audio"]
    audio = _envelope(documents["audio"], "audio", audio_relative)
    _keys(audio, f"{audio_relative}.audio", {"magic"})

    variants_relative = JSON_FILES["variants"]
    variants = _envelope(documents["variants"], "variants", variants_relative)
    _keys(variants, f"{variants_relative}.variants", {"magic", "variant_list"})
    if _array(variants["variant_list"], f"{variants_relative}.variants.variant_list", 8):
        raise ValueError(f"{variants_relative} must be empty until variants are implemented")

    platform_relative = JSON_FILES["platform"]
    platform_document = documents["platform"]
    _keys(platform_document, platform_relative, {"platform"})
    platform = _object(platform_document["platform"], f"{platform_relative}.platform")
    _keys(platform, f"{platform_relative}.platform", {"category", "name", "year", "manufacturer"})
    for name in ("category", "name", "manufacturer"):
        _text(platform[name], f"{platform_relative}.platform.{name}", 31)
    year = _integer(platform["year"], f"{platform_relative}.platform.year", 9999)
    if year < 1:
        raise ValueError(f"{platform_relative}.platform.year must be positive")


def _validate_assets(dist: pathlib.Path) -> None:
    platform_path = dist / "Platforms/_images/wonderswan.bin"
    platform = platform_path.read_bytes()
    expected_platform_size = 521 * 165 * 2
    if len(platform) != expected_platform_size:
        raise ValueError(
            f"Platforms/_images/wonderswan.bin must be 521x165x16-bit "
            f"({expected_platform_size} bytes), got {len(platform)}"
        )
    if any(platform[index] != 0 for index in range(1, len(platform), 2)):
        raise ValueError(
            "Platforms/_images/wonderswan.bin has nonzero low brightness bytes"
        )

    icon_path = dist / CORE_RELATIVE / "icon.bin"
    if icon_path.exists():
        icon = icon_path.read_bytes()
        expected_icon_size = 36 * 36 * 2
        if len(icon) != expected_icon_size:
            raise ValueError(
                f"{CORE_RELATIVE}/icon.bin must be 36x36x16-bit "
                f"({expected_icon_size} bytes), got {len(icon)}"
            )
        pixels = [icon[index : index + 2] for index in range(0, len(icon), 2)]
        if any(pixel not in (b"\x00\x00", b"\xff\x00") for pixel in pixels):
            raise ValueError(f"{CORE_RELATIVE}/icon.bin must contain only 0x0000/0xFF00 pixels")


def validate_distribution(dist: pathlib.Path) -> ValidatedDistribution:
    """Validate the complete release source tree and return resolved identities."""

    dist = dist.resolve()
    _validate_tree(dist)
    documents = {name: _read_json(dist, relative) for name, relative in JSON_FILES.items()}
    metadata, bitstream_name, chip32_name = _validate_core(
        documents["core"], JSON_FILES["core"]
    )
    if bitstream_name.casefold() == chip32_name.casefold():
        raise ValueError("core bitstream and Chip32 filenames must be distinct")
    source_names = {
        path.name.casefold()
        for path in (dist / CORE_RELATIVE).iterdir()
    }
    for filename, description in (
        (bitstream_name, "core bitstream"),
        (chip32_name, "Chip32 image"),
    ):
        if filename.casefold() in source_names:
            raise ValueError(f"refusing to overwrite existing {description} package input")

    _validate_data(documents["data"], JSON_FILES["data"], len(metadata["platform_ids"]))
    _validate_input(documents["input"], JSON_FILES["input"])
    _validate_interact(documents["interact"], JSON_FILES["interact"])
    _validate_video(documents["video"], JSON_FILES["video"])
    _validate_simple_documents(documents)
    _validate_assets(dist)

    info_path = dist / CORE_RELATIVE / "info.txt"
    try:
        info = info_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"invalid UTF-8 {CORE_RELATIVE}/info.txt: {error}") from error
    if not info.strip():
        raise ValueError(f"{CORE_RELATIVE}/info.txt must not be empty")
    if len(info.splitlines()) > 32:
        raise ValueError(f"{CORE_RELATIVE}/info.txt exceeds the official 32-line limit")
    if any(character != "\n" and not 0x20 <= ord(character) <= 0x7E for character in info):
        raise ValueError(
            f"{CORE_RELATIVE}/info.txt must contain only printable ASCII and LF"
        )

    return ValidatedDistribution(
        core_directory=CORE_RELATIVE,
        bitstream_name=bitstream_name,
        chip32_name=chip32_name,
        author=metadata["author"],
        shortname=metadata["shortname"],
        repository_url=metadata["url"],
        version=metadata["version"],
        release_date=metadata["date_release"],
    )
