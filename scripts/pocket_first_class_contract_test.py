#!/usr/bin/env python3
"""Contract checks for the Analogue Pocket-facing core definition and wrapper."""

from __future__ import annotations

import json
import os
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE_DIR = ROOT / "dist/Cores/RegionallyFamous.SwanSong"

SOURCE_PATHS = {
    "bridge": "src/fpga/core/core_bridge_cmd.v",
    "core_top": "src/fpga/core/core_top.v",
    "guard": "src/fpga/core/apf_dataslot_guard.sv",
    "metadata": "src/fpga/core/apf_save_metadata_cdc.sv",
    "settings": "src/fpga/core/apf_settings_cdc.sv",
    "startup": "src/fpga/core/apf_startup_sequencer.sv",
    "save_init": "src/fpga/core/pocket_save_init.sv",
    "wonderswan": "src/fpga/core/wonderswan.sv",
    "rom_loader": "src/fpga/core/apf_rom_loader_adapter.sv",
    "chip32": "src/support/chip32.asm",
    "qsf": "src/fpga/ap_core.qsf",
    "regression": "scripts/regression.sh",
}


def load(name: str) -> dict:
    return json.loads((CORE_DIR / name).read_text(encoding="utf-8"))


def number(value: int | str) -> int:
    return int(value, 0) if isinstance(value, str) else value


def source_bundle() -> dict[str, str]:
    return {
        name: (ROOT / relative).read_text(encoding="utf-8")
        for name, relative in SOURCE_PATHS.items()
    }


def strip_hdl_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def compact_hdl(source: str) -> str:
    return re.sub(r"\s+", "", strip_hdl_comments(source))


