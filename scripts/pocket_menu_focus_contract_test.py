#!/usr/bin/env python3
"""Mutation-lock PocketOS menu pause, input ownership, and resume safety."""

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
    menu_cdc = compact(sources["menu_cdc"])
    constraints = compact(sources["constraints"]).replace("\\", "")
    wonderswan = compact(sources["wonderswan"])
    swan_top = compact(sources["swan_top"])
    rtc = compact(sources["rtc"])
    i2s = compact(sources["i2s"])
    fast_forward = compact(sources["fast_forward"])
    pause_tb = compact(sources["pause_tb"])
    pause_runner = sources["pause_runner"]

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
        "apf_menu_focus_cdcmenu_focus_system_cdc(",
        ".clk_destination(clk_sys_36_864)",
        ".reset_n_async(reset_n)",
        ".menu_focus_source(osnotify_inmenu)",
        ".menu_focus_destination(menu_focus_sys_s)",
        ".physical_input_blocked(physical_input_blocked_sys_s)",
        ".menu_focus_paused(menu_focus_sys_s)",
    ):
        if fragment not in core_top:
            raise ValueError(f"top-level focus boundary is missing {fragment}")
    if ".button_start(cont1_key_s[15])" not in core_top:
        raise ValueError("focus filtering changed the logical Start mapping")
    if core_top.count(".menu_focus_source(osnotify_inmenu)") != 1:
        raise ValueError("raw 00B0 must feed exactly the menu-pause CDC")
    if "synch_3#(.width(16))cont1_s(" in core_top:
        raise ValueError("physical buttons still cross as a tearable vector synchronizer")
    for forbidden in (
        ".menu_focus_paused(osnotify_inmenu)",
        ".menu_focus_paused(physical_input_blocked_sys_s)",
        ".menu_focus_source(physical_input_blocked_74a)",
    ):
        if forbidden in core_top:
            raise ValueError(
                "menu pause bypassed its dedicated CDC or became coupled to PAD rearm"
            )

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
        "moduleapf_menu_focus_cdc(",
        "inputwireclk_destination",
        "inputwirereset_n_async",
        "inputwiremenu_focus_source",
        "outputwiremenu_focus_destination",
        "assignmenu_focus_destination=menu_focus_level;",
        "always@(posedgeclk_destinationornegedgereset_n_async)begin",
        "if(!reset_n_async)beginmenu_focus_meta<=1'b0;menu_focus_sync<=1'b0;menu_focus_level<=1'b0;end",
        "menu_focus_meta<=menu_focus_source;menu_focus_sync<=menu_focus_meta;menu_focus_level<=menu_focus_sync;",
    ):
        if fragment not in menu_cdc:
            raise ValueError(f"dedicated menu-focus level CDC is missing {fragment}")
    if menu_cdc.count("synchronizer_identificationforced") != 3 or menu_cdc.count(
        "preserve_registeron"
    ) != 3:
        raise ValueError("menu-focus CDC lacks three native synchronizer assignments")

    for fragment in (
        "ic|input_state_system_cdc|payload_hold_source[*]",
        "if{$input_state_source_count!=17}",
        "if{$input_state_destination_count!=13}",
    ):
        if fragment not in constraints:
            raise ValueError(f"atomic input-state SDC is missing {fragment}")
    for index in (*range(10), 14, 15, 16):
        fragment = f"ic|input_state_system_cdc|payload_destination[{index}]"
        if constraints.count(fragment) != 2:
            raise ValueError(f"atomic input-state SDC is missing exact destination {index}")
    for index in range(10, 14):
        fragment = f"ic|input_state_system_cdc|payload_destination[{index}]"
        if fragment in constraints:
            raise ValueError(f"input-state SDC includes unused destination {index}")
    cdc_from_to = (
        "-from$input_state_source_registers_expanded"
        "-to$input_state_destination_registers_expanded"
    )
    if constraints.count(cdc_from_to) != 2:
        raise ValueError("input-state payload requires exact net-delay and max-skew bounds")

    for fragment in (
        "inputwirephysical_input_blocked",
        "inputwiremenu_focus_paused",
        "wirepaused=menu_focus_paused;",
        ".pause_in(paused)",
        "apf_fast_forward_controlfast_forward_control(",
        ".reset_n(reset_n_sys)",
        ".clear_state(external_reset||cart_download_sys||physical_input_blocked)",
        ".button_select(button_select)",
        ".fast_forward(fast_forward)",
    ):
        if fragment not in wonderswan:
            raise ValueError(f"Fast Forward lifecycle integration is missing {fragment}")
    if "paused=physical_input_blocked" in wonderswan:
        raise ValueError("console pause incorrectly waits for physical-input neutral rearm")

    # The actual SwanTop scheduler must gate every emulation enable, retain its
    # refresh watchdog while paused, and impose the existing three-cycle resume
    # warmup. CPU consumes ce_cpu; DMA/GPU/sound consume ce. RTC deliberately
    # consumes raw clk so cartridge wall time continues in the OS menu.
    for fragment in (
        "ce<='0';ce_cpu<='0';ce_4x<='0';normalrefresh<='0';",
        "pause_in='1'ormemories_pause_gate='1'",
        "if(refreshcnt=127)thennormalrefresh<='1';refreshcnt<=0;endif;startwait<=3;",
        "ce=>ce_cpu",
        "idma:entitywork.dma",
        "igpu:entitywork.gpu",
        "isound:entitywork.sound",
        "irtc:entitywork.rtc",
        "clk=>clk,ce=>ce",
    ):
        if fragment not in swan_top:
            raise ValueError(f"SwanTop menu-pause semantics are missing {fragment}")
    for consumer in ("idma", "igpu", "isound"):
        start = swan_top.index(f"{consumer}:entitywork.")
        if "ce=>ce" not in swan_top[start : start + 500]:
            raise ValueError(f"{consumer} no longer consumes the pause-gated console CE")
    rtc_start = swan_top.index("irtc:entitywork.rtc")
    if "clk=>clk" not in swan_top[rtc_start : rtc_start + 500]:
        raise ValueError("RTC no longer receives the raw console-domain clock")
    for forbidden in ("if(ce='1')", "ifce='1'", "rising_edge(ce)"):
        if forbidden in rtc:
            raise ValueError("RTC wall clock incorrectly became console-CE gated")
    for fragment in (
        "if(secondcount<36863999)thensecondcount<=secondcount+1;",
        "producer_frame_done=pixel_we&&pixel_addr==32255;",
        ".write_enable(pixel_we&&framebank_write==3'd0)",
    ):
        target = rtc if "secondcount" in fragment else wonderswan
        if fragment not in target:
            raise ValueError(f"paused RTC/frame stability contract is missing {fragment}")
    for fragment in (
        "always@(posedgeclk_audio)begin",
        "if(audio_l!=prev_left||audio_r!=prev_right)beginwrite_en<=1;",
        "always@(posedgeclk_74a)begin",
    ):
        if fragment not in i2s:
            raise ValueError(f"I2S held-sample continuity is missing {fragment}")
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
        "core/apf_menu_focus_cdc.sv",
        "core/apf_fast_forward_control.sv",
    ):
        if sources["qsf"].count(
            f"set_global_assignment -name SYSTEMVERILOG_FILE {module}"
        ) != 1:
            raise ValueError(f"Quartus project does not compile exactly one {module}")
    for hook in (
        '"$ROOT/sim/rtl/run_apf_gamepad_filter_tb.sh"',
        '"$ROOT/sim/rtl/run_apf_input_blocked_cdc_tb.sh"',
        '"$ROOT/sim/rtl/run_apf_menu_focus_cdc_tb.sh"',
        '"$ROOT/sim/rtl/run_apf_menu_focus_pause_tb.sh"',
        '"$ROOT/sim/rtl/run_swantop_menu_pause_tb.sh"',
        '"$ROOT/sim/rtl/run_apf_fast_forward_control_tb.sh"',
        '"$ROOT/sim/rtl/run_apf_i2s_waveform_tb.sh"',
        'python3 "$ROOT/scripts/pocket_menu_focus_contract_test.py"',
    ):
        if hook not in sources["regression"]:
            raise ValueError(f"regression is missing focus-safety gate {hook}")

    # SwanTop's CPU-side EXTRAM request is a one-clk_sys pulse. The translated
    # test must validate and capture its payload while that pulse is live, then
    # stop interpreting the combinational address/BE/data outputs after it
    # falls. Across pause, cardinality and the delayed returned read value are
    # the valid contracts. Also reject accidental duplicate bus declarations,
    # which Verilator reports only after the expensive VHDL translation step.
    for declaration in (
        "wireextram_read;",
        "wireextram_write;",
        "wire[1:0]extram_be;",
        "wire[24:0]extram_addr;",
        "wire[15:0]extram_datawrite;",
    ):
        if pause_tb.count(declaration) != 1:
            raise ValueError(
                f"translated pause test requires exactly one declaration {declaration}"
            )
    for fragment in (
        ".extram_be(extram_be)",
        ".extram_addr(extram_addr)",
        ".extram_datawrite(extram_datawrite)",
        ".open_ipl_word_width(open_ipl_word_width)",
        ".open_ipl_protect_owner_area(open_ipl_protect_owner_area)",
        "regopen_ipl_word_width=1'b1;",
        "regopen_ipl_protect_owner_area=1'b1;",
        "functionautomatic[15:0]cartridge_word(input[24:0]byte_address);",
        "cartridge_reset_address+25'h0:cartridge_word=16'h00ea;",
        "cartridge_reset_address+25'h2:cartridge_word=16'h0001;",
        "cartridge_reset_address+25'h4:cartridge_word=16'h9020;",
        "extram_dataread<=cartridge_word(captured_read_addr);",
        "extram_addr!=expected_address||extram_be!=expected_be",
        "expected_write&&extram_datawrite!=expected_write_data",
        "captured_read_addr<=extram_addr;",
        "captured_write_addr<=extram_addr;",
        "captured_write_be<=extram_be;",
        "captured_write_data<=extram_datawrite;",
        "read_delay<=6'd14;",
        "write_delay<=6'd9;",
        'if(extram_read||extram_write)$fatal(1,"%sexternalrequestreplayedwhilepaused",label_text);',
        "response_seen&&extram_dataread!=expected_read_data",
        '"%sreturneddatawasnotheldwhilepaused"',
        "extram_dataread!=expected_read_data",
        "rom_read_episodes!=1||sram_write_episodes!=1||sram_read_episodes!=1",
        "memory_read_completions!=2||memory_write_commits!=1",
        "rom_marker_count!=1||sram_marker_count!=1",
    ):
        if fragment not in pause_tb:
            raise ValueError(
                f"translated pause test omits edge/cardinality/response proof {fragment}"
            )
    for forbidden in (
        "bios_wraddr",
        "bios_wrdata",
        "bios_wrcolor",
        "write_bios_word",
        "load_clean_bios",
        "held_address",
        "held_be",
        "held_write_data",
        "externalrequestpayloadchangedwhilepaused",
    ):
        if forbidden in pause_tb:
            raise ValueError(
                f"translated pause test treats post-pulse EXTRAM metadata as live: {forbidden}"
            )
    paused_loop_start = pause_tb.index(
        "for(index=0;index<260;index=index+1)begin"
    )
    paused_loop_end = pause_tb.index("phase_after=", paused_loop_start)
    paused_loop = pause_tb[paused_loop_start:paused_loop_end]
    for post_pulse_signal in ("extram_addr", "extram_be", "extram_datawrite"):
        if post_pulse_signal in paused_loop:
            raise ValueError(
                "translated pause test reads live EXTRAM metadata after its "
                f"request pulse: {post_pulse_signal}"
            )
    for fragment in (
        "for fastforward in 0 1; do",
        "for ram_phase_ps in 0 833 1666 2499; do",
        '"+fastforward=$fastforward"',
        '"+ram_phase_ps=$ram_phase_ps"',
        "passes=$((passes + 1))",
        'if [[ "$passes" -ne 8 ]]; then',
    ):
        if fragment not in pause_runner:
            raise ValueError(
                f"translated pause runner omits mode/clock-phase matrix {fragment}"
            )

    docs = sources["input_doc"] + sources["controls_doc"]
    for phrase in (
        "physical gameplay input is blocked",
        "valid neutral",
        "pauses the emulated console",
        "product choice",
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
        "menu_cdc": ROOT / "src/fpga/core/apf_menu_focus_cdc.sv",
        "constraints": ROOT / "src/fpga/core/core_constraints.sdc",
        "wonderswan": ROOT / "src/fpga/core/wonderswan.sv",
        "swan_top": ROOT / "src/fpga/core/rtl/swanTop.vhd",
        "rtc": ROOT / "src/fpga/core/rtl/rtc.vhd",
        "i2s": ROOT / "src/fpga/core/sound_i2s.sv",
        "fast_forward": ROOT / "src/fpga/core/apf_fast_forward_control.sv",
        "pause_tb": ROOT / "sim/rtl/swantop_menu_pause_tb.sv",
        "pause_runner": ROOT / "sim/rtl/run_swantop_menu_pause_tb.sh",
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
            ".menu_focus_source(osnotify_inmenu)",
            ".menu_focus_source(physical_input_blocked_74a)",
        ),
        ("core_top", ".menu_focus_destination(menu_focus_sys_s)", ".menu_focus_destination()"),
        ("core_top", ".menu_focus_paused(menu_focus_sys_s)", ".menu_focus_paused(physical_input_blocked_sys_s)"),
        ("core_top", ".key_word_updated(cont1_key_updated)", ".key_word_updated(1'b1)"),
        ("core_top", ".button_start(cont1_key_s[15])", ".button_start(1'b0)"),
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
        ("menu_cdc", "menu_focus_level <= menu_focus_sync;", "menu_focus_level <= menu_focus_meta;"),
        ("menu_cdc", "or negedge reset_n_async", ""),
        (
            "constraints",
            "if {$input_state_source_count != 17}",
            "if {$input_state_source_count != 16}",
        ),
        (
            "constraints",
            "if {$input_state_destination_count != 13}",
            "if {$input_state_destination_count != 12}",
        ),
        (
            "constraints",
            "-to $input_state_destination_registers_expanded",
            "-to $settings_destination_registers",
        ),
        ("wonderswan", "external_reset || cart_download_sys || physical_input_blocked", "cart_download_sys || physical_input_blocked"),
        ("wonderswan", "external_reset || cart_download_sys || physical_input_blocked", "external_reset || physical_input_blocked"),
        ("wonderswan", "external_reset || cart_download_sys || physical_input_blocked", "external_reset || cart_download_sys"),
        ("wonderswan", "wire paused = menu_focus_paused;", "wire paused = physical_input_blocked;"),
        ("swan_top", "pause_in = '1' or memories_pause_gate = '1'", "memories_pause_gate = '1'"),
        ("swan_top", "startwait <= 3;", "startwait <= 0;"),
        ("rtc", "secondcount <= secondcount + 1;", "secondcount <= secondcount;"),
        ("fast_forward", "if (!reset_n || clear_state)", "if (!reset_n)"),
        ("fast_forward", "reset_n && !clear_state", "reset_n"),
        ("qsf", "core/apf_input_blocked_cdc.sv", "core/missing_input_blocked_cdc.sv"),
        ("qsf", "core/apf_menu_focus_cdc.sv", "core/missing_menu_focus_cdc.sv"),
        ("qsf", "core/apf_fast_forward_control.sv", "core/missing_fast_forward_control.sv"),
        ("regression", "run_apf_input_blocked_cdc_tb.sh", "run_missing_input_blocked_cdc_tb.sh"),
        ("regression", "run_apf_menu_focus_pause_tb.sh", "run_missing_menu_focus_pause_tb.sh"),
        ("regression", "pocket_menu_focus_contract_test.py", "missing_menu_focus_contract_test.py"),
        (
            "pause_tb",
            "wire [1:0] EXTRAM_be;",
            "wire [1:0] EXTRAM_be;\n  wire [1:0] EXTRAM_be;",
        ),
        (
            "pause_tb",
            "EXTRAM_addr != expected_address || EXTRAM_be != expected_be",
            "EXTRAM_be != expected_be",
        ),
        (
            "pause_tb",
            "captured_write_data <= EXTRAM_datawrite;",
            "captured_write_data <= 16'd0;",
        ),
        (
            "pause_tb",
            'if (EXTRAM_read || EXTRAM_write)\n          $fatal(1, "%s external request replayed while paused", label_text);',
            'if (1\'b0)\n          $fatal(1, "%s external request replayed while paused", label_text);',
        ),
        (
            "pause_tb",
            "response_seen && EXTRAM_dataread != expected_read_data",
            "1'b0",
        ),
        (
            "pause_tb",
            "rom_read_episodes != 1 || sram_write_episodes != 1",
            "rom_read_episodes != 0 || sram_write_episodes != 1",
        ),
        (
            "pause_tb",
            "if (pixel_out_we)",
            "if (EXTRAM_addr != expected_address) $fatal(1, \"live metadata changed\");\n        if (pixel_out_we)",
        ),
        (
            "pause_runner",
            "for fastforward in 0 1; do",
            "for fastforward in 0; do",
        ),
        (
            "pause_runner",
            "for ram_phase_ps in 0 833 1666 2499; do",
            "for ram_phase_ps in 0; do",
        ),
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
        "PASS PocketOS menu-pause/input safety contract "
        f"({rejected} adversarial mutations rejected)"
    )


if __name__ == "__main__":
    main()
