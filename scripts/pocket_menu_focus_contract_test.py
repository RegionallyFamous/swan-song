#!/usr/bin/env python3
"""Mutation-lock PocketOS focus ownership and Fast Forward lifecycle safety."""

from __future__ import annotations

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parent.parent


def active(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def compact(source: str) -> str:
    return re.sub(r"\s+", "", active(source)).lower()


def verify_contract(sources: dict[str, str]) -> None:
    pad = compact(sources["pad"])
    apf_top = compact(sources["apf_top"])
    core_top = compact(sources["core_top"])
    gamepad = compact(sources["gamepad"])
    cdc = compact(sources["cdc"])
    constraints = compact(sources["constraints"]).replace("\\", "")
    wonderswan = compact(sources["wonderswan"])
    fast_forward = compact(sources["fast_forward"])

    for fragment in (
        "outputregcont1_key_updated",
        "cont1_key_updated<=0;",
        "cont1_key<=rx_word;cont1_key_updated<=1;",
    ):
        if fragment not in pad:
            raise ValueError(f"PAD fresh-P1-sample contract is missing {fragment}")
    if pad.count("cont1_key_updated<=1;") != 1:
        raise ValueError("PAD must pulse fresh-P1-sample only at the P1 key word")
    for fragment in (
        "wirecont1_key_updated;",
        ".cont1_key_updated(cont1_key_updated)",
    ):
        if fragment not in apf_top:
            raise ValueError(f"APF top omits fresh P1 sample transport {fragment}")
    if apf_top.count(".cont1_key_updated(cont1_key_updated)") != 2:
        raise ValueError("fresh P1 sample must connect PAD controller to core top")

    for controller_type in ("type_pocket", "type_dock_digital", "type_dock_analog"):
        if f"key_word[31:28]=={controller_type}" not in gamepad:
            raise ValueError(f"focus guard omits valid gamepad class {controller_type}")
    for fragment in (
        "elseif(os_focus_lost)beginbuttons<=16'd0;wait_for_neutral<=1'b1;input_blocked<=1'b1;end",
        "elseif(wait_for_neutral)beginbuttons<=16'd0;",
        "if(key_word_updated&&neutral_gamepad)begin",
        "wireneutral_gamepad=valid_gamepad&&key_word[15:0]==16'd0;",
    ):
        if fragment not in gamepad:
            raise ValueError(f"focus/neutral-rearm guard is missing {fragment}")
    if "key_word_updated||neutral_gamepad" in gamepad:
        raise ValueError("invalid or stale PAD data can rearm physical input")

    for fragment in (
        "inputwirecont1_key_updated",
        ".os_focus_lost(osnotify_inmenu)",
        ".key_word_updated(cont1_key_updated)",
        ".input_blocked(physical_input_blocked_74a)",
        "apf_input_blocked_cdcinput_state_system_cdc(",
        ".clk_source(clk_74a)",
        ".buttons_source(cont1_gamepad_key_74a)",
        ".input_blocked_source(physical_input_blocked_74a)",
        ".buttons_destination(cont1_key_s)",
        ".input_blocked_destination(physical_input_blocked_sys_s)",
        ".physical_input_blocked(physical_input_blocked_sys_s)",
    ):
        if fragment not in core_top:
            raise ValueError(f"top-level focus boundary is missing {fragment}")
    if ".button_start(cont1_key_s[15]|console_setup_start_sys_s)" not in core_top:
        raise ValueError("focus filtering removed the internal Console Setup Start gesture")
    if "synch_3#(.width(16))cont1_s(" in core_top:
        raise ValueError("physical buttons still cross as a tearable vector synchronizer")
    if any(
        fragment in core_top
        for fragment in (
            ".core_run_enable(osnotify_inmenu)",
            ".pause(osnotify_inmenu)",
            "assigncore_run_enable=osnotify_inmenu",
        )
    ):
        raise ValueError("menu focus must not become an emulation pause control")

    for fragment in (
        "localparam[16:0]safe_payload={1'b1,16'h0000};",
        "wire[16:0]canonical_payload_source=input_blocked_source?safe_payload:{1'b0,buttons_source};",
        "reg[16:0]payload_hold_source=safe_payload;",
        "wiretransfer_idle_source=acknowledge_sync_source==request_toggle_source;",
        "if(transfer_idle_source&&canonical_payload_source!=payload_hold_source)begin",
        "payload_hold_source<=canonical_payload_source;",
        "request_toggle_source<=~request_toggle_source;",
        "(*preserve,noprune*)reg[16:0]payload_destination=safe_payload;",
        "assign{input_blocked_destination,buttons_destination}=payload_destination;",
        "if(request_sync_destination!=request_seen_destination)begin",
        "payload_destination<=payload_hold_source;",
        "acknowledge_toggle_destination<=request_sync_destination;",
    ):
        if fragment not in cdc:
            raise ValueError(f"atomic input-state CDC is missing {fragment}")
    if cdc.count("synchronizer_identificationforced") != 4 or cdc.count(
        "preserve_registeron"
    ) != 4:
        raise ValueError("atomic input-state handshake lacks four native synchronizer assignments")

    for fragment in (
        "ic|input_state_system_cdc|payload_hold_source[*]",
        "ic|input_state_system_cdc|payload_destination[*]",
        "if{$input_state_source_count!=17}",
        "if{$input_state_destination_count!=17}",
    ):
        if fragment not in constraints:
            raise ValueError(f"atomic input-state SDC is missing {fragment}")
    cdc_from_to = (
        "-from$input_state_source_registers_expanded"
        "-to$input_state_destination_registers_expanded"
    )
    if constraints.count(cdc_from_to) != 2:
        raise ValueError("input-state payload requires exact net-delay and max-skew bounds")

    for fragment in (
        "inputwirephysical_input_blocked",
        "apf_fast_forward_controlfast_forward_control(",
        ".reset_n(reset_n_sys)",
        ".clear_state(external_reset||cart_download_sys||physical_input_blocked)",
        ".button_select(button_select)",
        ".fast_forward(fast_forward)",
    ):
        if fragment not in wonderswan:
            raise ValueError(f"Fast Forward lifecycle integration is missing {fragment}")
    for stale in ("regff_latch", "reglast_ffw", "longintff_count"):
        if stale in wonderswan:
            raise ValueError(f"unreset inherited Fast Forward state remains: {stale}")

    reset_body = (
        "if(!reset_n||clear_state)begin"
        "press_cycles<={counter_width{1'b0}};"
        "button_was_down<=1'b0;"
        "press_was_long<=1'b0;"
        "suppress_short_latch<=1'b0;"
        "fast_forward_latched<=1'b0;end"
    )
    if reset_body not in fast_forward:
        raise ValueError("Fast Forward clear does not reset every history/state element")
    if (
        "assignfast_forward=reset_n&&!clear_state&&"
        "(button_select||fast_forward_latched);"
    ) not in fast_forward:
        raise ValueError("Fast Forward output is not dominated by reset/focus/title clear")

    for module in (
        "core/apf_gamepad_filter.sv",
        "core/apf_input_blocked_cdc.sv",
        "core/apf_fast_forward_control.sv",
    ):
        if sources["qsf"].count(
            f"set_global_assignment -name SYSTEMVERILOG_FILE {module}"
        ) != 1:
            raise ValueError(f"Quartus project does not compile exactly one {module}")
    for hook in (
        '"$ROOT/sim/rtl/run_apf_gamepad_filter_tb.sh"',
        '"$ROOT/sim/rtl/run_apf_input_blocked_cdc_tb.sh"',
        '"$ROOT/sim/rtl/run_apf_fast_forward_control_tb.sh"',
        'python3 "$ROOT/scripts/pocket_menu_focus_contract_test.py"',
    ):
        if hook not in sources["regression"]:
            raise ValueError(f"regression is missing focus-safety gate {hook}")

    docs = sources["input_doc"] + sources["controls_doc"]
    for phrase in (
        "physical gameplay input is blocked",
        "valid neutral",
        "does not pause",
        "Console Setup",
    ):
        if phrase.casefold() not in docs.casefold():
            raise ValueError(f"focus-safety documentation is missing {phrase!r}")


def main() -> None:
    paths = {
        "pad": ROOT / "src/fpga/apf/io_pad_controller.v",
        "apf_top": ROOT / "src/fpga/apf/apf_top.v",
        "core_top": ROOT / "src/fpga/core/core_top.v",
        "gamepad": ROOT / "src/fpga/core/apf_gamepad_filter.sv",
        "cdc": ROOT / "src/fpga/core/apf_input_blocked_cdc.sv",
        "constraints": ROOT / "src/fpga/core/core_constraints.sdc",
        "wonderswan": ROOT / "src/fpga/core/wonderswan.sv",
        "fast_forward": ROOT / "src/fpga/core/apf_fast_forward_control.sv",
        "qsf": ROOT / "src/fpga/ap_core.qsf",
        "regression": ROOT / "scripts/regression.sh",
        "input_doc": ROOT / "FIRST_CLASS_INPUT_DOCK.md",
        "controls_doc": ROOT / "docs/wiki/Controls-and-Settings.md",
    }
    sources = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    verify_contract(sources)

    mutations = (
        ("pad", "cont1_key_updated <= 1;", "cont1_key_updated <= 0;"),
        ("apf_top", ".cont1_key_updated      ( cont1_key_updated )", ".cont1_key_updated      ( 1'b0 )"),
        ("gamepad", "else if (os_focus_lost)", "else if (1'b0)"),
        ("gamepad", "key_word_updated && neutral_gamepad", "neutral_gamepad"),
        ("gamepad", "valid_gamepad && key_word[15:0] == 16'd0", "key_word[15:0] == 16'd0"),
        ("core_top", ".os_focus_lost(osnotify_inmenu)", ".os_focus_lost(1'b0)"),
        (
            "core_top",
            ".os_focus_lost(osnotify_inmenu)",
            ".pause(osnotify_inmenu),\n      .os_focus_lost(osnotify_inmenu)",
        ),
        ("core_top", ".key_word_updated(cont1_key_updated)", ".key_word_updated(1'b1)"),
        ("core_top", "cont1_key_s[15] | console_setup_start_sys_s", "cont1_key_s[15]"),
        ("core_top", ".buttons_destination(cont1_key_s)", ".buttons_destination()"),
        (
            "core_top",
            "apf_input_blocked_cdc input_state_system_cdc (",
            "synch_3 #(.WIDTH(16)) cont1_s (\n"
            "      cont1_gamepad_key_74a, cont1_key_s, clk_sys_36_864);\n"
            "  apf_input_blocked_cdc input_state_system_cdc (",
        ),
        ("cdc", "canonical_payload_source != payload_hold_source", "1'b0"),
        ("cdc", "payload_hold_source <= canonical_payload_source;", "payload_hold_source <= SAFE_PAYLOAD;"),
        ("cdc", "(* preserve, noprune *)", ""),
        ("cdc", "payload_destination <= payload_hold_source;", "payload_destination <= SAFE_PAYLOAD;"),
        ("cdc", "acknowledge_toggle_destination <= request_sync_destination;", "acknowledge_toggle_destination <= acknowledge_toggle_destination;"),
        (
            "constraints",
            "if {$input_state_source_count != 17}",
            "if {$input_state_source_count != 16}",
        ),
        (
            "constraints",
            "-to $input_state_destination_registers_expanded",
            "-to $settings_destination_registers",
        ),
        ("wonderswan", "external_reset || cart_download_sys || physical_input_blocked", "cart_download_sys || physical_input_blocked"),
        ("wonderswan", "external_reset || cart_download_sys || physical_input_blocked", "external_reset || physical_input_blocked"),
        ("wonderswan", "external_reset || cart_download_sys || physical_input_blocked", "external_reset || cart_download_sys"),
        ("fast_forward", "if (!reset_n || clear_state)", "if (!reset_n)"),
        ("fast_forward", "reset_n && !clear_state", "reset_n"),
        ("qsf", "core/apf_input_blocked_cdc.sv", "core/missing_input_blocked_cdc.sv"),
        ("qsf", "core/apf_fast_forward_control.sv", "core/missing_fast_forward_control.sv"),
        ("regression", "run_apf_input_blocked_cdc_tb.sh", "run_missing_input_blocked_cdc_tb.sh"),
        ("regression", "pocket_menu_focus_contract_test.py", "missing_menu_focus_contract_test.py"),
    )

    rejected = 0
    for source_name, old, new in mutations:
        if old not in sources[source_name]:
            raise RuntimeError(f"mutation anchor missing in {source_name}: {old!r}")
        changed = dict(sources)
        changed[source_name] = changed[source_name].replace(old, new, 1)
        try:
            verify_contract(changed)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError(
                f"menu-focus contract accepted mutation in {source_name}: {old!r}"
            )

    print(
        "PASS PocketOS menu-focus/input safety contract "
        f"({rejected} adversarial mutations rejected)"
    )


if __name__ == "__main__":
    main()