def first_class_source_errors(sources: dict[str, str]) -> list[str]:
    """Verify the isolated APF blocks and command boundary as one contract."""

    errors: list[str] = []
    bridge = strip_hdl_comments(sources["bridge"])
    bridge_compact = compact_hdl(sources["bridge"])
    core_top = strip_hdl_comments(sources["core_top"])
    core_top_compact = compact_hdl(sources["core_top"])
    guard = strip_hdl_comments(sources["guard"])
    guard_compact = compact_hdl(sources["guard"])
    metadata = strip_hdl_comments(sources["metadata"])
    metadata_compact = compact_hdl(sources["metadata"])
    settings_compact = compact_hdl(sources["settings"])
    startup = strip_hdl_comments(sources["startup"])
    startup_compact = compact_hdl(sources["startup"])
    save_init = strip_hdl_comments(sources["save_init"])
    save_compact = compact_hdl(sources["save_init"])
    wonderswan = strip_hdl_comments(sources["wonderswan"])
    wonderswan_compact = compact_hdl(sources["wonderswan"])
    rom_loader_compact = compact_hdl(sources["rom_loader"])
    chip32_compact = compact_hdl(sources["chip32"])

    # Host command 0082 carries a 48-bit byte count: parameter 0 upper half is
    # size[47:32], parameter 1 is size[31:0], and parameter 0 lower half is ID.
    if not re.search(
        r"output\s+reg\s*\[\s*47\s*:\s*0\s*\]\s*"
        r"dataslot_requestwrite_size\b",
        bridge,
    ):
        errors.append("0082 request must have a 48-bit 0082 declaration")
    if "dataslot_requestwrite_size<={host_20[31:16],host_24};" not in bridge_compact:
        errors.append("0082 request must use exact 48-bit 0082 assembly")
    if "dataslot_requestwrite_id<=host_20[15:0];" not in bridge_compact:
        errors.append("0082 slot ID must remain in parameter-0 low 16 bits")

    # 0080/0082 have three documented results. A boolean OK loses the distinct
    # permanent-rejection and retry-later states, so both sides remain 2-bit.
    for signal, label in (
        ("dataslot_requestread_result", "read"),
        ("dataslot_requestwrite_result", "write"),
    ):
        if not re.search(
            rf"input\s+wire\s*\[\s*1\s*:\s*0\s*\]\s*{signal}\b",
            bridge,
        ):
            errors.append(f"{label} result code must be explicit 2-bit")
        if f"host_resultcode<={{14'd0,{signal}}};" not in bridge_compact:
            errors.append(f"bridge must zero-extend {label} result code")

    # Reset Exit cannot start execution until the startup sequencer has emitted
    # Ready to Run and published its persistent startup_complete level.
    startup_requirements = (
        "wireall_startup_requirements="
        "(data_slots_seen||data_slots_all_complete)&&"
        "(rtc_seen||rtc_notification_observed)&&"
        "loaders_ready&&initializers_ready;"
    )
    if startup_requirements not in startup_compact:
        errors.append("startup gating must require 008F, 0090, loaders, and initializers")
    if startup_compact.count("ready_to_run_pulse<=1'b1;") != 1:
        errors.append("startup gating must issue exactly one Ready-to-Run source pulse")
    if (
        "ready_to_run_pulse<=1'b1;startup_complete<=1'b1;state<=STATE_IDLE;"
        not in startup_compact
    ):
        errors.append("Ready-to-Run must atomically publish completion and enter Idle")
    if (
        "if(ready_to_run_complete&&reset_exit_ready)begin"
        "reset_n<=1;hstate<=ST_DONE_OK;end"
        not in bridge_compact
    ):
        errors.append("Reset Exit must wait for startup and settings acknowledgement")
    if (
        "assignupdate_pending_source=transfer_busy_source||"
        "settings_source!=settings_hold_source;"
        not in settings_compact
    ):
        errors.append("settings pending must cover in-flight and superseding payloads")
    if (
        "wiresettings_reset_exit_ready_74a=!settings_write_74a&&"
        "!settings_update_pending_74a;"
        not in core_top_compact
        or ".reset_exit_ready(settings_reset_exit_ready_74a),"
        not in core_top_compact
    ):
        errors.append("core_top must fence Reset Exit on the acknowledged settings CDC")
    settings_write_match = re.search(
        r"wire\s+settings_write_74a\s*=\s*bridge_wr\s*&&\s*(.*?);",
        core_top,
        flags=re.DOTALL,
    )
    settings_write_compact = (
        re.sub(r"\s+", "", settings_write_match.group(1))
        if settings_write_match
        else ""
    )
    settings_addresses = (
        "32'h00000100",
        "32'h00000110",
        "32'h00000200",
        "32'h00000204",
        "32'h00000208",
        "32'h0000020c",
        "32'h00000210",
        "32'h00000214",
        "32'h00000300",
    )
    if not all(address in settings_write_compact for address in settings_addresses):
        errors.append("same-cycle settings write guard must cover every interact register")
    if bridge_compact.count("reset_exit_ready") != 2:
        errors.append("settings acknowledgement may qualify only Reset Exit")
    if "run_apf_settings_boot_barrier_tb.sh" not in sources["regression"]:
        errors.append("regression must run the asynchronous settings boot barrier test")
    if (
        "if(!status_setup_done)beginready_to_run_complete<=0;end"
        not in bridge_compact
        or "ready_to_run_complete<=status_setup_done;" not in bridge_compact
    ):
        errors.append("target 0140 acknowledgement must not cross title lifecycles")
    if "assigncore_run_enable=status_running;" not in startup_compact:
        errors.append("execution enable must follow truthful Running status")

    # Footer metadata is a bundled 21-bit snapshot, held until an acknowledged
    # toggle returns. Overlap is rejected and each clock has independent reset
    # release, preventing a torn size/RTC table entry.
    if not re.search(
        r"reg\s*\[\s*20\s*:\s*0\s*\]\s*metadata_hold\b", metadata
    ):
        errors.append("metadata CDC must hold one bundled 21-bit snapshot")
    for expression, error in (
        (
            "assignbusy_source=request_toggle!=acknowledge_sync;",
            "metadata CDC busy must span request through acknowledgement",
        ),
        (
            "metadata_hold<={has_rtc_source,save_size_bytes_source};",
            "metadata CDC must capture size and RTC atomically",
        ),
        (
            "{has_rtc_74a,save_size_bytes_74a}<=metadata_hold;",
            "metadata CDC must publish size and RTC atomically",
        ),
        (
            "if(commit_source&&!commit_previous)beginif(!busy_source)begin",
            "metadata CDC must accept only a fresh commit edge while idle",
        ),
        (
            "rejected_source<=1'b1;",
            "metadata CDC must explicitly reject an overlapping commit",
        ),
    ):
        if expression not in metadata_compact:
            errors.append(error)
    if (
        "always@(posedgeclk_sourceornegedgereset_n)" not in metadata_compact
        or "always@(posedgeclk_74aornegedgereset_n)" not in metadata_compact
    ):
        errors.append("metadata CDC reset must asynchronously assert in both domains")

    # The slot guard snapshots one request, evaluates actual policy/readiness,
    # returns one of the three explicit codes, and waits for request release.
    if not re.search(
        r"input\s+wire\s*\[\s*47\s*:\s*0\s*\]\s*request_size\b", guard
    ):
        errors.append("data-slot guard must preserve the 48-bit request size")
    if not re.search(
        r"output\s+reg\s*\[\s*1\s*:\s*0\s*\]\s*request_result\b", guard
    ):
        errors.append("data-slot guard result must be explicit 2-bit")
    for expression, error in (
        ("localparam[1:0]RESULT_READY=2'd0;", "guard result 0 must mean ready"),
        (
            "localparam[1:0]RESULT_NOT_ALLOWED=2'd1;",
            "guard result 1 must mean never allowed",
        ),
        (
            "localparam[1:0]RESULT_CHECK_LATER=2'd2;",
            "guard result 2 must mean check later",
        ),
        (
            "if(!policy_slot_known||!direction_allowed)begin",
            "data-slot guard must reject unknown slots and directions",
        ),
        (
            "elseif(!selected_loader_ready)beginrequest_result<=RESULT_CHECK_LATER;",
            "data-slot guard must retry while the selected loader is unavailable",
        ),
        (
            "captured_save_length<=latched_size;",
            "data-slot guard must retain the offered 48-bit save length",
        ),
        (
            "if(!request_valid)state<=STATE_IDLE;",
            "data-slot guard must wait for request release before re-arming",
        ),
    ):
        if expression not in guard_compact:
            errors.append(error)
    if guard_compact.count("request_ack<=1'b1;") != 1:
        errors.append("data-slot guard must have one acknowledgement source")

    # Save initialization is decided at load completion, before Ready to Run.
    # Host reset is intentionally not a trigger. Resolution is persistent until
    # the next per-title cart_download lifecycle.
    if not re.search(r"input\s+wire\s+load_complete\b", save_init):
        errors.append("save initializer must receive pre-Ready-to-Run load_complete")
    if not re.search(r"output\s+reg\s+initialization_resolved\b", save_init):
        errors.append("save initializer must expose persistent initialization_resolved")
    for expression, error in (
        (
            "wire[19:0]save_word_count=save_size_bytes>>1;",
            "save initializer must clear the exact selected word capacity",
        ),
        (
            "if(load_complete&&init_pending)begin",
            "save initializer must start only from load_complete",
        ),
        (
            "if(save_loaded||save_payload_write||save_word_count==0||"
            "!(save_is_sram||save_is_eeprom))begin",
            "loaded or nonpersistent saves must resolve without clearing",
        ),
    ):
        if expression not in save_compact:
            errors.append(error)
    if "prev_reset_n" in save_init:
        errors.append("host Reset Exit must not trigger save initialization")
    if save_compact.count("initialization_resolved<=1'b0;") != 1:
        errors.append("cart download must clear save initialization resolution once")
    if save_compact.count("initialization_resolved<=1'b1;") != 3:
        errors.append("loaded, SRAM, and EEPROM completion must each resolve initialization")

    # Mutation-lock the real wrapper wiring as well as the isolated blocks. Both
    # host request directions must reach one guard without narrowing the 48-bit
    # size or collapsing the three-valued result on the way back to the bridge.
    integration_requirements = (
        (
            core_top_compact,
            "wire[47:0]dataslot_requestwrite_size;",
            "core_top must preserve the bridge's full 48-bit 0082 size",
        ),
        (
            core_top_compact,
            "wiredataslot_request_valid=dataslot_requestread||dataslot_requestwrite;",
            "core_top guard must receive both 0080 and 0082 requests",
        ),
        (
            core_top_compact,
            "wire[47:0]dataslot_request_size=dataslot_requestwrite?"
            "dataslot_requestwrite_size:48'd0;",
            "core_top must pass the full 0082 size into the guard",
        ),
        (
            core_top_compact,
            "assigndataslot_requestread_ack=dataslot_guard_ack&&dataslot_requestread;",
            "core_top must return the guard acknowledgement to 0080",
        ),
        (
            core_top_compact,
            "assigndataslot_requestwrite_ack=dataslot_guard_ack&&dataslot_requestwrite;",
            "core_top must return the guard acknowledgement to 0082",
        ),
        (
            core_top_compact,
            "assigndataslot_requestread_result=dataslot_guard_result;",
            "core_top must return the full guard result to 0080",
        ),
        (
            core_top_compact,
            "assigndataslot_requestwrite_result=dataslot_guard_result;",
            "core_top must return the full guard result to 0082",
        ),
        (
            core_top_compact,
            ".request_valid(dataslot_request_valid),.request_write(dataslot_requestwrite),"
            ".request_id(dataslot_request_id),.request_size(dataslot_request_size),"
            ".request_ack(dataslot_guard_ack),.request_result(dataslot_guard_result),",
            "core_top must wire the complete host request through the data-slot guard",
        ),
        (
            wonderswan_compact,
            "save_metadata_commit<=cart_download_mem_previous&&!cart_download;",
            "WonderSwan must commit footer metadata at cartridge completion",
        ),
        (
            core_top_compact,
            ".save_metadata_commit(save_metadata_commit),",
            "core_top must receive the WonderSwan footer commit",
        ),
        (
            core_top_compact,
            "wiresave_metadata_commit_source=save_metadata_commit_pending_mem&&"
            "!save_metadata_cdc_busy;",
            "footer metadata commit must wait until the metadata CDC is available",
        ),
        (
            core_top_compact,
            "save_size_bytes_snapshot_mem<=save_size_bytes;"
            "has_rtc_snapshot_mem<=has_rtc;"
            "save_metadata_commit_pending_mem<=1'b1;",
            "footer metadata must be snapshotted while its CDC commit is queued",
        ),
        (
            core_top_compact,
            "elseif(save_metadata_commit_source)begin"
            "save_metadata_commit_pending_mem<=1'b0;",
            "footer metadata queue must retire only after starting its CDC transfer",
        ),
        (
            core_top_compact,
            "apf_save_metadata_cdcsave_metadata_command_cdc("
            ".reset_n(pll_core_locked),",
            "metadata CDC reset must remain independent of host Reset Enter",
        ),
        (
            core_top_compact,
            "apf_save_metadata_cdcsave_metadata_command_cdc("
            ".reset_n(pll_core_locked),.clk_source(clk_mem_110_592),"
            ".save_size_bytes_source(save_size_bytes_snapshot_mem),"
            ".has_rtc_source(has_rtc_snapshot_mem),"
            ".commit_source(save_metadata_commit_source),",
            "metadata CDC must consume the queued footer snapshot",
        ),
        (
            core_top_compact,
            "if(save_metadata_publish_pending&&dataslot_allcomplete)begin",
            "save-size table publication must wait for 008F",
        ),
        (
            core_top_compact,
            "synch_3dataslot_complete_to_memory(dataslot_allcomplete,"
            "dataslot_allcomplete_mem,clk_mem_110_592);",
            "008F must be synchronized into the save-initializer clock domain",
        ),
        (
            core_top_compact,
            ".load_complete(dataslot_allcomplete_mem),",
            "WonderSwan must receive synchronized 008F as load completion",
        ),
        (
            wonderswan_compact,
            ".load_complete(load_complete),",
            "WonderSwan must pass synchronized load completion to the save initializer",
        ),
        (
            core_top_compact,
            "synch_3save_initialization_to_bridge(save_initialization_resolved_mem,"
            "save_initialization_resolved_74a,clk_74a);",
            "save-initialization resolution must be synchronized to the startup domain",
        ),
        (
            core_top_compact,
            ".rtc_notification_observed(rtc_transfer_delivered),",
            "startup must observe delivered RTC data, not merely command receipt",
        ),
        (
            core_top_compact,
            ".initializers_ready(save_initialization_resolved_74a),",
            "startup must wait for resolved save initialization",
        ),
        (
            core_top_compact,
            "assignstatus_setup_done=startup_complete;",
            "status_setup_done must use persistent startup completion",
        ),
        (
            core_top_compact,
            ".ready_to_run_complete(ready_to_run_complete),",
            "core_top must retain the Pocket acknowledgement of target 0140",
        ),
        (
            core_top_compact,
            ".update_pending_source(settings_update_pending_74a),",
            "core_top must consume the settings CDC acknowledgement state",
        ),
        (
            core_top_compact,
            "apf_dataslot_guardpocket_dataslot_guard(.clk(clk_74a),"
            ".reset_n(pll_core_ready_74a),",
            "data-slot guard reset must remain independent of host Reset Enter",
        ),
        (
            core_top_compact,
            ".read_loader_ready(startup_complete&&!reset_n&&"
            "!execution_ready_74a&&save_backend_quiesced&&"
            "save_metadata_table_published&&save_initialization_resolved_74a),",
            "0080 flush must wait for real execution stop and backend quiescence",
        ),
        (
            core_top_compact,
            ".pll_core_locked(pll_core_ready_mem),",
            "footer commit reset must remain independent of host Reset Enter",
        ),
    )
    for source, expression, error in integration_requirements:
        if expression not in source:
            errors.append(error)

    # Chip32 asserts cart_download before LOADF and holds it until the 0082
    # transaction returns. Capture clearing therefore may not gate or abort the
    # guard FSM; it must run after the request case so only diagnostics clear.
    if (
        "endelsebegincase(state)" not in guard_compact
        or "endcaseif(captured_length_clear)begin" not in guard_compact
    ):
        errors.append("cart download capture clear must not block the request FSM")

    # There is exactly one table-write assertion, inside the 008F-qualified
    # publication branch checked above. This prevents an unqualified duplicate.
    if core_top_compact.count("datatable_wren<=1'b1;") != 1:
        errors.append("save-size table must have one 008F-qualified write source")

    # A LOADF word can be presented before the accepted-size CDC pulse. The
    # adapter must hold acknowledgement and SDRAM request low until the plan
    # for this external download is active. Prefix progress must be guaranteed
    # under a continuously held stream, and the Color flag must be sampled only
    # during the real LOADF window, never its reset/validation extension.
    compact_rom_requirements = (
        (
            "wireactivate_plan=cart_download&&(!plan_loaded||download_rise)&&"
            "(plan_valid||staged_plan_valid);",
            "compact ROM loader must activate a staged plan per download",
        ),
        (
            "assignraw_write_complete=!plan_active?1'b0:",
            "compact ROM loader must stall the first word until plan arrival",
        ),
        (
            "assignsdram_req=!plan_active?1'b0:",
            "compact ROM loader must not write SDRAM before plan arrival",
        ),
        (
            "if(raw_write_data[11:8]!=4'd0)",
            "compact footer must validate the reserved low nibble of byte 5",
        ),
        (
            "if(fill_active&&(fill_due||!raw_write_en))beginstate<=STATE_FILL;end"
            "elseif(raw_write_en)beginstate<=STATE_RAW;",
            "compact loader must interleave a due prefix word before the next raw word",
        ),
        (
            "if(sdram_ready)beginfill_due<=fill_active;state<=STATE_GAP;end",
            "each accepted compact raw word must schedule prefix progress",
        ),
        (
            "plan_non_power_of_two&&(fill_active||!load_end_seen||!validation_passed)",
            "compact reset hold must not glitch before falling-edge validation",
        ),
    )
    for expression, error in compact_rom_requirements:
        if expression not in rom_loader_compact:
            errors.append(error)
    if "raw_write_data[15:12]!=4'd0" in rom_loader_compact:
        errors.append("compact footer must not reject legal upper maintenance flags")
    if (
        "if(cart_download_sys_external)begin"
        "colorcart_downloaded<=colorcart_download_sys;end"
        not in wonderswan_compact
    ):
        errors.append("Color model must latch only during the external LOADF window")

    validation_status_requirements = (
        (
            core_top_compact,
            "32'h00000014:beginbridge_rd_data<=rom_validation_status_74a;end",
            "Chip32 must receive compact-ROM validation at PMP 0x14",
        ),
        (
            core_top_compact,
            "rom_validation_state_74a[1]?32'd2:"
            "rom_validation_state_74a[0]?32'd1:32'd0",
            "compact-ROM validation status must encode pending/ready/fail",
        ),
        (
            core_top_compact,
            "synch_3#(.WIDTH(2))rom_validation_to_bridge("
            "{rom_validation_failed_mem,rom_image_ready_mem},"
            "rom_validation_state_74a,clk_74a);",
            "compact-ROM terminal status must cross atomically to the PMP domain",
        ),
        (
            wonderswan_compact,
            ".image_ready(rom_image_ready_mem),"
            ".validation_failed(rom_validation_failed_mem)",
            "compact-ROM terminal status must leave the memory domain",
        ),
        (
            chip32_compact,
            "constantrom_validation_status_addr=0x14",
            "Chip32 validation status address must match the RTL",
        ),
        (
            chip32_compact,
            "constantrom_validation_timeout=0x00100000",
            "Chip32 timeout must use the reviewed instruction guard",
        ),
        (
            chip32_compact,
            "rom_validation_poll:pmprr1,r2cmpr2,#1jpz,rom_validation_ready"
            "cmpr2,#2jpz,rom_validation_rejected",
            "Chip32 must distinguish ready from rejected compact ROMs",
        ),
        (
            chip32_compact,
            "ldr4,#rom_validation_timeoutrom_validation_poll:",
            "Chip32 compact-ROM polling must start a bounded timeout",
        ),
        (
            chip32_compact,
            "subr4,#1jpnz,rom_validation_poll"
            "ldr14,#rom_validation_timeout_msgjpprint_error_and_exit",
            "Chip32 compact-ROM timeout must fail closed with a visible error",
        ),
    )
    for source, expression, error in validation_status_requirements:
        if expression not in source:
            errors.append(error)

    project_lines = {
        "core/apf_dataslot_guard.sv": "Quartus must compile the data-slot guard",
        "core/apf_rom_loader_adapter.sv": "Quartus must compile the compact-ROM loader",
        "core/apf_rom_plan_cdc.sv": "Quartus must compile the ROM-plan CDC",
        "core/apf_save_metadata_cdc.sv": "Quartus must compile the metadata CDC",
        "core/apf_startup_sequencer.sv": "Quartus must compile the startup sequencer",
    }
    for filename, error in project_lines.items():
        line = f"set_global_assignment -name SYSTEMVERILOG_FILE {filename}"
        if sources["qsf"].count(line) != 1:
            errors.append(error)

    runner_lines = {
        "run_apf_dataslot_guard_tb.sh": "regression must run the data-slot guard bench",
        "run_apf_rom_loader_adapter_tb.sh": "regression must run the compact-ROM loader bench",
        "run_apf_rom_plan_cdc_tb.sh": "regression must run the ROM-plan CDC bench",
        "run_apf_save_metadata_cdc_tb.sh": "regression must run the metadata CDC bench",
        "run_apf_startup_sequencer_tb.sh": "regression must run the startup sequencer bench",
    }
    for filename, error in runner_lines.items():
        line = f'"$ROOT/sim/rtl/{filename}"'
        if sources["regression"].count(line) != 1:
            errors.append(error)

    synchronizer_contract_line = (
        'python3 "$ROOT/scripts/pocket_synchronizer_attribute_contract_test.py"'
    )
    if sources["regression"].count(synchronizer_contract_line) != 1:
        errors.append("regression must run the synchronizer attribute contract")

    return errors


