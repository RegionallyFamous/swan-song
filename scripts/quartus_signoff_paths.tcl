package require ::quartus::project
package require ::quartus::sta
load_package report

set project_name ap_core
set report_file output_files/ap_core.sta.rpt

if {![file isfile $report_file] || [file size $report_file] == 0} {
    error "base TimeQuest report is missing or empty: $report_file"
}

set project_opened 0
set timing_netlist_open 0
set report_loaded 0
set marker_channel {}

set body_failed [catch {
    project_open $project_name
    set project_opened 1
    # Quartus' supported structured report API is available only after the
    # compilation report database is explicitly loaded.  check_timing itself
    # returns TCL_OK even when it finds problems, so its command status is not
    # a sign-off result.
    load_report
    set report_loaded 1
    create_timing_netlist
    set timing_netlist_open 1
    read_sdc
    update_timing_netlist

    # Validate the SDRAM source-synchronous model in the fitted netlist.  In
    # particular, reference_pin proves that the selected PLL clock is in the
    # direct fan-in of the physical forwarded-clock port; the remaining checks
    # expose incomplete or internally inconsistent min/max I/O delays.
    check_timing \
        -include {reference_pin generated_io_delay partial_input_delay partial_output_delay io_min_max_delay_consistency partial_min_max_delay partial_multicycle multicycle_consistency} \
        -panel_name {Swan Song I/O Constraint Checks} \
        -file $report_file \
        -append

    # Quartus Prime Lite 21.1.1 Build 850 creates one exact Summary panel for
    # the aggregate check above.  Freeze its live-probed schema and all eight
    # zero rows.  Missing, duplicate, added, reordered, nonzero, or newly
    # shaped data is a hard failure rather than a warning hidden in text.
    set check_panel \
        {Timing Analyzer GUI||Swan Song I/O Constraint Checks||Summary}
    set matching_check_panels [list]
    foreach panel [get_report_panel_names] {
        if {[string match {*Swan Song I/O Constraint Checks*} $panel]} {
            lappend matching_check_panels $panel
        }
    }
    if {[llength $matching_check_panels] != 1 ||
        [lindex $matching_check_panels 0] ne $check_panel} {
        error "check_timing panel set changed: $matching_check_panels"
    }
    set check_panel_id [get_report_panel_id $check_panel]
    if {$check_panel_id < 0} {
        error "check_timing Summary panel is missing: $check_panel"
    }
    if {[get_number_of_rows -id $check_panel_id] != 9 ||
        [get_number_of_columns -id $check_panel_id] != 2} {
        error "check_timing Summary schema changed"
    }
    set expected_check_rows [list \
        [list {Check} {Number of Issues Found}] \
        [list reference_pin 0] \
        [list generated_io_delay 0] \
        [list partial_input_delay 0] \
        [list partial_output_delay 0] \
        [list io_min_max_delay_consistency 0] \
        [list partial_min_max_delay 0] \
        [list partial_multicycle 0] \
        [list multicycle_consistency 0]]
    for {set row 0} {$row < 9} {incr row} {
        if {[catch {
            get_report_panel_row -id $check_panel_id -row $row
        } observed]} {
            error "check_timing Summary row $row is unreadable: $observed"
        }
        set expected [lindex $expected_check_rows $row]
        if {[llength $observed] != 2 ||
            [lindex $observed 0] ne [lindex $expected 0] ||
            [lindex $observed 1] ne [lindex $expected 1]} {
            error "check_timing Summary row $row changed: expected $expected; observed $observed"
        }
    }
    set marker_channel [open $report_file a]
    puts $marker_channel {SWAN_SONG_CHECK_TIMING_V2 checks 8 findings 0}
    close $marker_channel
    set marker_channel {}

    # Keep this report bounded while retaining multiple paths per endpoint.
    # Full path and routing detail expose the actual launch/capture registers,
    # clock paths, logic depth, placement, and routing delay for the next fit.
    report_timing \
        -setup \
        -npaths 100 \
        -nworst 3 \
        -detail full_path \
        -show_routing \
        -panel_name {Swan Song Worst Setup Paths} \
        -file $report_file \
        -append
    report_timing \
        -hold \
        -npaths 100 \
        -nworst 3 \
        -detail full_path \
        -show_routing \
        -panel_name {Swan Song Worst Hold Paths} \
        -file $report_file \
        -append

    # Do not request -summary: detailed UCP output is what identifies every
    # exact startpoint and endpoint that still needs a real interface model.
    report_ucp \
        -panel_name {Swan Song Detailed Unconstrained Paths} \
        -file $report_file \
        -append

    # Quartus returns TCL_OK and can leave a usable-looking RBF even when the
    # fitted design has negative slack.  Query paths at internal precision at
    # every fitted-device corner; a value rendered as -0.000 is still caught.
    # Run this after emitting diagnostics so a rejected build remains
    # actionable, then restore the caller's original operating condition.
    set original_operating_condition [get_operating_conditions]
    set operating_conditions [get_available_operating_conditions]
    if {[get_collection_size $operating_conditions] != 4} {
        error "expected four sign-off operating conditions"
    }
    set signoff_dq_ports [get_ports -nowarn {dram_dq[*]}]
    set signoff_dq_registers [get_fanouts -no_logic $signoff_dq_ports]
    if {[get_collection_size $signoff_dq_ports] != 16 ||
        [get_collection_size $signoff_dq_registers] != 16} {
        error "expected exactly sixteen fitted SDRAM DQ capture paths"
    }
    set observed_corner_keys [list]
    set timing_failures [list]
    set pulse_width_checks 0
    set dq_corner_evidence [list]
    foreach_in_collection operating_condition $operating_conditions {
        set model \
            [get_operating_conditions_info $operating_condition -model]
        set temperature \
            [get_operating_conditions_info $operating_condition -temperature]
        set voltage \
            [get_operating_conditions_info $operating_condition -voltage]
        set corner_key [join [list $model $temperature $voltage] {|}]
        lappend observed_corner_keys $corner_key
        set_operating_conditions $operating_condition
        update_timing_netlist

        # Emit bounded full-path evidence after selecting each individual
        # operating condition.  The base .sta report's detailed tables cover
        # only its default corner, which made a failure at slow 0 C impossible
        # to localize from a rejected build without reopening the netlist.
        foreach analysis {setup hold} {
            report_timing \
                -$analysis \
                -npaths 25 \
                -nworst 3 \
                -detail full_path \
                -show_routing \
                -panel_name "Swan Song Worst [string totitle $analysis] $corner_key" \
                -file $report_file \
                -append
        }
        foreach analysis {setup hold recovery removal} {
            set negative_paths \
                [get_timing_paths -$analysis -less_than_slack 0 -npaths 1]
            set negative_count [get_collection_size $negative_paths]
            if {$negative_count > 1} {
                error "unexpected $analysis timing-path collection at $corner_key"
            }
            foreach_in_collection path $negative_paths {
                set path_type [get_path_info $path -type]
                if {$path_type ne $analysis} {
                    error "expected $analysis path at $corner_key, got $path_type"
                }
                lappend timing_failures \
                    "$corner_key $analysis [get_path_info $path -slack]"
            }
        }
        # Minimum-pulse-width checks use a separate TimeQuest API rather than
        # get_timing_paths.  Freeze the live-probed 21.1.1 seven-field schema
        # and test the direct signed Tcl result at TimeQuest's native 1 ps
        # resolution.  Preserve the sign because a displayed -0.000 is still a
        # failure, even though Tcl numeric comparison treats it as zero.
        set pulse_checks [get_min_pulse_width -nworst 1]
        if {[llength $pulse_checks] != 1} {
            error "expected one worst minimum-pulse-width check at $corner_key"
        }
        set pulse_check [lindex $pulse_checks 0]
        if {[llength $pulse_check] != 7} {
            error "minimum-pulse-width schema changed at $corner_key: $pulse_check"
        }
        set pulse_slack [lindex $pulse_check 0]
        # Freeze the decimal text form observed from Quartus 21.1.1.  Tcl
        # accepts NaN/Inf as doubles and compares -0.000 equal to zero; neither
        # is acceptable release evidence.
        if {![regexp {^-?[0-9]+(?:\.[0-9]+)?$} $pulse_slack]} {
            error "non-numeric minimum-pulse-width slack at $corner_key: $pulse_slack"
        }
        incr pulse_width_checks
        if {[string index $pulse_slack 0] eq "-"} {
            lappend timing_failures \
                "$corner_key minimum_pulse_width $pulse_slack"
        }
        report_min_pulse_width \
            -nworst 100 \
            -detail full_path \
            -panel_name "Swan Song Minimum Pulse Width $corner_key" \
            -file $report_file \
            -append

        # Prove the complete source-synchronous bus, not just whichever DQ bit
        # happens to appear in the global top-100 report.  `-nworst 1` yields
        # one worst path for each of the sixteen one-to-one capture endpoints.
        set dq_corner [dict create]
        foreach analysis {setup hold} {
            set dq_paths [get_timing_paths \
                -$analysis \
                -from $signoff_dq_ports \
                -to $signoff_dq_registers \
                -npaths 100 \
                -nworst 1]
            if {[get_collection_size $dq_paths] != 16} {
                error "expected sixteen SDRAM DQ $analysis paths at $corner_key"
            }
            set dq_worst {}
            foreach_in_collection dq_path $dq_paths {
                set dq_type [get_path_info $dq_path -type]
                if {$dq_type ne $analysis} {
                    error "expected SDRAM DQ $analysis path at $corner_key, got $dq_type"
                }
                set dq_slack [get_path_info $dq_path -slack]
                if {![regexp {^-?[0-9]+(?:\.[0-9]+)?$} $dq_slack]} {
                    error "non-numeric SDRAM DQ $analysis slack at $corner_key: $dq_slack"
                }
                if {[string index $dq_slack 0] eq "-"} {
                    lappend timing_failures \
                        "$corner_key sdram_dq_$analysis $dq_slack"
                }
                if {$dq_worst eq {} || [expr {$dq_slack < $dq_worst}]} {
                    set dq_worst $dq_slack
                }
            }
            dict set dq_corner $analysis $dq_worst
            report_timing \
                -$analysis \
                -from $signoff_dq_ports \
                -to $signoff_dq_registers \
                -npaths 100 \
                -nworst 1 \
                -detail full_path \
                -show_routing \
                -panel_name "Swan Song SDRAM DQ [string totitle $analysis] $corner_key" \
                -file $report_file \
                -append
        }
        lappend dq_corner_evidence [list \
            $corner_key [dict get $dq_corner setup] [dict get $dq_corner hold]]
    }
    set_operating_conditions $original_operating_condition
    update_timing_netlist
    set expected_corner_keys [list \
        {slow|85|1100} {slow|0|1100} \
        {fast|85|1100} {fast|0|1100}]
    if {[lsort $observed_corner_keys] ne [lsort $expected_corner_keys]} {
        error "operating condition set changed: $observed_corner_keys"
    }
    if {[llength $timing_failures] != 0} {
        error "negative sign-off timing slack: [join $timing_failures {; }]"
    }
    if {$pulse_width_checks != 4} {
        error "expected four minimum-pulse-width checks; observed $pulse_width_checks"
    }
    set marker_channel [open $report_file a]
    puts $marker_channel \
        {SWAN_SONG_TIMING_GATE_V1 corners 4 analyses 4 negative_paths 0}
    puts $marker_channel \
        {SWAN_SONG_MIN_PULSE_GATE_V1 corners 4 worst_checks 4 negative_checks 0}
    foreach dq_evidence $dq_corner_evidence {
        puts $marker_channel [format \
            {SWAN_SONG_SDRAM_DQ_V1 corner %s setup_paths 16 setup_worst %s hold_paths 16 hold_worst %s} \
            [lindex $dq_evidence 0] \
            [lindex $dq_evidence 1] \
            [lindex $dq_evidence 2]]
    }
    close $marker_channel
    set marker_channel {}
} failure options]

# Cleanup is all-attempted on success and failure.  A cleanup error cannot
# prevent the remaining report/netlist/project resources from being released;
# the primary analysis failure, when present, keeps precedence.
set cleanup_failures [list]
if {$marker_channel ne {}} {
    if {[catch {close $marker_channel} cleanup]} {
        lappend cleanup_failures "close marker: $cleanup"
    }
}
if {$timing_netlist_open} {
    if {[catch {delete_timing_netlist} cleanup]} {
        lappend cleanup_failures "delete timing netlist: $cleanup"
    }
}
if {$report_loaded} {
    if {[catch {unload_report} cleanup]} {
        lappend cleanup_failures "unload report: $cleanup"
    }
}
if {$project_opened} {
    if {[catch {project_close} cleanup]} {
        lappend cleanup_failures "close project: $cleanup"
    }
}

if {$body_failed} {
    return -options $options $failure
}
if {[llength $cleanup_failures] != 0} {
    error "signoff cleanup failed: [join $cleanup_failures {; }]"
}
