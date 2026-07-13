#!/usr/bin/env python3
"""Lock the first-class Pocket/Dock input metadata and source boundary."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "dist/Cores/agg23.WonderSwan"

EXPECTED_MAPPINGS = [
    (0, "Horz A/Vert X3", "pad_btn_a"),
    (1, "Horz B/Vert X4", "pad_btn_b"),
    (2, "Horz Y3/Vert X2", "pad_btn_x"),
    (3, "Horz Y4/Vert X1", "pad_btn_y"),
    (10, "Horz Y1/Vert A", "pad_trig_l"),
    (11, "Horz Y2/Vert B", "pad_trig_r"),
    (20, "Start", "pad_btn_start"),
    (30, "Fast Forward", "pad_btn_select"),
]

EXPECTED_SCALERS = [
    (224, 144, 14, 9, 0, 0),
    (224, 144, 14, 9, 270, 0),
    (224, 144, 14, 9, 180, 0),
]


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    return re.sub(r"--[^\n]*", "", source)


def compact(source: str) -> str:
    return re.sub(r"\s+", "", strip_comments(source))


def verify_contract(bundle: dict[str, object]) -> None:
    input_json = bundle["input_json"]
    core_json = bundle["core_json"]
    video_json = bundle["video_json"]
    platform_json = bundle["platform_json"]
    info = bundle["info"]
    readme = bundle["readme"]
    presets = bundle["presets"]
    first_class_input = bundle["first_class_input"]
    core_top_source = bundle["core_top"]
    wonderswan_source = bundle["wonderswan"]
    joypad_source = bundle["joypad"]
    filter_source = bundle["filter"]
    regression = bundle["regression"]

    inp = input_json.get("input", {})
    if inp.get("magic") != "APF_VER_1":
        raise ValueError("input.json magic is not APF_VER_1")
    controllers = inp.get("controllers", [])
    if len(controllers) != 1 or controllers[0].get("type") != "default":
        raise ValueError("input.json must expose one default controller")
    mappings = controllers[0].get("mappings", [])
    actual_mappings = [
        (entry.get("id"), entry.get("name"), entry.get("key"))
        for entry in mappings
    ]
    if actual_mappings != EXPECTED_MAPPINGS:
        raise ValueError("orientation-aware Controls labels changed")
    if len({entry[0] for entry in actual_mappings}) != len(actual_mappings):
        raise ValueError("input mapping IDs are not unique")
    if len({entry[2] for entry in actual_mappings}) != len(actual_mappings):
        raise ValueError("input mapping keycodes are not unique")
    if any(not 0 <= entry[0] <= 0xFFFF for entry in actual_mappings):
        raise ValueError("input mapping ID exceeds the documented 16-bit range")
    if any(len(entry[1]) > 19 for entry in actual_mappings):
        raise ValueError("input mapping label exceeds the documented 19 characters")

    core = core_json.get("core", {})
    framework = core.get("framework", {})
    dock = framework.get("dock", {})
    if core.get("magic") != "APF_VER_1":
        raise ValueError("core.json magic is not APF_VER_1")
    if core.get("metadata", {}).get("platform_ids") != ["wonderswan"]:
        raise ValueError("core does not identify the WonderSwan platform")
    if framework.get("target_product") != "Analogue Pocket":
        raise ValueError("core target is not Analogue Pocket")
    if dock != {"supported": True, "analog_output": False}:
        raise ValueError("Dock capability must be enabled without analog video output")

    platform = platform_json.get("platform", {})
    expected_platform = {
        "category": "Handheld",
        "name": "WonderSwan",
        "year": 1999,
        "manufacturer": "Bandai",
    }
    if platform != expected_platform:
        raise ValueError("WonderSwan platform metadata changed")

    video = video_json.get("video", {})
    if video.get("magic") != "APF_VER_1":
        raise ValueError("video.json magic is not APF_VER_1")
    scalers = [
        (
            mode.get("width"),
            mode.get("height"),
            mode.get("aspect_w"),
            mode.get("aspect_h"),
            mode.get("rotation"),
            mode.get("mirror"),
        )
        for mode in video.get("scaler_modes", [])
    ]
    if scalers != EXPECTED_SCALERS:
        raise ValueError("landscape/portrait/180 scaler contract changed")
    if any("dock_aspect_w" in mode or "dock_aspect_h" in mode for mode in video["scaler_modes"]):
        raise ValueError("unexpected unreviewed Dock-specific aspect override")

    info_lines = info.splitlines()
    if len(info_lines) > 32:
        raise ValueError("info.txt exceeds the documented 32-line limit")
    if not info.isascii():
        raise ValueError("info.txt contains non-ASCII characters")
    for statement in (
        "* Pocket and Dock use the same Player 1 digital mapping",
        "* Controllers 2-4, analog axes, keyboard, and mouse are not used",
        "* Controls behavior is PocketOS-owned; verify on 2.6.0",
        "* Vertical games use D-pad for Y and face buttons for X",
    ):
        if statement not in info_lines:
            raise ValueError(f"info.txt omits input boundary: {statement}")

    for statement in (
        "Analogue's current developer pages describe the\n`input.json` Controls UI as read-only",
        "official Pocket firmware 2.4 notes separately say beta Dock remapping\napplies to all four controllers",
        "Firmware 2.6.0 Pocket and Dock hardware observation is\nthe acceptance gate",
        "Pocket's built-in controls and a Dock controller use this same Player 1 digital\nmapping",
        "FIRST_CLASS_INPUT_DOCK.md",
    ):
        if statement not in readme:
            raise ValueError(f"README omits input/Dock contract: {statement}")
    if "Pocket owns the actual saved control remaps" in readme:
        raise ValueError("README makes an unsupported saved-remap claim")

    for statement in (
        "**currently read-only**",
        "[Pocket firmware 2.4 notes]",
        "promise editability, remap application, persistence, or per-asset remap scope",
        "actual PocketOS 2.6.0 behavior remains a hardware gate",
    ):
        if statement not in presets:
            raise ValueError(f"per-game presets omit Controls documentation conflict: {statement}")
    for stale_claim in (
        "perform the actual host-managed remap",
        "all eight remaps take effect and survive relaunch",
        "specifies per-asset Input lookup and host remapping",
    ):
        if stale_claim in presets:
            raise ValueError(f"per-game presets retain stale remapping claim: {stale_claim}")

    for statement in (
        "the current developer page describes the Controls menu as read-only",
        "beta controller remapping applies to all four controllers when Docked",
        "Either an observed read-only screen or an observed beta remapper is evidence",
    ):
        if statement not in first_class_input:
            raise ValueError(f"first-class input guide omits Controls conflict: {statement}")

    core_top = compact(core_top_source)
    wonderswan = compact(wonderswan_source)
    joypad = compact(joypad_source)
    gamepad_filter = compact(filter_source)

    expected_filter = (
        "TYPE_POCKET,TYPE_DOCK_DIGITAL,TYPE_DOCK_ANALOG:"
        "buttons<=key_word[15:0];default:buttons<=16'd0;"
    )
    if expected_filter not in gamepad_filter:
        raise ValueError("gamepad filter does not accept exactly APF PAD types 1-3")
    for signal in (
        "cont2_key", "cont3_key", "cont4_key",
        "cont1_joy", "cont2_joy", "cont3_joy", "cont4_joy",
        "cont1_trig", "cont2_trig", "cont3_trig", "cont4_trig",
    ):
        if len(re.findall(rf"\b{signal}\b", strip_comments(core_top_source))) != 1:
            raise ValueError(f"unsupported input signal is consumed: {signal}")
    if ".key_word(cont1_key)" not in core_top:
        raise ValueError("P1 key word does not pass through the gamepad type filter")

    for fragment in (
        ".button_a(cont1_key_s[4])",
        ".button_b(cont1_key_s[5])",
        ".button_x(cont1_key_s[6])",
        ".button_y(cont1_key_s[7])",
        ".button_trig_l(cont1_key_s[8])",
        ".button_trig_r(cont1_key_s[9])",
        ".button_start(cont1_key_s[15]|console_setup_start_sys_s)",
        ".button_select(cont1_key_s[14])",
        ".dpad_up(cont1_key_s[0])",
        ".dpad_down(cont1_key_s[1])",
        ".dpad_left(cont1_key_s[2])",
        ".dpad_right(cont1_key_s[3])",
    ):
        if fragment not in core_top:
            raise ValueError(f"documented PAD bit mapping is missing {fragment}")

    for fragment in (
        ".KeyY1(vertical?button_x:button_trig_l)",
        ".KeyY2(vertical?button_a:button_trig_r)",
        ".KeyY3(vertical?button_b:button_x)",
        ".KeyY4(vertical?button_y:button_y)",
        ".KeyX1(dpad_up)",
        ".KeyX2(dpad_right)",
        ".KeyX3(dpad_down)",
        ".KeyX4(dpad_left)",
        ".KeyA(~vertical?button_a:button_trig_l)",
        ".KeyB(~vertical?button_b:button_trig_r)",
        "wirefastforward=button_select&&!ioctl_download;",
    ):
        if fragment not in wonderswan:
            raise ValueError(f"native-orientation input mapping is missing {fragment}")

    vertical_y_matrix = (
        "else"
        "if(KeyX4='1')thenKEYPAD_read(0)<='1';endif;"
        "if(KeyX1='1')thenKEYPAD_read(1)<='1';endif;"
        "if(KeyX2='1')thenKEYPAD_read(2)<='1';endif;"
        "if(KeyX3='1')thenKEYPAD_read(3)<='1';endif;"
        "endif;endif;"
    )
    vertical_x_matrix = (
        "else"
        "if(KeyY4='1')thenKEYPAD_read(0)<='1';endif;"
        "if(KeyY1='1')thenKEYPAD_read(1)<='1';endif;"
        "if(KeyY2='1')thenKEYPAD_read(2)<='1';endif;"
        "if(KeyY3='1')thenKEYPAD_read(3)<='1';endif;"
        "endif;endif;"
    )
    if vertical_y_matrix not in joypad or vertical_x_matrix not in joypad:
        raise ValueError("VHDL vertical matrix rotation changed")

    if 'python3 "$ROOT/scripts/pocket_input_dock_contract_test.py"' not in regression:
        raise ValueError("regression does not run the input/Dock contract")


def load_bundle() -> dict[str, object]:
    return {
        "input_json": json.loads((CORE_DIR / "input.json").read_text()),
        "core_json": json.loads((CORE_DIR / "core.json").read_text()),
        "video_json": json.loads((CORE_DIR / "video.json").read_text()),
        "platform_json": json.loads((ROOT / "dist/Platforms/wonderswan.json").read_text()),
        "info": (CORE_DIR / "info.txt").read_text(),
        "readme": (ROOT / "README.md").read_text(),
        "presets": (ROOT / "PER_GAME_PRESETS.md").read_text(),
        "first_class_input": (ROOT / "FIRST_CLASS_INPUT_DOCK.md").read_text(),
        "core_top": (ROOT / "src/fpga/core/core_top.v").read_text(),
        "wonderswan": (ROOT / "src/fpga/core/wonderswan.sv").read_text(),
        "joypad": (ROOT / "src/fpga/core/rtl/joypad.vhd").read_text(),
        "filter": (ROOT / "src/fpga/core/apf_gamepad_filter.sv").read_text(),
        "regression": (ROOT / "scripts/regression.sh").read_text(),
    }


def main() -> None:
    bundle = load_bundle()
    verify_contract(bundle)

    mutations: list[tuple[str, object]] = []

    changed_input = copy.deepcopy(bundle["input_json"])
    changed_input["input"]["controllers"][0]["mappings"][0]["name"] = "A"
    mutations.append(("orientation label", ("input_json", changed_input)))

    changed_core = copy.deepcopy(bundle["core_json"])
    changed_core["core"]["framework"]["dock"]["supported"] = False
    mutations.append(("Dock disabled", ("core_json", changed_core)))

    changed_video = copy.deepcopy(bundle["video_json"])
    changed_video["video"]["scaler_modes"][1]["rotation"] = 90
    mutations.append(("portrait rotation", ("video_json", changed_video)))

    mutations.extend(
        [
            (
                "type filter",
                (
                    "filter",
                    bundle["filter"].replace(
                        "TYPE_DOCK_ANALOG: buttons <= key_word[15:0];",
                        "TYPE_DOCK_ANALOG, 4'h4: buttons <= key_word[15:0];",
                        1,
                    ),
                ),
            ),
            (
                "P2 consumption",
                (
                    "core_top",
                    bundle["core_top"].replace(
                        "wire [15:0] cont1_key_s;",
                        "wire [15:0] cont1_key_s;\nwire p2_used = cont2_key[4];",
                        1,
                    ),
                ),
            ),
            (
                "vertical face mapping",
                (
                    "wonderswan",
                    bundle["wonderswan"].replace(
                        ".KeyY2   (vertical ? button_a : button_trig_r)",
                        ".KeyY2   (vertical ? button_b : button_trig_r)",
                        1,
                    ),
                ),
            ),
            (
                "firmware conflict claim",
                (
                    "readme",
                    bundle["readme"].replace(
                        "official Pocket firmware 2.4 notes", "older firmware notes", 1
                    ),
                ),
            ),
            (
                "per-game firmware conflict",
                (
                    "presets",
                    bundle["presets"].replace(
                        "[Pocket firmware 2.4 notes]", "[older firmware notes]", 1
                    ),
                ),
            ),
            (
                "first-class firmware conflict",
                (
                    "first_class_input",
                    bundle["first_class_input"].replace(
                        "beta controller remapping applies to all four controllers when Docked",
                        "Controls behavior is uniform",
                        1,
                    ),
                ),
            ),
            (
                "regression hook",
                (
                    "regression",
                    bundle["regression"].replace(
                        'python3 "$ROOT/scripts/pocket_input_dock_contract_test.py"',
                        'python3 "$ROOT/scripts/missing_input_dock_contract_test.py"',
                        1,
                    ),
                ),
            ),
        ]
    )

    rejected = 0
    for name, (field, value) in mutations:
        mutated = dict(bundle)
        mutated[field] = value
        try:
            verify_contract(mutated)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError(f"input/Dock contract accepted mutation: {name}")

    print(
        "PASS Pocket first-class input/Dock source+metadata contract "
        f"({rejected} adversarial mutations rejected)"
    )


if __name__ == "__main__":
    main()
