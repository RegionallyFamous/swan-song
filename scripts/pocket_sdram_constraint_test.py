#!/usr/bin/env python3
"""Source-lock and mutation-test the Pocket SDRAM timing model."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SDC = ROOT / "src/fpga/core/core_constraints.sdc"
SDRAM = ROOT / "src/fpga/core/rtl/sdram.sv"
QSF = ROOT / "src/fpga/ap_core.qsf"
APF_SDC = ROOT / "src/fpga/apf/apf_constraints.sdc"

EXACT_LIMITS = (
    "set_output_delay -clock $dram_chip_clk -clock_fall -reference_pin $sdram_clock_port -max 2.0 -add_delay $sdram_write_ports",
    "set_output_delay -clock $dram_chip_clk -clock_fall -reference_pin $sdram_clock_port -min -1.0 -add_delay $sdram_write_ports",
    "set_input_delay -clock $dram_chip_clk -clock_fall -reference_pin $sdram_clock_port -max 5.9 -add_delay $sdram_read_ports",
    "set_input_delay -clock $dram_chip_clk -clock_fall -reference_pin $sdram_clock_port -min 2.5 -add_delay $sdram_read_ports",
)
EXACT_MULTICYCLES = (
    "set_multicycle_path -setup -end -from $sdram_read_ports -to $sdram_capture_registers 2",
    "set_multicycle_path -hold -end -from $sdram_read_ports -to $sdram_capture_registers 0",
)


def validate_model(source: str) -> None:
    for limit in EXACT_LIMITS:
        if source.count(limit) != 1:
            raise AssertionError(f"exact SDRAM timing policy changed or duplicated: {limit}")
    if re.search(r"set_false_path[^\n]*(?:dram_|sdram)", source, re.IGNORECASE):
        raise AssertionError("real SDRAM paths must never be hidden with a false path")
    for multicycle in EXACT_MULTICYCLES:
        if source.count(multicycle) != 1:
            raise AssertionError(
                f"exact SDRAM two-sample contract changed or duplicated: {multicycle}"
            )
    sdram_hold_lines = [
        line.strip()
        for line in source.splitlines()
        if "set_multicycle_path" in line
        and "-hold" in line
        and (
            "$sdram_read_ports" in line
            or "$sdram_capture_registers" in line
        )
    ]
    if sdram_hold_lines != [EXACT_MULTICYCLES[1]]:
        raise AssertionError(
            "exact SDRAM two-sample contract must use only explicit hold-zero"
        )
    capture_selector = "set sdram_capture_registers [get_fanouts -no_logic $sdram_read_ports]"
    if source.count(capture_selector) != 1:
        raise AssertionError(
            "exact SDRAM two-sample contract capture hierarchy changed"
        )


def validate_capture_contract(source: str) -> None:
    compact = re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", source))
    capture = (
        "always@(posedgeclk)begin"
        "if(init)dq_reg<=16'd0;"
        "elsedq_reg<=SDRAM_DQ;"
        "end"
    )
    if compact.count(capture) != 1:
        raise AssertionError("dq_reg must be reset/sample exactly once on posedge clk")
    if compact.count("dq_reg<=") != 2:
        raise AssertionError("dq_reg must have one single-driver edge process")
    for channel in (1, 2, 3):
        width = f"reg[CAS_LATENCY+BURST_LENGTH+1:0]data_ready_delay{channel};"
        launch = (
            f"data_ready_delay{channel}[CAS_LATENCY+BURST_LENGTH+1]<=1;"
        )
        if compact.count(width) != 1 or compact.count(launch) != 1:
            raise AssertionError(
                "read-ready pipeline must consume the post-r+3 dq_reg sample"
            )
    for channel in (1, 2, 3):
        consumer = (
            f"if(data_ready_delay{channel}[1])"
            f"ch{channel}_dout[15:00]<=dq_reg;"
        )
        if compact.count(consumer) != 1:
            raise AssertionError(
                "downstream read-data consumption must remain on the controller process"
            )


def validate_ddio_clock_contract(source: str) -> None:
    uncommented = re.sub(r"//[^\n]*", "", source)
    compact = re.sub(r"\s+", "", uncommented)
    instances = re.findall(r"\baltddio_out\b\s*#\s*\(", uncommented)
    if len(instances) != 1:
        raise AssertionError("SDRAM clock must have exactly one ALTDDIO_OUT driver")
    blocks = re.findall(
        r"\bsdramclk_ddr\s*\((.*?)\)\s*;", uncommented, re.DOTALL
    )
    if len(blocks) != 1:
        raise AssertionError("SDRAM clock ALTDDIO_OUT instance changed or duplicated")
    block = re.sub(r"\s+", "", blocks[0])
    required = (
        ".datain_h(1'b0)",
        ".datain_l(1'b1)",
        ".outclock(clk)",
        ".dataout(SDRAM_CLK)",
    )
    if any(block.count(connection) != 1 for connection in required):
        raise AssertionError("SDRAM clock must remain an inverted copy of clk")
    if compact.count('.invert_output("OFF")') != 1:
        raise AssertionError("SDRAM clock primitive inversion policy changed")
    if compact.count("SDRAM_CLK") != 2:
        raise AssertionError("SDRAM_CLK must be driven only by ALTDDIO_OUT")


def source_sdc(
    sdram_clock_count: int = 1,
    sdram_clock_port_count: int = 1,
    write_ports: int = 37,
    read_ports: int = 16,
    capture_fanouts: int = 16,
    capture_registers: int = 16,
    apf_input_ports: int = 4,
    apf_bridge_output_ports: int = 3,
    apf_scaler_output_ports: int = 20,
) -> subprocess.CompletedProcess[str]:
    harness = f"""
