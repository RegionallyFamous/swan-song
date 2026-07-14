#!/usr/bin/env python3
"""Fail-closed source and Tcl-execution contract for signoff path evidence."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts/build_core.sh"
SCRIPT = ROOT / "scripts/quartus_signoff_paths.tcl"


class QuartusSignoffPathsContract(unittest.TestCase):
    def test_build_requires_quartus_sta_diagnostics_after_compile(self) -> None:
        source = BUILD.read_text(encoding="utf-8")
        compile_call = '"$QUARTUS_SH" --flow compile ap_core'
        diagnostic_call = (
            '"$QUARTUS_STA" -t "$ROOT/scripts/quartus_signoff_paths.tcl"'
        )
        rbf_gate = "test -s output_files/ap_core.rbf"
        self.assertIn(
            'QUARTUS_STA="${QUARTUS_STA:-$(dirname "$(command -v "$QUARTUS_SH")")/quartus_sta}"',
            source,
        )
        self.assertIn('command -v "$QUARTUS_STA"', source)
        self.assertIn(diagnostic_call, source)
        self.assertLess(source.index(compile_call), source.index(diagnostic_call))
        self.assertLess(source.index(diagnostic_call), source.index(rbf_gate))

    def test_failed_post_fit_signoff_deletes_new_rbf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            fpga = root / "src/fpga"
            output = fpga / "output_files"
            tools = root / "tools"
            scripts.mkdir(parents=True)
            output.mkdir(parents=True)
            tools.mkdir()
            build = scripts / "build_core.sh"
            build.write_text(BUILD.read_text(encoding="utf-8"), encoding="utf-8")
            build.chmod(0o755)
            (scripts / "quartus_signoff_paths.tcl").write_text(
                "# fixture\n", encoding="utf-8"
            )
            quartus_sh = tools / "quartus_sh"
            quartus_sh.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "mkdir -p output_files\n"
                "printf candidate > output_files/ap_core.rbf\n",
                encoding="utf-8",
            )
            quartus_sh.chmod(0o755)
            quartus_sta = tools / "quartus_sta"
            quartus_sta.write_text(
                "#!/usr/bin/env bash\nexit 9\n", encoding="utf-8"
            )
            quartus_sta.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{tools}:{environment['PATH']}"
            result = subprocess.run(
                [str(build)],
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            rbf_exists = (output / "ap_core.rbf").exists()
        self.assertEqual(result.returncode, 9, result.stdout + result.stderr)
        self.assertFalse(rbf_exists)

    def test_tcl_emits_bounded_full_setup_hold_and_detailed_ucp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output_files"
            output.mkdir()
            (output / "ap_core.sta.rpt").write_text(
                "genuine base TimeQuest report\n", encoding="utf-8"
            )
            harness = root / "harness.tcl"
            harness.write_text(
                textwrap.dedent(
                    f"""
                    package provide ::quartus::project 1.0
                    package provide ::quartus::sta 1.0
                    set calls [list]
                    set check_rows [list \
                        [list {{Check}} {{Number of Issues Found}}] \
                        [list reference_pin 0] \
                        [list generated_io_delay 0] \
                        [list partial_input_delay 0] \
                        [list partial_output_delay 0] \
                        [list io_min_max_delay_consistency 0] \
                        [list partial_min_max_delay 0] \
                        [list partial_multicycle 0] \
                        [list multicycle_consistency 0]]
                    proc load_package {{args}} {{}}
                    proc project_open {{args}} {{ global calls; lappend calls [list project_open {{*}}$args] }}
                    proc load_report {{args}} {{ global calls; lappend calls [list load_report {{*}}$args] }}
                    proc create_timing_netlist {{args}} {{ global calls; lappend calls [list create_timing_netlist {{*}}$args] }}
                    proc read_sdc {{args}} {{ global calls; lappend calls [list read_sdc {{*}}$args] }}
                    proc update_timing_netlist {{args}} {{ global calls; lappend calls [list update_timing_netlist {{*}}$args] }}
                    proc check_timing {{args}} {{ global calls; lappend calls [list check_timing {{*}}$args] }}
                    proc get_report_panel_names {{args}} {{ return [list {{Timing Analyzer GUI||Swan Song I/O Constraint Checks||Summary}}] }}
                    proc get_report_panel_id {{args}} {{ return 0 }}
                    proc get_number_of_rows {{args}} {{ return 9 }}
                    proc get_number_of_columns {{args}} {{ return 2 }}
                    proc get_report_panel_row {{args}} {{
                        global check_rows
                        set index [lsearch -exact $args -row]
                        return [lindex $check_rows [lindex $args [expr {{$index + 1}}]]]
                    }}
                    proc report_timing {{args}} {{ global calls; lappend calls [list report_timing {{*}}$args] }}
                    proc report_ucp {{args}} {{ global calls; lappend calls [list report_ucp {{*}}$args] }}
                    proc get_operating_conditions {{args}} {{ return original_corner }}
                    proc get_available_operating_conditions {{args}} {{
                        return [list slow85 slow0 fast85 fast0]
                    }}
                    proc get_ports {{args}} {{
                        set ports [list]
                        for {{set index 0}} {{$index < 16}} {{incr index}} {{
                            lappend ports [format {{dram_dq[%d]}} $index]
                        }}
                        return $ports
                    }}
                    proc get_fanouts {{args}} {{
                        set registers [list]
                        for {{set index 0}} {{$index < 16}} {{incr index}} {{
                            lappend registers [format {{dq_reg[%d]}} $index]
                        }}
                        return $registers
                    }}
                    proc get_collection_size {{collection}} {{ return [llength $collection] }}
                    proc foreach_in_collection {{variable collection body}} {{
                        upvar 1 $variable item
                        foreach item $collection {{ uplevel 1 $body }}
                    }}
                    proc get_operating_conditions_info {{condition option}} {{
                        set values [dict create \
                            slow85 [list slow 85 1100] \
                            slow0 [list slow 0 1100] \
                            fast85 [list fast 85 1100] \
                            fast0 [list fast 0 1100]]
                        set offsets [dict create -model 0 -temperature 1 -voltage 2]
                        return [lindex [dict get $values $condition] [dict get $offsets $option]]
                    }}
                    proc set_operating_conditions {{condition}} {{
                        global calls
                        lappend calls [list set_operating_conditions $condition]
                    }}
                    proc get_timing_paths {{args}} {{
                        global calls
                        lappend calls [list get_timing_paths {{*}}$args]
                        if {{[lsearch -exact $args -from] >= 0}} {{
                            set analysis setup
                            if {{[lsearch -exact $args -hold] >= 0}} {{ set analysis hold }}
                            set paths [list]
                            for {{set index 0}} {{$index < 16}} {{incr index}} {{
                                lappend paths "${{analysis}}_dq_$index"
                            }}
                            return $paths
                        }}
                        return [list]
                    }}
                    proc get_path_info {{path option}} {{
                        if {{$option eq "-type"}} {{
                            return [lindex [split $path _] 0]
                        }}
                        if {{$option eq "-slack"}} {{
                            if {{[string match "setup_*" $path]}} {{ return 0.843 }}
                            return 0.521
                        }}
                        error "unknown get_path_info option $option"
                    }}
                    proc get_min_pulse_width {{args}} {{
                        global calls
                        lappend calls [list get_min_pulse_width {{*}}$args]
                        return [list [list 0.753 4.000 3.247 high pll_clk rise pll_target]]
                    }}
                    proc report_min_pulse_width {{args}} {{
                        global calls
                        lappend calls [list report_min_pulse_width {{*}}$args]
                    }}
                    proc delete_timing_netlist {{args}} {{ global calls; lappend calls [list delete_timing_netlist {{*}}$args] }}
                    proc unload_report {{args}} {{ global calls; lappend calls [list unload_report {{*}}$args] }}
                    proc project_close {{args}} {{ global calls; lappend calls [list project_close {{*}}$args] }}
                    source {{{SCRIPT}}}
                    foreach call $calls {{ puts [join $call \\t] }}
                    """
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["tclsh", str(harness)],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            report_text = (output / "ap_core.sta.rpt").read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = result.stdout.splitlines()
        constraint_check = next(
            line for line in calls if line.startswith("check_timing\t")
        )
        setup = next(line for line in calls if line.startswith("report_timing\t-setup"))
        hold = next(line for line in calls if line.startswith("report_timing\t-hold"))
        ucp = next(line for line in calls if line.startswith("report_ucp\t"))
        for timing in (setup, hold):
            self.assertIn("\t-npaths\t100", timing)
            self.assertIn("\t-nworst\t3", timing)
            self.assertIn("\t-detail\tfull_path", timing)
            self.assertIn("\t-show_routing", timing)
            self.assertIn("\t-file\toutput_files/ap_core.sta.rpt\t-append", timing)
        corner_timing = [
            line
            for line in calls
            if line.startswith("report_timing\t")
            and "\t-npaths\t25\t" in line
        ]
        self.assertEqual(len(corner_timing), 8)
        for analysis in ("setup", "hold"):
            self.assertEqual(
                sum(f"\t-{analysis}\t" in line for line in corner_timing), 4
            )
        for timing in corner_timing:
            self.assertIn("\t-nworst\t3", timing)
            self.assertIn("\t-detail\tfull_path", timing)
            self.assertIn("\t-show_routing", timing)
            self.assertIn("\t-file\toutput_files/ap_core.sta.rpt\t-append", timing)
        self.assertIn("\t-file\toutput_files/ap_core.sta.rpt\t-append", ucp)
        self.assertNotIn("\t-summary", ucp)
        self.assertIn(
            "\t-include\treference_pin generated_io_delay partial_input_delay "
            "partial_output_delay io_min_max_delay_consistency partial_min_max_delay "
            "partial_multicycle multicycle_consistency",
            constraint_check,
        )
        self.assertIn(
            "\t-panel_name\tSwan Song I/O Constraint Checks", constraint_check
        )
        self.assertIn(
            "\t-file\toutput_files/ap_core.sta.rpt\t-append", constraint_check
        )
        self.assertEqual(calls.count("create_timing_netlist"), 1)
        self.assertEqual(calls.count("load_report"), 1)
        self.assertEqual(calls.count("read_sdc"), 1)
        self.assertEqual(calls.count("update_timing_netlist"), 6)
        all_timing_queries = [
            line for line in calls if line.startswith("get_timing_paths\t")
        ]
        timing_gates = [
            line for line in all_timing_queries if "\t-less_than_slack\t" in line
        ]
        self.assertEqual(len(timing_gates), 16)
        for analysis in ("setup", "hold", "recovery", "removal"):
            self.assertEqual(
                sum(f"\t-{analysis}\t" in line for line in timing_gates), 4
            )
        for gate in timing_gates:
            self.assertIn("\t-less_than_slack\t0\t-npaths\t1", gate)
        dq_queries = [
            line for line in all_timing_queries if "\t-from\t" in line
        ]
        self.assertEqual(len(dq_queries), 8)
        for analysis in ("setup", "hold"):
            self.assertEqual(
                sum(f"\t-{analysis}\t" in line for line in dq_queries), 4
            )
        for query in dq_queries:
            self.assertIn("\t-npaths\t100\t-nworst\t1", query)
        pulse_gates = [
            line for line in calls if line.startswith("get_min_pulse_width\t")
        ]
        self.assertEqual(pulse_gates, ["get_min_pulse_width\t-nworst\t1"] * 4)
        pulse_reports = [
            line for line in calls if line.startswith("report_min_pulse_width\t")
        ]
        self.assertEqual(len(pulse_reports), 4)
        for pulse_report in pulse_reports:
            self.assertIn("\t-nworst\t100", pulse_report)
            self.assertIn("\t-detail\tfull_path", pulse_report)
            self.assertIn(
                "\t-file\toutput_files/ap_core.sta.rpt\t-append", pulse_report
            )
        self.assertEqual(calls.count("delete_timing_netlist"), 1)
        self.assertEqual(calls.count("unload_report"), 1)
        self.assertEqual(calls.count("project_close"), 1)
        self.assertIn(
            "SWAN_SONG_CHECK_TIMING_V2 checks 8 findings 0", report_text
        )
        self.assertIn(
            "SWAN_SONG_TIMING_GATE_V1 corners 4 analyses 4 negative_paths 0",
            report_text,
        )
        self.assertIn(
            "SWAN_SONG_MIN_PULSE_GATE_V1 corners 4 worst_checks 4 negative_checks 0",
            report_text,
        )
        self.assertEqual(report_text.count("SWAN_SONG_SDRAM_DQ_V1 corner "), 4)
        self.assertIn(
            "SWAN_SONG_SDRAM_DQ_V1 corner slow|85|1100 setup_paths 16 "
            "setup_worst 0.843 hold_paths 16 hold_worst 0.521",
            report_text,
        )

    def test_tcl_fails_closed_on_check_timing_findings_or_schema_changes(self) -> None:
        fixtures = (
            ("finding", 9, 2, 1, "Number of Issues Found", 1, 0, False),
            ("missing_panel", 9, 2, 0, "Number of Issues Found", 0, 0, False),
            ("detail_panel", 9, 2, 0, "Number of Issues Found", 2, 0, False),
            ("extra_row", 10, 2, 0, "Number of Issues Found", 1, 0, False),
            ("extra_column", 9, 3, 0, "Number of Issues Found", 1, 0, False),
            ("changed_header", 9, 2, 0, "Issues", 1, 0, False),
            ("missing_id", 9, 2, 0, "Number of Issues Found", 1, -1, False),
            ("row_api_error", 9, 2, 0, "Number of Issues Found", 1, 0, True),
        )
        for (
            name,
            rows,
            columns,
            finding,
            header,
            panel_count,
            panel_id,
            row_error,
        ) in fixtures:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output = root / "output_files"
                output.mkdir()
                (output / "ap_core.sta.rpt").write_text(
                    "genuine base TimeQuest report\n", encoding="utf-8"
                )
                panels = ""
                if panel_count:
                    panels = (
                        "{Timing Analyzer GUI||Swan Song I/O Constraint Checks||Summary}"
                    )
                if panel_count == 2:
                    panels += (
                        " {Timing Analyzer GUI||Swan Song I/O Constraint Checks||"
                        "reference_pin}"
                    )
                harness = root / "harness.tcl"
                harness.write_text(
                    textwrap.dedent(
                        f"""
                        package provide ::quartus::project 1.0
                        package provide ::quartus::sta 1.0
                        set calls [list]
                        set check_rows [list \
                            [list {{Check}} {{{header}}}] \
                            [list reference_pin {finding}] \
                            [list generated_io_delay 0] \
                            [list partial_input_delay 0] \
                            [list partial_output_delay 0] \
                            [list io_min_max_delay_consistency 0] \
                            [list partial_min_max_delay 0] \
                            [list partial_multicycle 0] \
                            [list multicycle_consistency 0]]
                        proc load_package {{args}} {{}}
                        proc project_open {{args}} {{ global calls; lappend calls project_open }}
                        proc load_report {{args}} {{ global calls; lappend calls load_report }}
                        proc create_timing_netlist {{args}} {{ global calls; lappend calls create_timing_netlist }}
                        proc read_sdc {{args}} {{}}
                        proc update_timing_netlist {{args}} {{}}
                        proc check_timing {{args}} {{}}
                        proc get_report_panel_names {{args}} {{ return [list {panels}] }}
                        proc get_report_panel_id {{args}} {{ return {panel_id} }}
                        proc get_number_of_rows {{args}} {{ return {rows} }}
                        proc get_number_of_columns {{args}} {{ return {columns} }}
                        proc get_report_panel_row {{args}} {{
                            global check_rows
                            if {{{str(row_error).lower()}}} {{ error "injected row API failure" }}
                            set index [lsearch -exact $args -row]
                            return [lindex $check_rows [lindex $args [expr {{$index + 1}}]]]
                        }}
                        proc report_timing {{args}} {{ global calls; lappend calls report_timing }}
                        proc report_ucp {{args}} {{ global calls; lappend calls report_ucp }}
                        proc delete_timing_netlist {{args}} {{ global calls; lappend calls delete_timing_netlist }}
                        proc unload_report {{args}} {{ global calls; lappend calls unload_report }}
                        proc project_close {{args}} {{ global calls; lappend calls project_close }}
                        set failed [catch {{source {{{SCRIPT}}}}} message]
                        puts "FAILED=$failed"
                        puts "MESSAGE=$message"
                        puts "CALLS=$calls"
                        """
                    ),
                    encoding="utf-8",
                )
                result = subprocess.run(
                    ["tclsh", str(harness)],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("FAILED=1", result.stdout)
            self.assertIn("MESSAGE=check_timing", result.stdout)
            self.assertIn("delete_timing_netlist", result.stdout)
            self.assertIn("unload_report", result.stdout)
            self.assertIn("project_close", result.stdout)
            calls = next(
                line for line in result.stdout.splitlines() if line.startswith("CALLS=")
            )
            self.assertNotIn("report_timing", calls)
            self.assertNotIn("report_ucp", calls)

    def test_tcl_fails_closed_on_minimum_pulse_width_failures(self) -> None:
        fixtures = (
            (
                "negative",
                "[list [list -0.001 4.000 4.001 high pll_clk rise pll_target]]",
                "negative sign-off timing slack",
            ),
            (
                "negative_zero",
                "[list [list -0.000 4.000 4.000 high pll_clk rise pll_target]]",
                "negative sign-off timing slack",
            ),
            ("missing", "[list]", "expected one worst minimum-pulse-width check"),
            (
                "duplicate",
                "[list [list 0.100 4.000 3.900 high pll_clk rise pll_target] "
                "[list 0.200 4.000 3.800 high pll_clk rise pll_target]]",
                "expected one worst minimum-pulse-width check",
            ),
            (
                "short_schema",
                "[list [list 0.100 4.000 3.900 high pll_clk rise]]",
                "minimum-pulse-width schema changed",
            ),
            (
                "non_numeric",
                "[list [list invalid 4.000 3.900 high pll_clk rise pll_target]]",
                "non-numeric minimum-pulse-width slack",
            ),
            (
                "nan",
                "[list [list NaN 4.000 3.900 high pll_clk rise pll_target]]",
                "non-numeric minimum-pulse-width slack",
            ),
            (
                "infinity",
                "[list [list Inf 4.000 3.900 high pll_clk rise pll_target]]",
                "non-numeric minimum-pulse-width slack",
            ),
        )
        for name, pulse_result, expected_message in fixtures:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output = root / "output_files"
                output.mkdir()
                report = output / "ap_core.sta.rpt"
                report.write_text("genuine base TimeQuest report\n", encoding="utf-8")
                harness = root / "harness.tcl"
                harness.write_text(
                    textwrap.dedent(
                        f"""
                        package provide ::quartus::project 1.0
                        package provide ::quartus::sta 1.0
                        set calls [list]
                        set pulse_result {pulse_result}
                        set check_rows [list \
                            [list {{Check}} {{Number of Issues Found}}] \
                            [list reference_pin 0] \
                            [list generated_io_delay 0] \
                            [list partial_input_delay 0] \
                            [list partial_output_delay 0] \
                            [list io_min_max_delay_consistency 0] \
                            [list partial_min_max_delay 0] \
                            [list partial_multicycle 0] \
                            [list multicycle_consistency 0]]
                        proc load_package {{args}} {{}}
                        proc project_open {{args}} {{ global calls; lappend calls project_open }}
                        proc load_report {{args}} {{ global calls; lappend calls load_report }}
                        proc create_timing_netlist {{args}} {{ global calls; lappend calls create_timing_netlist }}
                        proc read_sdc {{args}} {{}}
                        proc update_timing_netlist {{args}} {{}}
                        proc check_timing {{args}} {{}}
                        proc get_report_panel_names {{args}} {{
                            return [list {{Timing Analyzer GUI||Swan Song I/O Constraint Checks||Summary}}]
                        }}
                        proc get_report_panel_id {{args}} {{ return 0 }}
                        proc get_number_of_rows {{args}} {{ return 9 }}
                        proc get_number_of_columns {{args}} {{ return 2 }}
                        proc get_report_panel_row {{args}} {{
                            global check_rows
                            set index [lsearch -exact $args -row]
                            return [lindex $check_rows [lindex $args [expr {{$index + 1}}]]]
                        }}
                        proc report_timing {{args}} {{}}
                        proc report_ucp {{args}} {{}}
                        proc get_operating_conditions {{args}} {{ return original_corner }}
                        proc get_available_operating_conditions {{args}} {{
                            return [list slow85 slow0 fast85 fast0]
                        }}
                        proc get_ports {{args}} {{
                            set ports [list]
                            for {{set index 0}} {{$index < 16}} {{incr index}} {{
                                lappend ports [format {{dram_dq[%d]}} $index]
                            }}
                            return $ports
                        }}
                        proc get_fanouts {{args}} {{
                            set registers [list]
                            for {{set index 0}} {{$index < 16}} {{incr index}} {{
                                lappend registers [format {{dq_reg[%d]}} $index]
                            }}
                            return $registers
                        }}
                        proc get_collection_size {{collection}} {{ return [llength $collection] }}
                        proc foreach_in_collection {{variable collection body}} {{
                            upvar 1 $variable item
                            foreach item $collection {{ uplevel 1 $body }}
                        }}
                        proc get_operating_conditions_info {{condition option}} {{
                            set values [dict create \
                                slow85 [list slow 85 1100] \
                                slow0 [list slow 0 1100] \
                                fast85 [list fast 85 1100] \
                                fast0 [list fast 0 1100]]
                            set offsets [dict create -model 0 -temperature 1 -voltage 2]
                            return [lindex [dict get $values $condition] [dict get $offsets $option]]
                        }}
                        proc set_operating_conditions {{args}} {{}}
                        proc get_timing_paths {{args}} {{
                            if {{[lsearch -exact $args -from] >= 0}} {{
                                set analysis setup
                                if {{[lsearch -exact $args -hold] >= 0}} {{ set analysis hold }}
                                set paths [list]
                                for {{set index 0}} {{$index < 16}} {{incr index}} {{
                                    lappend paths "${{analysis}}_dq_$index"
                                }}
                                return $paths
                            }}
                            return [list]
                        }}
                        proc get_path_info {{path option}} {{
                            if {{$option eq "-type"}} {{ return [lindex [split $path _] 0] }}
                            if {{$option eq "-slack"}} {{ return 0.500 }}
                            error "unknown get_path_info option $option"
                        }}
                        proc get_min_pulse_width {{args}} {{
                            global pulse_result
                            return $pulse_result
                        }}
                        proc report_min_pulse_width {{args}} {{}}
                        proc delete_timing_netlist {{args}} {{ global calls; lappend calls delete_timing_netlist }}
                        proc unload_report {{args}} {{ global calls; lappend calls unload_report }}
                        proc project_close {{args}} {{ global calls; lappend calls project_close }}
                        set failed [catch {{source {{{SCRIPT}}}}} message]
                        puts "FAILED=$failed"
                        puts "MESSAGE=$message"
                        puts "CALLS=$calls"
                        """
                    ),
                    encoding="utf-8",
                )
                result = subprocess.run(
                    ["tclsh", str(harness)],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                report_text = report.read_text(encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("FAILED=1", result.stdout)
            self.assertIn(f"MESSAGE={expected_message}", result.stdout)
            self.assertIn("delete_timing_netlist", result.stdout)
            self.assertIn("unload_report", result.stdout)
            self.assertIn("project_close", result.stdout)
            self.assertNotIn("SWAN_SONG_MIN_PULSE_GATE_V1", report_text)

    def test_tcl_rejects_missing_or_empty_base_report_before_opening_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "output_files").mkdir()
            harness = root / "harness.tcl"
            harness.write_text(
                textwrap.dedent(
                    f"""
                    package provide ::quartus::project 1.0
                    package provide ::quartus::sta 1.0
                    proc load_package {{args}} {{}}
                    proc project_open {{args}} {{ error "project unexpectedly opened" }}
                    source {{{SCRIPT}}}
                    """
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                ["tclsh", str(harness)],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("base TimeQuest report is missing or empty", result.stderr)


if __name__ == "__main__":
    unittest.main()
