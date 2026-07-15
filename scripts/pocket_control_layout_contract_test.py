#!/usr/bin/env python3
"""Lock Swan Song's persistent Pocket control-layout source boundary."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "dist/Cores/RegionallyFamous.SwanSong"

EXPECTED_LAYOUT_VARIABLE = {
    "name": "Control Layout",
    "id": 46,
    "type": "list",
    "enabled": True,
    "persist": True,
    "address": "0x214",
    "defaultval": 0,
    "options": [
        {"value": 0, "name": "Auto"},
        {"value": 1, "name": "Horizontal"},
        {"value": 2, "name": "Vertical"},
    ],
}


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    return re.sub(r"--[^\n]*", "", source)


def compact(source: str) -> str:
    return re.sub(r"\s+", "", strip_comments(source))


def parse_address(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"unsupported interact address: {value!r}")


def instance_connections(source: str, module: str, instance: str) -> dict[str, str]:
    clean = strip_comments(source)
    match = re.search(
        rf"\b{re.escape(module)}\s+{re.escape(instance)}\s*\((.*?)\)\s*;",
        clean,
        flags=re.DOTALL,
    )
    if match is None:
        raise ValueError(f"missing {module} {instance} instance")
    connections = re.findall(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)", match.group(1))
    if not connections or len(connections) != len(dict(connections)):
        raise ValueError(f"malformed or duplicate ports on {module} {instance}")
    return {name: re.sub(r"\s+", "", signal) for name, signal in connections}


def require_fragment(source: str, fragment: str, message: str) -> None:
    if fragment not in compact(source):
        raise ValueError(message)


def require_13_bit_sdc_guard(sdc: str, endpoint: str) -> None:
    guard = re.compile(
        rf"if\s*\{{\s*\[get_collection_size\s+\${endpoint}\]\s*!=\s*13\s*\}}"
    )
    if guard.search(strip_comments(sdc)) is None:
        raise ValueError(f"settings CDC does not fail closed on 13 {endpoint} registers")
    diagnostic_name = {
        "settings_source_registers": "settings_hold_source",
        "settings_destination_registers": "settings_destination",
    }[endpoint]
    if f"settings CDC constraint expected 13 {diagnostic_name} registers" not in sdc:
        raise ValueError(f"settings CDC omits the 13-bit {endpoint} diagnostic")


def verify_contract(bundle: dict[str, object]) -> None:
    interact = bundle["interact"]
    core_top = bundle["core_top"]
    cdc = bundle["cdc"]
    sdc = bundle["sdc"]
    mapper = bundle["mapper"]
    wonderswan = bundle["wonderswan"]
    qsf = bundle["qsf"]

    interact_root = interact.get("interact", {})
    if interact_root.get("magic") != "APF_VER_1":
        raise ValueError("interact.json magic is not APF_VER_1")
    variables = interact_root.get("variables", [])
    layout_variables = [entry for entry in variables if entry.get("id") == 46]
    if layout_variables != [EXPECTED_LAYOUT_VARIABLE]:
        raise ValueError("persistent Control Layout ID/options/address contract changed")
    if len({entry.get("id") for entry in variables}) != len(variables):
        raise ValueError("interact variable IDs are not unique")
    address_214 = [
        entry for entry in variables
        if "address" in entry and parse_address(entry["address"]) == 0x214
    ]
    if address_214 != layout_variables:
        raise ValueError("interact address 0x214 is missing or aliased")

    top = compact(core_top)
    for fragment, message in (
        ("reg[1:0]configured_control_layout=2'd0;", "bridge layout reset is not Auto"),
        ("wire[1:0]configured_control_layout_s;", "console layout signal is not two bits"),
        ("wire[12:0]settings_snapshot_s;", "settings snapshot is not 13 bits"),
        (
            "wire[12:0]settings_source_74a={configured_system,use_cpu_turbo,"
            "use_triple_buffer,configured_flickerblend,configured_orientation,"
            "configured_control_layout,use_flip_horizontal,"
            "configured_color_profile,use_fastforward_sound};",
            "authoritative 13-bit settings source packing/order changed",
        ),
        (".DEFAULT_SETTINGS(13'h0201)", "settings CDC instance default changed"),
        (".reset_n(pll_core_ready_74a)", "settings CDC reset boundary changed"),
        (".settings_destination(settings_snapshot_s)", "settings snapshot destination changed"),
        (
            ".settings_source(settings_source_74a)",
            "settings CDC no longer consumes the authoritative source bundle",
        ),
        (
            "assign{configured_system_s,use_cpu_turbo_s,use_triple_buffer_s,"
            "configured_flickerblend_s,configured_orientation_s,"
            "configured_control_layout_s,use_flip_horizontal_s,"
            "configured_color_profile_s,use_fastforward_sound_s}=settings_snapshot_s;",
            "13-bit settings destination unpacking/order changed",
        ),
        (
            ".configured_control_layout(configured_control_layout_s)",
            "console instance does not consume the atomic layout snapshot",
        ),
    ):
        if fragment not in top:
            raise ValueError(message)

    assignments = re.findall(r"configured_control_layout<=([^;]+);", top)
    expected_assignment = "bridge_wr_data>32'd2?2'd0:bridge_wr_data[1:0]"
    if assignments != [expected_assignment]:
        raise ValueError("bridge layout write must clamp every invalid value to Auto")
    if "32'h214:beginconfigured_control_layout<=" + expected_assignment + ";end" not in top:
        raise ValueError("bridge address 0x214 does not own the clamped layout write")

    cdc_compact = compact(cdc)
    for fragment, message in (
        ("parameter[12:0]DEFAULT_SETTINGS=13'h0201", "CDC default is not 13'h0201"),
        ("inputwire[12:0]settings_source", "CDC source payload is not 13 bits"),
        ("outputreg[12:0]settings_destination", "CDC destination payload is not 13 bits"),
        ("reg[12:0]settings_hold_source;", "CDC atomic hold register is not 13 bits"),
        ("settings_hold_source<=settings_source;", "CDC no longer freezes the complete source bundle"),
        ("settings_destination<=settings_hold_source;", "CDC no longer captures the held bundle atomically"),
        (
            "request_sync_destination!=request_seen_destination",
            "CDC destination capture is no longer request-qualified",
        ),
    ):
        if fragment not in cdc_compact:
            raise ValueError(message)

    require_13_bit_sdc_guard(sdc, "settings_source_registers")
    require_13_bit_sdc_guard(sdc, "settings_destination_registers")

    mapper_compact = compact(mapper)
    for fragment, message in (
        ("moduleapf_control_layout(", "control-layout mapper module is missing"),
        ("inputwire[1:0]configured_layout", "mapper configured layout is not two bits"),
        ("inputwirenative_vertical", "mapper lacks native vertical input"),
        (
            "wirecontrols_vertical=configured_layout==2'd1?1'b0:"
            "configured_layout==2'd2?1'b1:native_vertical;",
            "Auto/invalid layout no longer fails closed to native orientation",
        ),
    ):
        if fragment not in mapper_compact:
            raise ValueError(message)

    expected_key_assignments = {
        "key_y1": "controls_vertical?button_x:button_trig_l",
        "key_y2": "controls_vertical?button_a:button_trig_r",
        "key_y3": "controls_vertical?button_b:button_x",
        "key_y4": "button_y",
        "key_a": "controls_vertical?button_trig_l:button_a",
        "key_b": "controls_vertical?button_trig_r:button_b",
    }
    actual_key_assignments = dict(
        re.findall(r"assign(key_(?:y[1-4]|a|b))=([^;]+);", mapper_compact)
    )
    if actual_key_assignments != expected_key_assignments:
        raise ValueError("horizontal/vertical keypad mapping changed")

    mapper_connections = instance_connections(
        wonderswan, "apf_control_layout", "control_layout_mapper"
    )
    expected_mapper_connections = {
        "configured_layout": "configured_control_layout",
        "native_vertical": "vertical",
        "button_a": "button_a",
        "button_b": "button_b",
        "button_x": "button_x",
        "button_y": "button_y",
        "button_trig_l": "button_trig_l",
        "button_trig_r": "button_trig_r",
        "key_y1": "control_key_y1",
        "key_y2": "control_key_y2",
        "key_y3": "control_key_y3",
        "key_y4": "control_key_y4",
        "key_a": "control_key_a",
        "key_b": "control_key_b",
    }
    if mapper_connections != expected_mapper_connections:
        raise ValueError("control_layout_mapper integration changed")

    swan_connections = instance_connections(wonderswan, "SwanTop", "SwanTop")
    expected_swan_keys = {
        "KeyY1": "control_key_y1",
        "KeyY2": "control_key_y2",
        "KeyY3": "control_key_y3",
        "KeyY4": "control_key_y4",
        "KeyA": "control_key_a",
        "KeyB": "control_key_b",
    }
    if {name: swan_connections.get(name) for name in expected_swan_keys} != expected_swan_keys:
        raise ValueError("SwanTop keypad bypasses the control-layout mapper")

    frame_connections = instance_connections(
        wonderswan, "apf_frame_orientation", "frame_orientation"
    )
    transition_connections = instance_connections(
        wonderswan, "apf_orientation_transition_guard", "orientation_transition"
    )
    if frame_connections.get("producer_orientation") != "vertical":
        raise ValueError("display frame orientation no longer follows native vertical")
    if transition_connections.get("producer_orientation") != "vertical":
        raise ValueError("display transition guard no longer follows native vertical")
    if "configured_control_layout" in frame_connections.values():
        raise ValueError("control layout leaked into frame orientation")
    if "configured_control_layout" in transition_connections.values():
        raise ValueError("control layout leaked into display transition orientation")
    require_fragment(
        wonderswan,
        "assignis_vertical=presented_vertical;",
        "Pocket display orientation output no longer reports the presented native frame",
    )

    assignment = "set_global_assignment-nameSYSTEMVERILOG_FILEcore/apf_control_layout.sv"
    if compact(qsf).count(assignment) != 1:
        raise ValueError("Quartus project does not compile exactly one apf_control_layout source")


def load_bundle() -> dict[str, object]:
    return {
        "interact": json.loads((CORE_DIR / "interact.json").read_text(encoding="utf-8")),
        "core_top": (ROOT / "src/fpga/core/core_top.v").read_text(encoding="utf-8"),
        "cdc": (ROOT / "src/fpga/core/apf_settings_cdc.sv").read_text(encoding="utf-8"),
        "sdc": (ROOT / "src/fpga/core/core_constraints.sdc").read_text(encoding="utf-8"),
        "mapper": (ROOT / "src/fpga/core/apf_control_layout.sv").read_text(encoding="utf-8"),
        "wonderswan": (ROOT / "src/fpga/core/wonderswan.sv").read_text(encoding="utf-8"),
        "qsf": (ROOT / "src/fpga/ap_core.qsf").read_text(encoding="utf-8"),
    }


def replaced(source: object, old: str, new: str) -> str:
    if not isinstance(source, str) or source.count(old) != 1:
        raise AssertionError(f"test mutation source is missing or ambiguous: {old!r}")
    return source.replace(old, new, 1)


def main() -> None:
    bundle = load_bundle()
    verify_contract(bundle)

    mutations: list[tuple[str, tuple[str, object]]] = []
    for name, path, value in (
        ("interact ID", ("id",), 47),
        ("interact address", ("address",), "0x218"),
        ("interact default", ("defaultval",), 1),
        ("interact persistence", ("persist",), False),
        ("interact write-only", ("writeonly",), True),
        ("Auto option", ("options", 0, "name"), "Native"),
        ("Horizontal encoding", ("options", 1, "value"), 2),
        ("Vertical encoding", ("options", 2, "value"), 3),
    ):
        changed = copy.deepcopy(bundle["interact"])
        target = changed["interact"]["variables"]
        entry = next(item for item in target if item.get("id") == 46)
        cursor = entry
        for component in path[:-1]:
            cursor = cursor[component]
        cursor[path[-1]] = value
        mutations.append((name, ("interact", changed)))

    text_mutations = (
        (
            "bridge address",
            "core_top",
            "32'h214: begin",
            "32'h218: begin",
        ),
        (
            "bridge invalid encoding",
            "core_top",
            "configured_control_layout <=\n"
            "              bridge_wr_data > 32'd2 ? 2'd0 : bridge_wr_data[1:0]",
            "configured_control_layout <=\n"
            "              bridge_wr_data > 32'd3 ? 2'd0 : bridge_wr_data[1:0]",
        ),
        (
            "bridge low-bit alias",
            "core_top",
            "bridge_wr_data > 32'd2 ? 2'd0 : bridge_wr_data[1:0]",
            "bridge_wr_data[1:0] > 2'd2 ? 2'd0 : bridge_wr_data[1:0]",
        ),
        (
            "bridge fallback",
            "core_top",
            "configured_control_layout <=\n              bridge_wr_data > 32'd2 ? 2'd0",
            "configured_control_layout <=\n              bridge_wr_data > 32'd2 ? 2'd1",
        ),
        (
            "snapshot width",
            "core_top",
            "wire [12:0] settings_snapshot_s;",
            "wire [11:0] settings_snapshot_s;",
        ),
        (
            "source packing",
            "core_top",
            "configured_orientation,\n    configured_control_layout,",
            "configured_control_layout,\n    configured_orientation,",
        ),
        (
            "destination unpacking",
            "core_top",
            "configured_orientation_s,\n    configured_control_layout_s,",
            "configured_control_layout_s,\n    configured_orientation_s,",
        ),
        (
            "console snapshot integration",
            "core_top",
            ".configured_control_layout(configured_control_layout_s)",
            ".configured_control_layout(configured_control_layout)",
        ),
        (
            "CDC payload width",
            "cdc",
            "input  wire [12:0] settings_source",
            "input  wire [11:0] settings_source",
        ),
        (
            "CDC atomic capture",
            "cdc",
            "settings_destination <= settings_hold_source;",
            "settings_destination <= settings_source;",
        ),
        (
            "CDC default",
            "cdc",
            "parameter [12:0] DEFAULT_SETTINGS = 13'h0201",
            "parameter [12:0] DEFAULT_SETTINGS = 13'h0000",
        ),
        (
            "source SDC cardinality",
            "sdc",
            "[get_collection_size $settings_source_registers] != 13",
            "[get_collection_size $settings_source_registers] != 12",
        ),
        (
            "destination SDC cardinality",
            "sdc",
            "[get_collection_size $settings_destination_registers] != 13",
            "[get_collection_size $settings_destination_registers] != 12",
        ),
        (
            "forced Horizontal",
            "mapper",
            "configured_layout == 2'd1 ? 1'b0",
            "configured_layout == 2'd1 ? 1'b1",
        ),
        (
            "forced Vertical",
            "mapper",
            "configured_layout == 2'd2 ? 1'b1",
            "configured_layout == 2'd2 ? 1'b0",
        ),
        (
            "invalid fail-closed",
            "mapper",
            "      native_vertical;",
            "      1'b0;",
        ),
        (
            "vertical keypad mapping",
            "mapper",
            "assign key_y2 = controls_vertical ? button_a : button_trig_r;",
            "assign key_y2 = controls_vertical ? button_b : button_trig_r;",
        ),
        (
            "mapper native orientation",
            "wonderswan",
            ".native_vertical(vertical)",
            ".native_vertical(1'b0)",
        ),
        (
            "SwanTop mapper bypass",
            "wonderswan",
            ".KeyY1   (control_key_y1)",
            ".KeyY1   (button_trig_l)",
        ),
        (
            "frame display orientation",
            "wonderswan",
            ".producer_orientation(vertical),\n"
            "      .consumer_frame_boundary(scanout_frame_boundary)",
            ".producer_orientation(configured_control_layout[0]),\n"
            "      .consumer_frame_boundary(scanout_frame_boundary)",
        ),
        (
            "presented display orientation",
            "wonderswan",
            "assign is_vertical = presented_vertical;",
            "assign is_vertical = configured_control_layout[0];",
        ),
        (
            "Quartus mapper source",
            "qsf",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_control_layout.sv",
            "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_control_layout_missing.sv",
        ),
    )
    for name, field, old, new in text_mutations:
        mutations.append((name, (field, replaced(bundle[field], old, new))))

    rejected = 0
    for name, (field, value) in mutations:
        mutated = dict(bundle)
        mutated[field] = value
        try:
            verify_contract(mutated)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError(f"control-layout contract accepted mutation: {name}")

    print(
        "PASS Pocket Control Layout source+mutation contract "
        f"({rejected} adversarial mutations rejected)"
    )


if __name__ == "__main__":
    main()