proc get_clocks {{args}} {{
  set result {{}}
  for {{set i 0}} {{$i < {sdram_clock_count}}} {{incr i}} {{ lappend result "sdram_pll_clock_$i" }}
  return $result
}}
proc get_ports {{args}} {{
  set filter [lindex $args end]
  set result {{}}
  if {{[string first "dram_clk" $filter] >= 0}} {{
    for {{set i 0}} {{$i < {sdram_clock_port_count}}} {{incr i}} {{ lappend result "dram_clk_$i" }}
    return $result
  }}
  if {{[string first "dram_a" $filter] >= 0}} {{
    for {{set i 0}} {{$i < {write_ports}}} {{incr i}} {{ lappend result "write_$i" }}
  }} elseif {{[string first "dram_dq" $filter] >= 0}} {{
    for {{set i 0}} {{$i < {read_ports}}} {{incr i}} {{ lappend result "read_$i" }}
  }} elseif {{[string first "bridge_spiss" $filter] >= 0}} {{
    for {{set i 0}} {{$i < {apf_input_ports}}} {{incr i}} {{ lappend result "apf_input_$i" }}
  }} elseif {{[string first "bridge_1wire" $filter] >= 0}} {{
    for {{set i 0}} {{$i < {apf_bridge_output_ports}}} {{incr i}} {{ lappend result "apf_bridge_output_$i" }}
  }} elseif {{[string first "scal_auddac" $filter] >= 0}} {{
    for {{set i 0}} {{$i < {apf_scaler_output_ports}}} {{incr i}} {{ lappend result "apf_scaler_output_$i" }}
  }}
  return $result
}}
proc get_registers {{args}} {{
  set filter [lindex $args end]
  set result {{}}
  if {{[string first "sdram:sdram|dq_reg" $filter] >= 0}} {{
    set count {capture_registers}; set stem sdram_capture
  }} elseif {{[string first "settings_hold_source" $filter] >= 0}} {{
    set count 13; set stem settings_source
  }} elseif {{[string first "settings_destination" $filter] >= 0}} {{
    set count 13; set stem settings_destination
  }} elseif {{[string first "slot_hold_sys" $filter] >= 0}} {{
    set count 2; set stem scaler_source
  }} elseif {{[string first "pending_slot_video" $filter] >= 0}} {{
    set count 2; set stem scaler_destination
  }} elseif {{[string first "input_state_system_cdc|payload_hold_source" $filter] >= 0}} {{
    set count 17; set stem input_state_source
  }} elseif {{[string first "input_state_system_cdc|payload_destination" $filter] >= 0}} {{
    set count 13; set stem input_state_destination
  }} elseif {{[string first "metadata_hold" $filter] >= 0}} {{
    set count 21; set stem metadata_source
  }} elseif {{[string first "save_size_bytes_74a" $filter] >= 0}} {{
    set count 21; set stem metadata_destination
  }} else {{
    return $result
  }}
  for {{set i 0}} {{$i < $count}} {{incr i}} {{ lappend result "${{stem}}_$i" }}
  return $result
}}
proc get_fanouts {{args}} {{
  set result {{}}
  for {{set i 0}} {{$i < {capture_fanouts}}} {{incr i}} {{
    lappend result "sdram_capture_$i"
  }}
  return $result
}}
proc get_collection_size {{collection}} {{ return [llength $collection] }}
proc foreach_in_collection {{variable collection body}} {{
  upvar 1 $variable item
  foreach item $collection {{ uplevel 1 $body }}
}}
proc get_object_info {{args}} {{ return [lindex $args end] }}
proc set_clock_groups {{args}} {{ set ::clock_groups $args }}
proc set_output_delay {{args}} {{ lappend ::output_delays $args }}
proc set_input_delay {{args}} {{ lappend ::input_delays $args }}
proc set_multicycle_path {{args}} {{ lappend ::multicycles $args }}
proc set_false_path {{args}} {{}}
proc set_net_delay {{args}} {{}}
proc set_max_skew {{args}} {{}}
proc derive_clock_uncertainty {{}} {{}}
set ::clock_groups {{}}
set ::output_delays {{}}
set ::input_delays {{}}
set ::multicycles {{}}
source {{{SDC}}}
puts "GROUPS=$::clock_groups"
puts "OUT=$::output_delays"
puts "IN=$::input_delays"
puts "MULTICYCLES=$::multicycles"
"""
    with tempfile.TemporaryDirectory(prefix="sdram-sdc-") as temporary:
        script = Path(temporary) / "contract.tcl"
        script.write_text(harness, encoding="utf-8")
        return subprocess.run(
            ["tclsh", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )


class PocketSdramConstraintContract(unittest.TestCase):
    def test_exact_part_mode_clock_and_timing_policy_are_constrained(self) -> None:
        sdc = SDC.read_text(encoding="utf-8")
        rtl = SDRAM.read_text(encoding="utf-8")
        qsf = QSF.read_text(encoding="utf-8")
        apf_sdc = APF_SDC.read_text(encoding="utf-8")
        validate_model(sdc)
        validate_capture_contract(rtl)
        validate_ddio_clock_contract(rtl)
        self.assertRegex(rtl, r"localparam\s+CAS_LATENCY\s*=\s*3'd3")
        self.assertIn("FAST_OUTPUT_REGISTER ON -to dram*", qsf)
        self.assertIn("FAST_INPUT_REGISTER ON -to dram_dq[]", qsf)
        self.assertIn("AS4C32M16MSA-6BIN", sdc)
        self.assertIn("set sdram_chip_clock [get_clocks -nowarn $dram_chip_clk]", sdc)
        self.assertNotIn("create_generated_clock -name sdram_clk", sdc)
        self.assertNotIn("SDC_FILE core/core_constraints.sdc", qsf)
        self.assertEqual(
            apf_sdc.count('read_sdc "core/core_constraints.sdc"'), 1
        )
        self.assertEqual(qsf.count("set_global_assignment -name SEED 3"), 1)
        self.assertNotRegex(qsf, r"set_global_assignment -name SEED (?!3(?:\s|$))")

        result = source_sdc()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        groups = next(
            line for line in result.stdout.splitlines() if line.startswith("GROUPS=")
        )
        self.assertIn("general[0].gpll~PLL_OUTPUT_COUNTER|divclk", groups)

        prefit = source_sdc(capture_fanouts=0)
        self.assertEqual(prefit.returncode, 0, prefit.stdout + prefit.stderr)

    def test_cardinality_guards_reject_missing_physical_ports(self) -> None:
        missing_clock = source_sdc(sdram_clock_count=0)
        self.assertNotEqual(missing_clock.returncode, 0)
        self.assertIn(
            "expected exactly one memory PLL clock",
            missing_clock.stdout + missing_clock.stderr,
        )
        missing_clock_port = source_sdc(sdram_clock_port_count=0)
        self.assertNotEqual(missing_clock_port.returncode, 0)
        self.assertIn(
            "expected exactly one dram_clk port",
            missing_clock_port.stdout + missing_clock_port.stderr,
        )
        missing_write = source_sdc(write_ports=36)
        self.assertNotEqual(missing_write.returncode, 0)
        self.assertIn(
            "expected exactly 37 write-side ports",
            missing_write.stdout + missing_write.stderr,
        )
        missing_read = source_sdc(read_ports=15)
        self.assertNotEqual(missing_read.returncode, 0)
        self.assertIn(
            "expected exactly 16 read-side DQ ports",
            missing_read.stdout + missing_read.stderr,
        )
        missing_capture = source_sdc(capture_fanouts=15)
        self.assertNotEqual(missing_capture.returncode, 0)
        self.assertIn(
            "expected exactly 16 dq_reg capture registers",
            missing_capture.stdout + missing_capture.stderr,
        )
        missing_prefit_capture = source_sdc(
            capture_fanouts=0, capture_registers=15
        )
        self.assertNotEqual(missing_prefit_capture.returncode, 0)
        self.assertIn(
            "expected exactly 16 dq_reg capture registers; observed 15",
            missing_prefit_capture.stdout + missing_prefit_capture.stderr,
        )

    def test_each_timing_limit_mutation_is_detected(self) -> None:
        source = SDC.read_text(encoding="utf-8")
        mutations = (
            (EXACT_LIMITS[0], EXACT_LIMITS[0].replace("-max 2.0", "-max 2.1")),
            (EXACT_LIMITS[1], EXACT_LIMITS[1].replace("-min -1.0", "-min -1.1")),
            (EXACT_LIMITS[2], EXACT_LIMITS[2].replace("-max 5.9", "-max 6.0")),
            (EXACT_LIMITS[3], EXACT_LIMITS[3].replace("-min 2.5", "-min 2.4")),
        )
        for expected, replacement in mutations:
            with self.subTest(expected=expected, replacement=replacement):
                self.assertNotEqual(expected, replacement)
                mutated = source.replace(expected, replacement, 1)
                with self.assertRaisesRegex(AssertionError, "exact SDRAM timing policy"):
                    validate_model(mutated)

    def test_dq_capture_edge_and_single_driver_mutations_are_detected(self) -> None:
        source = SDRAM.read_text(encoding="utf-8")
        mutations = (
            source.replace("always @(posedge clk) begin", "always @(negedge clk) begin", 1),
            source.replace(
                "\telse      dq_reg <= SDRAM_DQ;",
                "\telse      dq_reg <= SDRAM_DQ;\n\tdq_reg <= SDRAM_DQ;",
                1,
            ),
            source.replace(
                "if(data_ready_delay1[1]) ch1_dout[15:00] <= dq_reg;",
                "if(data_ready_delay1[1]) ch1_dout[15:00] <= SDRAM_DQ;",
                1,
            ),
            source.replace(
                "data_ready_delay1[CAS_LATENCY+BURST_LENGTH+1] <= 1;",
                "data_ready_delay1[CAS_LATENCY+BURST_LENGTH+2] <= 1;",
                1,
            ),
        )
        for number, mutated in enumerate(mutations):
            with self.subTest(mutation=number):
                with self.assertRaises(AssertionError):
                    validate_capture_contract(mutated)

    def test_ddio_forwarded_clock_mutations_are_detected(self) -> None:
        source = SDRAM.read_text(encoding="utf-8")
        second_driver = """
