#!/usr/bin/env python3
"""Generate APF per-asset presets for the Swan Song WonderSwan core.

The files contain only APF menu definitions.  The selected ROM is never opened,
hashed, copied, catalogued, or named inside either JSON document; its path is
used solely to derive the location APF documents for per-asset overrides.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import re
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_CORE_ID = "agg23.WonderSwan"
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
    "flicker": (42, "list", "0x204", {0, 1, 2}),
    "orientation": (43, "list", "0x208", {0, 1, 2}),
    "landscape_180": (44, "check", "0x20C", {0, 1}),
    "color_profile": (45, "list", "0x210", {0, 1}),
    "fast_forward_audio": (81, "check", "0x300", {0, 1}),
}

ORIENTATION_VALUES = {"auto": 0, "horizontal": 1, "vertical": 2}
# "3-frame" remains an explicit compatibility alias for the old menu wording.
# Mode 2 is a finite three-frame LCD-response model, not infinite persistence.
FLICKER_VALUES = {"off": 0, "2-frame": 1, "persistence": 2, "3-frame": 2}
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


def _read_json(path: pathlib.Path, envelope: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PresetError(f"cannot read valid JSON from {path}: {error}") from error
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
    definitions: pathlib.Path, options: PresetOptions
) -> dict[str, Any]:
    source = definitions / "interact.json"
    document = _read_json(source, "interact")
    generated = copy.deepcopy(document)
    variables = _variables_by_id(generated, source)

    selected = {
        "cpu_turbo": SWITCH_VALUES[options.cpu_turbo],
        "triple_buffer": SWITCH_VALUES[options.triple_buffer],
        "flicker": FLICKER_VALUES[options.flicker],
        "orientation": ORIENTATION_VALUES[options.orientation],
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
        if variable.get("persist") is not True or variable.get("writeonly") is not True:
            raise PresetError(
                f"{source} interact ID {identifier} must remain persistent and write-only"
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


def build_input_document(definitions: pathlib.Path) -> dict[str, Any]:
    source = definitions / "input.json"
    document = _read_json(source, "input")
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


def _ensure_safe_ancestors(root: pathlib.Path, destination: pathlib.Path) -> None:
    try:
        relative = destination.relative_to(root)
    except ValueError as error:
        raise PresetError(f"output path escapes SD root: {destination}") from error
    current = root
    for component in relative.parts[:-1]:
        current /= component
        if current.is_symlink():
            raise PresetError(f"refusing symlink in output path: {current}")
        if current.exists() and not current.is_dir():
            raise PresetError(f"output parent is not a directory: {current}")
    if destination.is_symlink():
        raise PresetError(f"refusing symlink output: {destination}")
    if destination.exists() and not destination.is_file():
        raise PresetError(f"output is not a regular file: {destination}")


def _preflight(
    root: pathlib.Path,
    outputs: Iterable[tuple[pathlib.Path, bytes]],
    *,
    force: bool,
) -> list[tuple[pathlib.Path, bytes]]:
    planned = list(outputs)
    for destination, _ in planned:
        _ensure_safe_ancestors(root, destination)
        if destination.exists() and not force:
            raise PresetError(
                f"preset already exists: {destination} (use --force to replace it)"
            )
    return planned


def _atomic_write(destination: pathlib.Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
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
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def generate_presets(
    *,
    sd_root: pathlib.Path,
    asset: str,
    definitions: pathlib.Path = DEFAULT_DEFINITIONS,
    core_id: str = DEFAULT_CORE_ID,
    options: PresetOptions = PresetOptions(),
    force: bool = False,
) -> PresetResult:
    _validate_core_id(core_id)
    if sd_root.is_symlink() or not sd_root.is_dir():
        raise PresetError(f"SD root must be an existing, non-symlink directory: {sd_root}")
    root = sd_root.resolve()
    if not definitions.is_dir():
        raise PresetError(f"core definitions directory does not exist: {definitions}")

    # Validate enum-like dataclass fields even when called as a library.
    choices = {
        "orientation": ORIENTATION_VALUES,
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
    interact_path = root / "Presets" / core_id / "Interact" / pathlib.Path(*relative.parts)
    input_path = (
        root / "Presets" / core_id / "Input" / pathlib.Path(*relative.parts)
        if options.controls == "per-game"
        else None
    )

    outputs = [(interact_path, _json_bytes(build_interact_document(definitions, options)))]
    if input_path is not None:
        outputs.append((input_path, _json_bytes(build_input_document(definitions))))
    planned = _preflight(root, outputs, force=force)

    for destination, payload in planned:
        # Recheck after creating earlier parents/files, closing the common
        # partial-tree and pre-existing-symlink failure modes.
        _ensure_safe_ancestors(root, destination)
        _atomic_write(destination, payload)
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
    parser.add_argument("--landscape-180", choices=SWITCH_VALUES, default="off")
    parser.add_argument(
        "--color-profile", choices=COLOR_PROFILE_VALUES, default="raw"
    )
    parser.add_argument("--triple-buffer", choices=SWITCH_VALUES, default="on")
    parser.add_argument(
        "--lcd-response",
        "--flicker",
        dest="flicker",
        choices=FLICKER_VALUES,
        default="off",
        help="finite LCD response model (--flicker is a compatibility alias)",
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
            "per-game creates an Input override for Pocket-side remapping; "
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
