#!/usr/bin/env python3
"""Source-lock and Tcl-parse the atomic Pocket settings CDC constraint."""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SDC = ROOT / "src/fpga/core/core_constraints.sdc"
CORE_TOP = ROOT / "src/fpga/core/core_top.v"
CDC = ROOT / "src/fpga/core/apf_settings_cdc.sv"


def require(pattern: str, source: str, message: str) -> None:
    if re.search(pattern, source, re.MULTILINE | re.DOTALL) is None:
        raise AssertionError(message)


def main() -> None:
    sdc = SDC.read_text(encoding="utf-8")
    core_top = CORE_TOP.read_text(encoding="utf-8")
    cdc = CDC.read_text(encoding="utf-8")

    require(
        r"apf_settings_cdc\s*#\s*\([^;]*\)\s*settings_command_cdc\s*\(",
        core_top,
        "missing constrained settings CDC instance",
    )
    require(
        r"\.reset_n\s*\(\s*pll_core_ready_74a\s*\)",
        core_top,
        "settings CDC reset is not independent of host Reset Enter",
    )
    if re.search(
        r"settings_command_cdc\s*\([^;]*\.reset_n\s*\(\s*reset_n\s*\)",
        core_top,
        re.MULTILINE | re.DOTALL,
    ):
        raise AssertionError("settings CDC incorrectly uses host reset_n")

    require(
        r"parameter\s*\[12:0\]\s+DEFAULT_SETTINGS\s*=\s*13'h0201",
        cdc,
        "settings CDC defaults do not match interact.json",
    )
    require(
        r"reg\s*\[12:0\]\s+settings_hold_source\s*;",
        cdc,
        "settings payload is not thirteen bits",
    )
    require(
        r"SYNCHRONIZER_IDENTIFICATION\s+FORCED[^\n]*"
        r"reg\s+request_meta_destination\s*;.*"
        r"SYNCHRONIZER_IDENTIFICATION\s+FORCED[^\n]*"
        r"reg\s+request_sync_destination\s*;",
        cdc,
        "request toggle lacks the expected Quartus-identified two-flop synchronizer",
    )
    if "ASYNC_REG" in cdc:
        raise AssertionError("settings CDC uses an unsupported Quartus attribute")
    require(
        r"ic\|settings_command_cdc\|settings_hold_source\[\*\]",
        sdc,
        "constraint does not select the exact settings source payload",
    )
    require(
        r"ic\|settings_command_cdc\|settings_destination\[\*\]",
        sdc,
        "constraint does not select the exact settings destination payload",
    )
    if len(re.findall(r"settings CDC constraint expected 13 .* registers", sdc)) != 2:
        raise AssertionError(
            "constraint does not fail closed on both thirteen-bit collections"
        )
    require(
        r"set_net_delay\s+-max\s+.*"
        r"-get_value_from_clock_period\s+dst_clock_period\s+.*"
        r"-from\s+\$settings_source_registers\s+.*"
        r"-to\s+\$settings_destination_registers",
        sdc,
        "settings payload delay is not bounded to one destination period",
    )
    require(
        r"set_max_skew\s+.*"
        r"-get_skew_value_from_clock_period\s+min_clock_period\s+.*"
        r"-from\s+\$settings_source_registers\s+.*"
        r"-to\s+\$settings_destination_registers",
        sdc,
        "settings payload skew is not bounded to the smaller clock period",
    )
    if re.search(
        r"set_false_path[^\n]*(?:settings_command_cdc|settings_hold_source)",
        sdc,
        re.IGNORECASE,
    ):
        raise AssertionError("settings payload was blanket-false-pathed")

    # Source the complete real SDC with collection-aware TimeQuest stubs. The
    # other constrained CDCs must also resolve because fail-closed guards run
    # while the file is sourced.
    harness = f"""
proc get_clocks {{args}} {{ return [list sdram_pll_clock] }}
proc get_ports {{args}} {{
  set filter [lindex $args end]
  set result {{}}
  if {{[string first "dram_clk" $filter] >= 0}} {{
    return [list dram_clk]
  }} elseif {{[string first "dram_a" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 37}} {{incr i}} {{ lappend result "sdram_write_$i" }}
  }} elseif {{[string first "dram_dq" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 16}} {{incr i}} {{ lappend result "sdram_read_$i" }}
  }} elseif {{[string first "bridge_spiss" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 4}} {{incr i}} {{ lappend result "apf_input_$i" }}
  }} elseif {{[string first "bridge_1wire" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 3}} {{incr i}} {{ lappend result "apf_bridge_output_$i" }}
  }} elseif {{[string first "scal_auddac" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 20}} {{incr i}} {{ lappend result "apf_scaler_output_$i" }}
  }}
  return $result
}}
proc create_generated_clock {{args}} {{}}
proc set_output_delay {{args}} {{}}
proc set_input_delay {{args}} {{}}
proc set_false_path {{args}} {{}}
proc set_clock_groups {{args}} {{}}
proc derive_clock_uncertainty {{}} {{}}
proc get_registers {{args}} {{
  set filter [lindex $args end]
  set result {{}}
  if {{[string first "settings_hold_source" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 13}} {{incr i}} {{ lappend result "settings_source_$i" }}
  }} elseif {{[string first "settings_destination" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 13}} {{incr i}} {{ lappend result "settings_destination_$i" }}
  }} elseif {{[string first "slot_hold_sys" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 2}} {{incr i}} {{ lappend result "scaler_source_$i" }}
  }} elseif {{[string first "pending_slot_video" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 2}} {{incr i}} {{ lappend result "scaler_destination_$i" }}
  }} elseif {{[string first "input_state_system_cdc|payload_hold_source" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 17}} {{incr i}} {{ lappend result "input_state_source_$i" }}
  }} elseif {{[string first "input_state_system_cdc|payload_destination" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 13}} {{incr i}} {{ lappend result "input_state_destination_$i" }}
  }} elseif {{[string first "metadata_hold" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 21}} {{incr i}} {{ lappend result "metadata_source_$i" }}
  }} elseif {{[string first "save_size_bytes_74a" $filter] >= 0 &&
              [string first "has_rtc_74a" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 21}} {{incr i}} {{ lappend result "metadata_destination_$i" }}
  }}
  return $result
}}
proc get_fanouts {{args}} {{
  set result {{}}
  for {{set i 0}} {{$i < 16}} {{incr i}} {{ lappend result "sdram_capture_$i" }}
  return $result
}}
proc get_collection_size {{collection}} {{ return [llength $collection] }}
proc foreach_in_collection {{variable collection body}} {{
  upvar 1 $variable item
  foreach item $collection {{ uplevel 1 $body }}
}}
proc get_object_info {{args}} {{ return [lindex $args end] }}
proc set_multicycle_path {{args}} {{}}
set ::net_delay_calls 0
set ::max_skew_calls 0
proc set_net_delay {{args}} {{ incr ::net_delay_calls }}
proc set_max_skew {{args}} {{ incr ::max_skew_calls }}
source {{{SDC}}}
if {{$::net_delay_calls != 4}} {{ error "expected four bundled-data delay constraints" }}
if {{$::max_skew_calls != 4}} {{ error "expected four bundled-data skew constraints" }}
puts "PASS Tcl source"
"""
    with tempfile.TemporaryDirectory(prefix="settings-sdc-test-") as temporary:
        harness_path = pathlib.Path(temporary) / "source_test.tcl"
        harness_path.write_text(harness, encoding="utf-8")
        completed = subprocess.run(
            ["tclsh", str(harness_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    if completed.returncode != 0:
        raise AssertionError(
            f"settings SDC Tcl source failed:\n{completed.stdout}{completed.stderr}"
        )
    if "PASS Tcl source" not in completed.stdout:
        raise AssertionError("settings SDC Tcl source did not reach its PASS marker")

    print(
        "PASS settings CDC constraint endpoints=13 delay=dst-period "
        "skew=min-period pll-reset no-payload-false-path"
    )


if __name__ == "__main__":
    main()