altddio_out #() duplicate_sdram_clock (
    .datain_h(1'b0), .datain_l(1'b1), .outclock(clk),
    .dataout(unused_duplicate_clock));
"""
        mutations = (
            source.replace(".datain_h(1'b0)", ".datain_h(1'b1)", 1),
            source.replace(".datain_l(1'b1)", ".datain_l(1'b0)", 1),
            source.replace(".outclock(clk)", ".outclock(~clk)", 1),
            source.replace('.invert_output("OFF")', '.invert_output("ON")', 1),
            source.replace("endmodule", second_driver + "\nendmodule", 1),
            source.replace("endmodule", "assign SDRAM_CLK = clk;\nendmodule", 1),
        )
        for number, mutated in enumerate(mutations):
            with self.subTest(mutation=number):
                with self.assertRaises(AssertionError):
                    validate_ddio_clock_contract(mutated)

    def test_multicycle_mutations_are_detected(self) -> None:
        source = SDC.read_text(encoding="utf-8")
        mutations = (
            source.replace(EXACT_MULTICYCLES[0], EXACT_MULTICYCLES[0][:-1] + "1", 1),
            source.replace(EXACT_MULTICYCLES[1], EXACT_MULTICYCLES[1][:-1] + "1", 1),
            source.replace(
                "[get_fanouts -no_logic $sdram_read_ports]",
                "[get_registers -nowarn {*dq_reg*}]",
                1,
            ),
        )
        for number, mutated in enumerate(mutations):
            with self.subTest(mutation=number):
                with self.assertRaisesRegex(
                    AssertionError, "two-sample contract"
                ):
                    validate_model(mutated)


if __name__ == "__main__":
    unittest.main()
