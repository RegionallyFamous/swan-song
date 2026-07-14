#!/usr/bin/env python3
"""Source-lock and Tcl-parse the bundled save-metadata CDC constraint."""

from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SDC = ROOT / "src/fpga/core/core_constraints.sdc"
CORE_TOP = ROOT / "src/fpga/core/core_top.v"
CDC = ROOT / "src/fpga/core/apf_save_metadata_cdc.sv"


def require(pattern: str, source: str, message: str) -> None:
    if re.search(pattern, source, re.MULTILINE | re.DOTALL) is None:
        raise AssertionError(message)


def main() -> None:
    sdc = SDC.read_text(encoding="utf-8")
    core_top = CORE_TOP.read_text(encoding="utf-8")
    cdc = CDC.read_text(encoding="utf-8")

    require(
        r"apf_save_metadata_cdc\s+save_metadata_command_cdc\s*\(",
        core_top,
        "missing constrained save metadata CDC instance",
    )
    require(r"reg\s*\[20:0\]\s+metadata_hold\s*;", cdc, "payload is not 21 bits")
    require(
        r"\(\*\s*preserve\s*\*\)\s*reg\s*\[20:0\]\s+metadata_hold\s*;",
        cdc,
        "source payload registers are not preserved for exact constraints",
    )
    require(
        r"\(\*\s*preserve\s*\*\)\s*output\s+reg\s*\[19:0\]\s+"
        r"save_size_bytes_74a\s*,.*"
        r"\(\*\s*preserve\s*\*\)\s*output\s+reg\s+has_rtc_74a\s*,",
        cdc,
        "destination payload registers are not preserved for exact constraints",
    )
    native_synchronizer = (
        r'\(\*\s*altera_attribute\s*=\s*"-name\s+'
        r'SYNCHRONIZER_IDENTIFICATION\s+FORCED;\s*'
        r'-name\s+PRESERVE_REGISTER\s+ON"\s*\*\)'
    )
    if len(re.findall(native_synchronizer, cdc)) != 6:
        raise AssertionError("metadata CDC does not mark all six synchronizer declarations")
    if "ASYNC_REG" in cdc:
        raise AssertionError("metadata CDC retains a non-Intel ASYNC_REG declaration")
    for declaration in (
        r"reg\s*\[1:0\]\s+source_reset_sync\s*=\s*2'b00\s*;",
        r"reg\s*\[1:0\]\s+destination_reset_sync\s*=\s*2'b00\s*;",
        r"reg\s+acknowledge_meta\s*;",
        r"reg\s+acknowledge_sync\s*;",
        r"reg\s+request_meta\s*;",
        r"reg\s+request_sync\s*;",
    ):
        require(
            native_synchronizer + r"\s*" + declaration,
            cdc,
            f"metadata synchronizer lacks Intel-native preservation: {declaration}",
        )
    require(
        native_synchronizer + r"\s*reg\s+request_meta\s*;.*"
        + native_synchronizer
        + r"\s*reg\s+request_sync\s*;",
        cdc,
        "request toggle does not have the expected preserved two-flop synchronizer",
    )
    require(
        r"ic\|save_metadata_command_cdc\|metadata_hold\[\*\]",
        sdc,
        "constraint does not select the exact source payload",
    )
    require(
        r"ic\|save_metadata_command_cdc\|save_size_bytes_74a\[\*\].*"
        r"ic\|save_metadata_command_cdc\|has_rtc_74a",
        sdc,
        "constraint does not select all exact destination capture registers",
    )
    if len(re.findall(r"expected 21 .* registers", sdc)) != 2:
        raise AssertionError("constraint does not fail closed on both 21-bit collections")
    require(
        r"set_net_delay\s+-max\s+.*"
        r"-get_value_from_clock_period\s+dst_clock_period\s+.*"
        r"-value_multiplier\s+1\.0\s+.*"
        r"-from\s+\$save_metadata_source_registers_expanded\s+.*"
        r"-to\s+\$save_metadata_destination_registers_expanded",
        sdc,
        "payload net delay is not bounded to one destination period",
    )
    require(
        r"set_max_skew\s+.*"
        r"-get_skew_value_from_clock_period\s+min_clock_period\s+.*"
        r"-skew_value_multiplier\s+1\.0\s+.*"
        r"-from\s+\$save_metadata_source_registers_expanded\s+.*"
        r"-to\s+\$save_metadata_destination_registers_expanded",
        sdc,
        "payload bus skew is not bounded to the smaller clock period",
    )
    if re.search(
        r"set_false_path[^\n]*(?:save_metadata|metadata_hold)", sdc, re.IGNORECASE
    ):
        raise AssertionError("payload was blanket-false-pathed")

    # Source the real SDC through Tcl command stubs. This catches quoting,
    # continuation, brace, collection-variable, and argument-shape errors even
    # on hosts without Quartus/TimeQuest installed.
    def source_harness(
        metadata_source_count: int, metadata_destination_count: int
    ) -> subprocess.CompletedProcess[str]:
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
  set no_duplicates [expr {{[lsearch -exact $args "-no_duplicates"] >= 0}}]
  set result {{}}
  if {{[string first "slot_hold_sys" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 2}} {{incr i}} {{ lappend result "scaler_source_$i" }}
  }} elseif {{[string first "pending_slot_video" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 2}} {{incr i}} {{ lappend result "scaler_destination_$i" }}
  }} elseif {{[string first "settings_hold_source" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 13}} {{incr i}} {{ lappend result "settings_source_$i" }}
  }} elseif {{[string first "settings_destination" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 13}} {{incr i}} {{ lappend result "settings_destination_$i" }}
  }} elseif {{[string first "input_state_system_cdc|payload_hold_source" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 17}} {{incr i}} {{ lappend result "input_state_source_$i" }}
  }} elseif {{[string first "input_state_system_cdc|payload_destination" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 13}} {{incr i}} {{ lappend result "input_state_destination_$i" }}
  }} elseif {{[string first "metadata_hold" $filter] >= 0}} {{
    for {{set i 0}} {{$i < {metadata_source_count}}} {{incr i}} {{ lappend result "source_$i" }}
    if {{!$no_duplicates}} {{ lappend result "source_fitter_duplicate" }}
  }} elseif {{[string first "save_size_bytes_74a" $filter] >= 0 &&
              [string first "has_rtc_74a" $filter] >= 0}} {{
    for {{set i 0}} {{$i < {metadata_destination_count}}} {{incr i}} {{ lappend result "destination_$i" }}
    if {{!$no_duplicates}} {{ lappend result "destination_fitter_duplicate" }}
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
set ::net_delay_calls {{}}
set ::max_skew_calls {{}}
proc set_net_delay {{args}} {{ lappend ::net_delay_calls $args }}
proc set_max_skew {{args}} {{ lappend ::max_skew_calls $args }}
source {{{SDC}}}
if {{[llength $::net_delay_calls] != 4}} {{ error "expected four set_net_delay calls" }}
if {{[llength $::max_skew_calls] != 4}} {{ error "expected four set_max_skew calls" }}
set net_delay_args {{}}
foreach call $::net_delay_calls {{
  set from_index [lsearch -exact $call "-from"]
  if {{$from_index >= 0 &&
      [lsearch -exact [lindex $call [expr {{$from_index + 1}}]] "source_fitter_duplicate"] >= 0}} {{
    set net_delay_args $call
  }}
}}
set max_skew_args {{}}
foreach call $::max_skew_calls {{
  set from_index [lsearch -exact $call "-from"]
  if {{$from_index >= 0 &&
      [lsearch -exact [lindex $call [expr {{$from_index + 1}}]] "source_fitter_duplicate"] >= 0}} {{
    set max_skew_args $call
  }}
}}
if {{[llength $net_delay_args] == 0}} {{ error "save-metadata set_net_delay was not called" }}
if {{[llength $max_skew_args] == 0}} {{ error "save-metadata set_max_skew was not called" }}
set net_delay_from [lindex $net_delay_args [expr {{[lsearch -exact $net_delay_args "-from"] + 1}}]]
set net_delay_to [lindex $net_delay_args [expr {{[lsearch -exact $net_delay_args "-to"] + 1}}]]
set max_skew_from [lindex $max_skew_args [expr {{[lsearch -exact $max_skew_args "-from"] + 1}}]]
set max_skew_to [lindex $max_skew_args [expr {{[lsearch -exact $max_skew_args "-to"] + 1}}]]
foreach collection [list $net_delay_from $max_skew_from] {{
  if {{[lsearch -exact $collection "source_fitter_duplicate"] < 0}} {{
    error "source Fitter duplicate omitted from timing bound"
  }}
}}
foreach collection [list $net_delay_to $max_skew_to] {{
  if {{[lsearch -exact $collection "destination_fitter_duplicate"] < 0}} {{
    error "destination Fitter duplicate omitted from timing bound"
  }}
}}
puts "PASS Tcl source"
"""
        with tempfile.TemporaryDirectory(
            prefix="save-metadata-sdc-test-"
        ) as temporary:
            harness_path = pathlib.Path(temporary) / "source_test.tcl"
            harness_path.write_text(harness, encoding="utf-8")
            return subprocess.run(
                ["tclsh", str(harness_path)],
                check=False,
                capture_output=True,
                text=True,
            )

    completed = source_harness(21, 21)
    if completed.returncode != 0:
        raise AssertionError(
            f"SDC Tcl source failed:\n{completed.stdout}{completed.stderr}"
        )
    if "PASS Tcl source" not in completed.stdout:
        raise AssertionError("SDC Tcl source did not reach its PASS marker")

    failed = source_harness(8, 21)
    diagnostic = failed.stdout + failed.stderr
    if failed.returncode == 0:
        raise AssertionError("SDC accepted an incomplete metadata source collection")
    if (
        "expected 21 metadata_hold registers; found 8 register(s):" not in diagnostic
        or "source_0" not in diagnostic
        or "source_7" not in diagnostic
    ):
        raise AssertionError(f"SDC failure omitted observed endpoints:\n{diagnostic}")

    failed = source_harness(21, 8)
    diagnostic = failed.stdout + failed.stderr
    if failed.returncode == 0:
        raise AssertionError("SDC accepted an incomplete metadata destination collection")
    if (
        "expected 21 destination registers; found 8 register(s):" not in diagnostic
        or "destination_0" not in diagnostic
        or "destination_7" not in diagnostic
    ):
        raise AssertionError(f"SDC failure omitted observed endpoints:\n{diagnostic}")

    print(
        "PASS save metadata CDC constraint endpoints=21 delay=dst-period "
        "skew=min-period fitter-duplicates no-payload-false-path"
    )


if __name__ == "__main__":
    main()