class PocketFirstClassContractTest(unittest.TestCase):
    def test_core_platform_and_framework_identity(self) -> None:
        core = load("core.json")["core"]
        self.assertEqual(core["magic"], "APF_VER_1")
        self.assertEqual(core["metadata"]["platform_ids"], ["wonderswan"])
        self.assertEqual(core["metadata"]["author"], "RegionallyFamous")
        self.assertEqual(core["metadata"]["shortname"], "SwanSong")
        self.assertEqual(
            core["metadata"]["url"],
            "https://github.com/RegionallyFamous/swan-song",
        )
        self.assertEqual(
            core["metadata"]["description"],
            "Swan Song for WonderSwan and WonderSwan Color",
        )

        # Framework 2.3 fixes Reset to Defaults for the persisted file-browser
        # history used by the cartridge and BIOS data slots.
        self.assertEqual(core["framework"]["version_required"], "2.3")
        # Memories/sleep remains disabled until the full controller and a
        # physical Pocket endurance matrix have passed.
        self.assertFalse(core["framework"]["sleep_supported"])
        self.assertTrue(core["framework"]["dock"]["supported"])
        self.assertEqual(core["framework"]["hardware"]["cartridge_adapter"], -1)

        platform = json.loads(
            (ROOT / "dist/Platforms/wonderswan.json").read_text(encoding="utf-8")
        )["platform"]
        self.assertEqual(
            platform,
            {
                "category": "Handheld",
                "name": "WonderSwan",
                "year": 1999,
                "manufacturer": "Bandai",
            },
        )

    def test_platform_detail_info_matches_the_shipped_contract(self) -> None:
        info_bytes = (CORE_DIR / "info.txt").read_bytes()
        info = info_bytes.decode("ascii")
        lines = info.splitlines()
        self.assertLessEqual(len(lines), 32)
        self.assertTrue(
            all(byte == 0x0A or 0x20 <= byte <= 0x7E for byte in info_bytes)
        )
        self.assertEqual(
            lines[:3],
            [
                "Swan Song by Regionally Famous",
                "System core by Robert Peip",
                "Pocket port by agg23",
            ],
        )

        core = load("core.json")["core"]
        data = load("data.json")["data"]
        slots = {number(slot["id"]): slot for slot in data["data_slots"]}
        cartridge = slots[0]
        self.assertEqual(cartridge["extensions"], ["ws", "wsc"])
        self.assertIn("* WonderSwan .ws and WonderSwan Color .wsc", lines)

        bw_bios = slots[9]
        color_bios = slots[10]
        self.assertTrue(bw_bios["required"])
        self.assertTrue(color_bios["required"])
        self.assertIn(
            "* User-supplied "
            f"{bw_bios['size_exact'] // 1024} KiB {bw_bios['filename']} and "
            f"{color_bios['size_exact'] // 1024} KiB {color_bios['filename']}",
            lines,
        )
        self.assertIn(
            "* Pocket firmware "
            f"{core['framework']['version_required']} minimum; 2.6.0 recommended",
            lines,
        )

        self.assertIn(
            "* Last-game reuse is configured; Pocket verification pending", lines
        )
        self.assertNotIn("Last cartridge is remembered", info)
        self.assertNotIn("Tear-safe", info)
        self.assertNotIn("source-pinned", info)
        self.assertNotIn("Analogue OS", info)

        variables = {
            number(variable["id"]): variable
            for variable in load("interact.json")["interact"]["variables"]
        }
        self.assertEqual(variables[41]["name"], "Triple Buffer")
        self.assertEqual(variables[42]["name"], "LCD Response")
        self.assertIn(
            "* Triple-buffered video and optional LCD response effects", lines
        )
        self.assertEqual(variables[45]["name"], "Color Profile")
        self.assertEqual(
            [option["name"] for option in variables[45]["options"]],
            ["Raw RGB444", "Color LCD (ares)"],
        )
        self.assertIn(
            "* Raw RGB444 and optional Color LCD (ares) profile", lines
        )

        self.assertFalse(core["framework"]["sleep_supported"])
        self.assertFalse(core["framework"]["hardware"]["link_port"])
        self.assertEqual(core["framework"]["hardware"]["cartridge_adapter"], -1)
        self.assertIn("The physical cartridge and link ports are not used.", lines)
        self.assertIn(
            "Memories and Sleep + Wake remain disabled pending end-to-end Pocket validation.",
            lines,
        )
        self.assertNotIn(
            "pc2",
            {
                extension.lower()
                for slot in data["data_slots"]
                for extension in slot.get("extensions", [])
            },
        )
        self.assertIn(
            "PocketChallenge v2 and .pc2 assets are not supported.", lines
        )

    def test_video_modes_are_generic_and_backed_by_grayscale_rtl(self) -> None:
        video = load("video.json")["video"]
        self.assertEqual(video["magic"], "APF_VER_1")
        self.assertLessEqual(len(video["scaler_modes"]), 8)
        self.assertEqual(len(video["scaler_modes"]), 3)
        self.assertEqual(
            [number(mode["rotation"]) for mode in video["scaler_modes"]],
            [0, 270, 180],
        )
        self.assertEqual(
            [number(mode["id"]) for mode in video["display_modes"]],
            [0x20, 0x30, 0x40],
        )
        self.assertLessEqual(len(video["display_modes"]), 16)
        self.assertEqual(video["defaults"]["sharpness"], 3)

        bridge = (ROOT / "src/fpga/core/core_bridge_cmd.v").read_text(
            encoding="utf-8"
        )
        top = (ROOT / "src/fpga/core/core_top.v").read_text(encoding="utf-8")
        video_bus = (ROOT / "src/fpga/core/apf_video_bus.sv").read_text(
            encoding="utf-8"
        )
        project = (ROOT / "src/fpga/ap_core.qsf").read_text(encoding="utf-8")
        self.assertIn("16'h00B1", bridge)
        self.assertIn("16'h00B2", bridge)
        self.assertIn("16'h00B8", bridge)
        self.assertIn("32'h0000_444D", bridge)
        self.assertIn("displaymode_grayscale_ack", bridge)
        self.assertIn("displaymode_grayscale_to_video", top)
        self.assertIn("displaymode_grayscale_to_bridge", top)
        self.assertIn("apf_video_bus video_bus", top)
        self.assertIn(
            "displaymode_grayscale_applied <= displaymode_grayscale_requested",
            video_bus,
        )
        self.assertIn("apf_grayscale_video displaymode_video", video_bus)
        self.assertIn("core/apf_grayscale_video.sv", project)
        self.assertIn("core/apf_video_bus.sv", project)
        self.assertEqual(
            project.count("set_global_assignment -name COMPRESSION_MODE ON"), 1
        )

    def test_dynamic_nonvolatile_save_contract(self) -> None:
        data = load("data.json")["data"]
        self.assertEqual(data["magic"], "APF_VER_1")
        slots = data["data_slots"]
        self.assertLessEqual(len(slots), 32)
        self.assertEqual(len({number(slot["id"]) for slot in slots}), len(slots))
        for slot in slots:
            self.assertLessEqual(len(slot["name"]), 15)
            self.assertLessEqual(len(slot.get("extensions", [])), 4)
            self.assertTrue(all(len(ext) <= 7 for ext in slot.get("extensions", [])))

        cartridge = next(slot for slot in slots if number(slot["id"]) == 0)
        cartridge_parameters = number(cartridge["parameters"])
        self.assertTrue(cartridge["required"])
        self.assertEqual(cartridge_parameters, 0x309)
        self.assertEqual(cartridge_parameters & (1 << 0), 1 << 0)  # user browsable
        self.assertEqual(cartridge_parameters & (1 << 3), 1 << 3)  # read-only
        self.assertEqual(cartridge_parameters & (1 << 8), 1 << 8)  # full reload
        self.assertEqual(cartridge_parameters & (1 << 9), 1 << 9)  # persist choice

        save = next(slot for slot in slots if number(slot["id"]) == 11)
        parameters = number(save["parameters"])
        self.assertTrue(save["nonvolatile"])
        self.assertEqual(parameters & (1 << 1), 1 << 1)  # core-specific
        self.assertEqual(parameters & (1 << 2), 1 << 2)  # clone slot-0 filename
        self.assertEqual(parameters & (1 << 3), 0)  # writable
        self.assertEqual(parameters & (1 << 7), 1 << 7)  # safe full restart
        self.assertEqual(number(save["address"]), 0x20000000)
        self.assertNotIn("size_exact", save)
        self.assertEqual(number(save["size_maximum"]), 512 * 1024 + 12)

        console_eeprom_contract = {
            number(slot["id"]): (
                slot["required"],
                slot["filename"],
                number(slot["parameters"]),
                slot["nonvolatile"],
                number(slot["size_exact"]),
                number(slot["size_maximum"]),
                number(slot["address"]),
            )
            for slot in slots
            if number(slot["id"]) in (12, 13)
        }
        self.assertEqual(
            console_eeprom_contract,
            {
                12: (False, "mono.eeprom", 0x02, True, 128, 128, 0x50000000),
                13: (False, "color.eeprom", 0x02, True, 2048, 2048, 0x60000000),
            },
        )
        for parameters in (console_eeprom_contract[12][2], console_eeprom_contract[13][2]):
            self.assertEqual(parameters & (1 << 1), 1 << 1)  # core-specific
            self.assertEqual(parameters & (1 << 2), 0)  # never clone cartridge name
            self.assertEqual(parameters & (1 << 3), 0)  # writable on shutdown
            self.assertEqual(parameters & (1 << 5), 0)  # retain factory seed if absent

        # Both boot ROMs are dependencies of the current Chip32 launch path.
        # Advertise that requirement to APF and reject malformed firmware at
        # the host definition before the guarded bridge transfer begins.
        bios_contract = {
            number(slot["id"]): (
                slot["required"],
                slot["filename"],
                number(slot["parameters"]),
                number(slot["size_exact"]),
                number(slot["address"]),
            )
            for slot in slots
            if number(slot["id"]) in (9, 10)
        }
        self.assertEqual(
            bios_contract,
            {
                9: (True, "bw.rom", 0x208, 4096, 0x30000000),
                10: (True, "color.rom", 0x208, 8192, 0x30000000),
            },
        )

    def test_input_and_interact_limits(self) -> None:
        input_definition = load("input.json")["input"]
        self.assertEqual(input_definition["magic"], "APF_VER_1")
        controllers = input_definition["controllers"]
        self.assertEqual(len(controllers), 1)
        self.assertEqual(controllers[0]["type"], "default")
        mappings = controllers[0]["mappings"]
        self.assertEqual(
            [(number(item["id"]), item["name"], item["key"]) for item in mappings],
            [
                (0, "Horz A/Vert X3", "pad_btn_a"),
                (1, "Horz B/Vert X4", "pad_btn_b"),
                (2, "Horz Y3/Vert X2", "pad_btn_x"),
                (3, "Horz Y4/Vert X1", "pad_btn_y"),
                (10, "Horz Y1/Vert A", "pad_trig_l"),
                (11, "Horz Y2/Vert B", "pad_trig_r"),
                (20, "Start", "pad_btn_start"),
                (30, "Fast Forward", "pad_btn_select"),
            ],
        )
        self.assertTrue(all(len(item["name"]) <= 19 for item in mappings))

        # Bind those user-facing labels to both halves of the production
        # vertical mapping: controls-only mapper and joypad.vhd's native rotation.
        swan = compact_hdl(
            (ROOT / "src/fpga/core/wonderswan.sv").read_text(encoding="utf-8")
        )
        control_layout = compact_hdl(
            (ROOT / "src/fpga/core/apf_control_layout.sv").read_text(
                encoding="utf-8"
            )
        )
        joypad = compact_hdl(
            (ROOT / "src/fpga/core/rtl/joypad.vhd").read_text(encoding="utf-8")
        ).lower()
        for expression in (
            ".keyy1(control_key_y1)",
            ".keyy2(control_key_y2)",
            ".keyy3(control_key_y3)",
            ".keyy4(control_key_y4)",
            ".keyx1(dpad_up)",
            ".keyx2(dpad_right)",
            ".keyx3(dpad_down)",
            ".keyx4(dpad_left)",
        ):
            self.assertIn(expression, swan.lower())
        for expression in (
            "assignkey_y1=controls_vertical?button_x:button_trig_l;",
            "assignkey_y2=controls_vertical?button_a:button_trig_r;",
            "assignkey_y3=controls_vertical?button_b:button_x;",
            "assignkey_y4=button_y;",
            "assignkey_a=controls_vertical?button_trig_l:button_a;",
            "assignkey_b=controls_vertical?button_trig_r:button_b;",
        ):
            self.assertIn(expression, control_layout.lower())
        for expression in (
            "if(keyy4='1')thenkeypad_read(0)<='1';endif;",
            "if(keyy1='1')thenkeypad_read(1)<='1';endif;",
            "if(keyy2='1')thenkeypad_read(2)<='1';endif;",
            "if(keyy3='1')thenkeypad_read(3)<='1';endif;",
        ):
            self.assertIn(expression, joypad)

        interact = load("interact.json")["interact"]
        variables = interact["variables"]
        self.assertLessEqual(len(variables), 16)
        self.assertEqual(len({number(item["id"]) for item in variables}), len(variables))
        variables_by_id = {number(item["id"]): item for item in variables}
        self.assertEqual(
            variables_by_id[40],
            {
                "name": "Video",
                "id": 40,
                "type": "action",
                "enabled": False,
                "address": "0x58",
                "value": 0,
            },
        )
        self.assertEqual(
            variables_by_id[80],
            {
                "name": "Sound",
                "id": 80,
                "type": "action",
                "enabled": False,
                "address": "0x5C",
                "value": 0,
            },
        )
        system_type = variables_by_id[10]
        self.assertEqual(number(system_type["address"]), 0x100)
        self.assertEqual(
            [(number(option["value"]), option["name"]) for option in system_type["options"]],
            [(0, "Auto"), (1, "WonderSwan"), (2, "WonderSwan Color")],
        )
        self.assertEqual(variables_by_id[43]["name"], "Display Orientation")
        self.assertEqual(number(variables_by_id[43]["address"]), 0x208)
        self.assertEqual(variables_by_id[44]["name"], "Landscape 180°")
        self.assertEqual(number(variables_by_id[44]["address"]), 0x20C)
        self.assertEqual(variables_by_id[42]["name"], "LCD Response")
        self.assertEqual(
            [
                (number(option["value"]), option["name"])
                for option in variables_by_id[42]["options"]
            ],
            [(0, "Off"), (1, "2-Frame Blend"), (2, "Persistence")],
        )
        self.assertEqual(variables_by_id[45]["name"], "Color Profile")
        self.assertEqual(number(variables_by_id[45]["address"]), 0x210)
        self.assertEqual(
            [
                (number(option["value"]), option["name"])
                for option in variables_by_id[45]["options"]
            ],
            [(0, "Raw RGB444"), (1, "Color LCD (ares)")],
        )
        self.assertEqual(variables_by_id[46]["name"], "Control Layout")
        self.assertEqual(number(variables_by_id[46]["address"]), 0x214)
        self.assertEqual(
            [
                (number(option["value"]), option["name"])
                for option in variables_by_id[46]["options"]
            ],
            [(0, "Auto"), (1, "Horizontal"), (2, "Vertical")],
        )
        self.assertEqual(variables_by_id[81]["name"], "Audio in Fast Forward")
        self.assertEqual(number(variables_by_id[81]["address"]), 0x300)

    def test_apf_boundary_sources_are_mutation_locked(self) -> None:
        sources = source_bundle()
        self.assertEqual(first_class_source_errors(sources), [])

        mutations = (
            (
                "bridge",
                "[47:0]  dataslot_requestwrite_size",
                "[31:0]  dataslot_requestwrite_size",
                "48-bit 0082 declaration",
            ),
            (
                "bridge",
                "{host_20[31:16], host_24}",
                "{16'd0, host_24}",
                "48-bit 0082 assembly",
            ),
            (
                "bridge",
                "[1:0]   dataslot_requestread_result",
                "        dataslot_requestread_result",
                "read result code must be explicit 2-bit",
            ),
            (
                "bridge",
                "[1:0]   dataslot_requestwrite_result",
                "        dataslot_requestwrite_result",
                "write result code must be explicit 2-bit",
            ),
            (
                "bridge",
                "{14'd0, dataslot_requestwrite_result}",
                "{15'd0, dataslot_requestwrite_result[0]}",
                "zero-extend write result code",
            ),
            (
                "core_top",
                "wire [47:0] dataslot_requestwrite_size;",
                "wire [31:0] dataslot_requestwrite_size;",
                "full 48-bit 0082 size",
            ),
            (
                "core_top",
                "dataslot_requestread || dataslot_requestwrite",
                "dataslot_requestwrite",
                "both 0080 and 0082 requests",
            ),
            (
                "core_top",
                "dataslot_requestwrite_size : 48'd0;",
                "{16'd0, dataslot_requestwrite_size[31:0]} : 48'd0;",
                "full 0082 size into the guard",
            ),
            (
                "core_top",
                "dataslot_guard_ack && dataslot_requestread;",
                "1'b0;",
                "guard acknowledgement to 0080",
            ),
            (
                "core_top",
                "dataslot_guard_ack && dataslot_requestwrite;",
                "1'b0;",
                "guard acknowledgement to 0082",
            ),
            (
                "core_top",
                "assign dataslot_requestread_result = dataslot_guard_result;",
                "assign dataslot_requestread_result = 2'd0;",
                "full guard result to 0080",
            ),
            (
                "core_top",
                "assign dataslot_requestwrite_result = dataslot_guard_result;",
                "assign dataslot_requestwrite_result = 2'd0;",
                "full guard result to 0082",
            ),
            (
                "core_top",
                ".request_id(dataslot_request_id),",
                ".request_id(dataslot_requestwrite_id),",
                "complete host request through the data-slot guard",
            ),
            (
                "guard",
                "end else begin\n      case (state)",
                "end else if (!captured_length_clear) begin\n      case (state)",
                "capture clear must not block the request FSM",
            ),
            (
                "wonderswan",
                "save_metadata_commit <= cart_download_mem_previous && !cart_download;",
                "save_metadata_commit <= 1'b0;",
                "commit footer metadata at cartridge completion",
            ),
            (
                "core_top",
                ".save_metadata_commit(save_metadata_commit),",
                ".save_metadata_commit(),",
                "receive the WonderSwan footer commit",
            ),
            (
                "core_top",
                "save_metadata_commit_pending_mem &&\n"
                "                                     !save_metadata_cdc_busy;",
                "save_metadata_commit_pending_mem;",
                "wait until the metadata CDC is available",
            ),
            (
                "core_top",
                "save_size_bytes_snapshot_mem <= save_size_bytes;",
                "save_size_bytes_snapshot_mem <= 20'd0;",
                "snapshotted while its CDC commit is queued",
            ),
            (
                "core_top",
                "end else if (save_metadata_commit_source) begin\n"
                "      save_metadata_commit_pending_mem <= 1'b0;",
                "end else if (1'b0) begin\n"
                "      save_metadata_commit_pending_mem <= 1'b0;",
                "queue must retire only after starting its CDC transfer",
            ),
            (
                "core_top",
                ".save_size_bytes_source(save_size_bytes_snapshot_mem),",
                ".save_size_bytes_source(save_size_bytes),",
                "consume the queued footer snapshot",
            ),
            (
                "core_top",
                "save_metadata_publish_pending && dataslot_allcomplete",
                "save_metadata_publish_pending",
                "table publication must wait for 008F",
            ),
            (
                "core_top",
                ".load_complete(dataslot_allcomplete_mem),",
                ".load_complete(dataslot_allcomplete),",
                "receive synchronized 008F as load completion",
            ),
            (
                "wonderswan",
                ".load_complete(load_complete),",
                ".load_complete(reset_n),",
                "pass synchronized load completion to the save initializer",
            ),
            (
                "core_top",
                ".rtc_notification_observed(rtc_transfer_delivered),",
                ".rtc_notification_observed(rtc_valid),",
                "observe delivered RTC data",
            ),
            (
                "core_top",
                ".initializers_ready(save_initialization_resolved_74a),",
                ".initializers_ready(1'b1),",
                "wait for resolved save initialization",
            ),
            (
                "core_top",
                "assign status_setup_done = startup_complete;",
                "assign status_setup_done = startup_ready_to_run_pulse;",
                "persistent startup completion",
            ),
            (
                "core_top",
                ".ready_to_run_complete(ready_to_run_complete),",
                ".ready_to_run_complete(),",
                "acknowledgement of target 0140",
            ),
            (
                "core_top",
                "apf_save_metadata_cdc save_metadata_command_cdc (\n"
                "      .reset_n(pll_core_locked),",
                "apf_save_metadata_cdc save_metadata_command_cdc (\n"
                "      .reset_n(reset_n),",
                "metadata CDC reset must remain independent of host Reset Enter",
            ),
            (
                "core_top",
                "apf_dataslot_guard pocket_dataslot_guard (\n"
                "      .clk(clk_74a),\n"
                "      .reset_n(pll_core_ready_74a),",
                "apf_dataslot_guard pocket_dataslot_guard (\n"
                "      .clk(clk_74a),\n"
                "      .reset_n(reset_n),",
                "guard reset must remain independent of host Reset Enter",
            ),
            (
                "core_top",
                "!execution_ready_74a && save_backend_quiesced &&",
                "1'b1 &&",
                "0080 flush must wait for real execution stop and backend quiescence",
            ),
            (
                "core_top",
                ".pll_core_locked(pll_core_ready_mem),",
                ".pll_core_locked(reset_n),",
                "footer commit reset must remain independent of host Reset Enter",
            ),
            (
                "startup",
                "loaders_ready && initializers_ready;",
                "loaders_ready;",
                "startup gating must require 008F, 0090, loaders, and initializers",
            ),
            (
                "startup",
                "(rtc_seen || rtc_notification_observed)",
                "rtc_seen",
                "startup gating must require 008F, 0090, loaders, and initializers",
            ),
            (
                "startup",
                "ready_to_run_pulse <= 1'b1;",
                "ready_to_run_pulse <= 1'b0;",
                "exactly one Ready-to-Run source pulse",
            ),
            (
                "bridge",
                "if(ready_to_run_complete && reset_exit_ready) begin\n"
                "                reset_n <= 1;",
                "if(1'b1) begin\n                reset_n <= 1;",
                "Reset Exit must wait for startup and settings acknowledgement",
            ),
            (
                "core_top",
                "wire settings_reset_exit_ready_74a =\n"
                "      !settings_write_74a && !settings_update_pending_74a;",
                "wire settings_reset_exit_ready_74a = 1'b1;",
                "core_top must fence Reset Exit on the acknowledged settings CDC",
            ),
            (
                "core_top",
                "       (bridge_addr == 32'h00000214) ||\n",
                "",
                "same-cycle settings write guard must cover every interact register",
            ),
            (
                "settings",
                "assign update_pending_source = transfer_busy_source ||\n"
                "      settings_source != settings_hold_source;",
                "assign update_pending_source = transfer_busy_source;",
                "settings pending must cover in-flight and superseding payloads",
            ),
            (
                "regression",
                '"$ROOT/sim/rtl/run_apf_settings_boot_barrier_tb.sh"\n',
                "",
                "regression must run the asynchronous settings boot barrier test",
            ),
            (
                "bridge",
                "if(!status_setup_done) begin\n"
                "        // A new title drops startup_complete before it can rise again. Never\n"
                "        // let that lifecycle consume the previous title's 0140 acknowledgement.\n"
                "        ready_to_run_complete <= 0;\n"
                "    end",
                "if(1'b0) begin\n"
                "        ready_to_run_complete <= 0;\n"
                "    end",
                "target 0140 acknowledgement must not cross title lifecycles",
            ),
            (
                "metadata",
                "reg [20:0] metadata_hold;",
                "reg [19:0] metadata_hold;",
                "bundled 21-bit snapshot",
            ),
            (
                "metadata",
                "assign busy_source = request_toggle != acknowledge_sync;",
                "assign busy_source = request_toggle == acknowledge_sync;",
                "busy must span request through acknowledgement",
            ),
            (
                "metadata",
                "metadata_hold <= {has_rtc_source, save_size_bytes_source};",
                "metadata_hold <= {1'b0, save_size_bytes_source};",
                "capture size and RTC atomically",
            ),
            (
                "metadata",
                "{has_rtc_74a, save_size_bytes_74a} <= metadata_hold;",
                "{has_rtc_74a, save_size_bytes_74a} <= 21'd0;",
                "publish size and RTC atomically",
            ),
            (
                "metadata",
                "if (commit_source && !commit_previous) begin",
                "if (commit_source) begin",
                "accept only a fresh commit edge while idle",
            ),
            (
                "qsf",
                "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_save_metadata_cdc.sv",
                "# metadata CDC omitted",
                "Quartus must compile the metadata CDC",
            ),
            (
                "guard",
                "[47:0] request_size",
                "[31:0] request_size",
                "guard must preserve the 48-bit request size",
            ),
            (
                "guard",
                "[ 1:0] request_result",
                "       request_result",
                "guard result must be explicit 2-bit",
            ),
            (
                "guard",
                "localparam [1:0] RESULT_CHECK_LATER = 2'd2;",
                "localparam [1:0] RESULT_CHECK_LATER = 2'd0;",
                "result 2 must mean check later",
            ),
            (
                "guard",
                "else if (!selected_loader_ready) begin",
                "else if (1'b0) begin",
                "retry while the selected loader is unavailable",
            ),
            (
                "guard",
                "captured_save_length <= latched_size;",
                "captured_save_length <= 48'd0;",
                "retain the offered 48-bit save length",
            ),
            (
                "qsf",
                "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_dataslot_guard.sv",
                "# data-slot guard omitted",
                "Quartus must compile the data-slot guard",
            ),
            (
                "save_init",
                "input  wire        load_complete,",
                "input  wire        load_complete_missing,",
                "pre-Ready-to-Run load_complete",
            ),
            (
                "save_init",
                "if (load_complete && init_pending) begin",
                "if (reset_n && init_pending) begin",
                "start only from load_complete",
            ),
            (
                "save_init",
                "initialization_resolved <= 1'b0;",
                "initialization_resolved <= 1'b1;",
                "cart download must clear save initialization resolution once",
            ),
            (
                "save_init",
                "initialization_resolved <= 1'b1;",
                "initialization_resolved <= 1'b0;",
                "loaded, SRAM, and EEPROM completion must each resolve",
            ),
            (
                "save_init",
                "wire [19:0] save_word_count = save_size_bytes >> 1;",
                "wire [19:0] save_word_count = save_size_bytes;",
                "clear the exact selected word capacity",
            ),
            (
                "qsf",
                "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_startup_sequencer.sv",
                "# startup sequencer omitted",
                "Quartus must compile the startup sequencer",
            ),
            (
                "regression",
                '"$ROOT/sim/rtl/run_apf_dataslot_guard_tb.sh"',
                "# data-slot guard runner omitted",
                "regression must run the data-slot guard bench",
            ),
            (
                "regression",
                '"$ROOT/sim/rtl/run_apf_save_metadata_cdc_tb.sh"',
                "# metadata CDC runner omitted",
                "regression must run the metadata CDC bench",
            ),
            (
                "regression",
                '"$ROOT/sim/rtl/run_apf_startup_sequencer_tb.sh"',
                "# startup sequencer runner omitted",
                "regression must run the startup sequencer bench",
            ),
            (
                "regression",
                'python3 "$ROOT/scripts/'
                'pocket_synchronizer_attribute_contract_test.py"',
                "# synchronizer attribute contract omitted",
                "regression must run the synchronizer attribute contract",
            ),
            (
                "rom_loader",
                "if (fill_active && (fill_due || !raw_write_en)) begin",
                "if (fill_active && !raw_write_en) begin",
                "interleave a due prefix word",
            ),
            (
                "rom_loader",
                "fill_due <= fill_active;",
                "fill_due <= 1'b0;",
                "schedule prefix progress",
            ),
            (
                "rom_loader",
                "fill_active || !load_end_seen ||\n                          !validation_passed",
                "fill_active ||\n                          (load_end_seen && !validation_passed)",
                "must not glitch before falling-edge validation",
            ),
            (
                "core_top",
                "32'h00000014: begin\n        bridge_rd_data <= rom_validation_status_74a;",
                "32'h00000018: begin\n        bridge_rd_data <= rom_validation_status_74a;",
                "validation at PMP 0x14",
            ),
            (
                "wonderswan",
                ".image_ready(rom_image_ready_mem),",
                ".image_ready(),",
                "terminal status must leave the memory domain",
            ),
            (
                "chip32",
                "pmpr r1,r2",
                "ld r2,#0",
                "distinguish ready from rejected",
            ),
            (
                "chip32",
                "cmp r2,#2",
                "cmp r2,#3",
                "distinguish ready from rejected",
            ),
            (
                "chip32",
                "sub r4,#1",
                "sub r4,#0",
                "timeout must fail closed",
            ),
            (
                "chip32",
                "constant rom_validation_timeout = 0x00100000",
                "constant rom_validation_timeout = 0x02000000",
                "reviewed instruction guard",
            ),
            (
                "core_top",
                ".WIDTH(2)\n  ) rom_validation_to_bridge",
                ".WIDTH(1)\n  ) rom_validation_to_bridge",
                "terminal status must cross atomically",
            ),
        )

        for index, (name, old, new, expected_error) in enumerate(mutations):
            with self.subTest(mutation=index, source=name):
                self.assertIn(old, sources[name])
                mutated = dict(sources)
                mutated[name] = mutated[name].replace(old, new, 1)
                errors = first_class_source_errors(mutated)
                self.assertTrue(
                    any(expected_error in error for error in errors),
                    f"mutation unexpectedly survived: {expected_error}; errors={errors}",
                )

    def test_focused_wrapper_tests_are_executable(self) -> None:
        for relative in (
            "scripts/pocket_control_cdc_contract_test.py",
            "scripts/pocket_synchronizer_attribute_contract_test.py",
            "sim/rtl/run_apf_host_notify_tb.sh",
            "sim/rtl/run_apf_grayscale_video_tb.sh",
            "sim/rtl/run_apf_dataslot_guard_tb.sh",
            "sim/rtl/run_apf_save_metadata_cdc_tb.sh",
            "sim/rtl/run_apf_startup_sequencer_tb.sh",
        ):
            path = ROOT / relative
            self.assertTrue(path.is_file())
            self.assertTrue(os.access(path, os.X_OK))


if __name__ == "__main__":
    unittest.main()
