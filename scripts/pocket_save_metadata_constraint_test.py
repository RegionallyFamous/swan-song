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
        r"ASYNC_REG[^\n]*reg\s+request_meta\s*;.*"
        r"ASYNC_REG[^\n]*reg\s+request_sync\s*;",
        cdc,
        "request toggle does not have the expected two-flop synchronizer",
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
        r"-from\s+\$save_metadata_source_registers\s+.*"
        r"-to\s+\$save_metadata_destination_registers",
        sdc,
        "payload net delay is not bounded to one destination period",
    )
    require(
        r"set_max_skew\s+.*"
        r"-get_skew_value_from_clock_period\s+min_clock_period\s+.*"
        r"-skew_value_multiplier\s+1\.0\s+.*"
        r"-from\s+\$save_metadata_source_registers\s+.*"
        r"-to\s+\$save_metadata_destination_registers",
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
    harness = f"""
proc set_clock_groups {{args}} {{}}
proc derive_clock_uncertainty {{}} {{}}
proc get_registers {{args}} {{
  set filter [lindex $args end]
  set result {{}}
  if {{[string first "metadata_hold" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 21}} {{incr i}} {{ lappend result "source_$i" }}
  }} elseif {{[string first "save_size_bytes_74a" $filter] >= 0 &&
              [string first "has_rtc_74a" $filter] >= 0}} {{
    for {{set i 0}} {{$i < 21}} {{incr i}} {{ lappend result "destination_$i" }}
  }}
  return $result
}}
proc get_collection_size {{collection}} {{ return [llength $collection] }}
set ::net_delay_args {{}}
set ::max_skew_args {{}}
proc set_net_delay {{args}} {{ set ::net_delay_args $args }}
proc set_max_skew {{args}} {{ set ::max_skew_args $args }}
source {{{SDC}}}
if {{[llength $::net_delay_args] == 0}} {{ error "set_net_delay was not called" }}
if {{[llength $::max_skew_args] == 0}} {{ error "set_max_skew was not called" }}
puts "PASS Tcl source"
"""
    with tempfile.TemporaryDirectory(prefix="save-metadata-sdc-test-") as temporary:
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
            f"SDC Tcl source failed:\n{completed.stdout}{completed.stderr}"
        )
    if "PASS Tcl source" not in completed.stdout:
        raise AssertionError("SDC Tcl source did not reach its PASS marker")

    print(
        "PASS save metadata CDC constraint endpoints=21 delay=dst-period "
        "skew=min-period no-payload-false-path"
    )


if __name__ == "__main__":
    main()
