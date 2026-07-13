# ================================================================================
# (c) 2011 Altera Corporation. All rights reserved.
# Altera products are protected under numerous U.S. and foreign patents, maskwork
# rights, copyrights and other intellectual property laws.
# 
# This reference design file, and your use thereof, is subject to and governed
# by the terms and conditions of the applicable Altera Reference Design License
# Agreement (either as signed by you, agreed by you upon download or as a
# "click-through" agreement upon installation andor found at www.altera.com).
# By using this reference design file, you indicate your acceptance of such terms
# and conditions between you and Altera Corporation.  In the event that you do
# not agree with such terms and conditions, you may not use the reference design
# file and please promptly destroy any copies you have made.
# 
# This reference design file is being provided on an "as-is" basis and as an
# accommodation and therefore all warranties, representations or guarantees of
# any kind (whether express, implied or statutory) including, without limitation,
# warranties of merchantability, non-infringement, or fitness for a particular
# purpose, are specifically disclaimed.  By making this reference design file
# available, Altera expressly does not recommend, suggest or require that this
# reference design file be used in combination with any other product not
# provided by Altera.
# ================================================================================
#
# APF build identification originally used the build host's current clock and a
# random word. Because this MIF is compiled into the FPGA image, that made two
# otherwise identical Quartus builds byte-different. Swan Song instead binds the
# three established APF words to reproducible source metadata:
#
#   0E0: UTC source date, BCD-like YYYYMMDD
#   0E1: UTC source time, BCD-like HHMMSS (zero-padded to 32 bits)
#   0E2: first 32 bits of the source commit ID
#
# SOURCE_DATE_EPOCH may override the commit timestamp. SWANSONG_SOURCE_COMMIT
# may assert the expected checkout commit. In a Git checkout the assertion must
# match HEAD and tracked source must be clean (the generated MIF itself is
# excluded). Outside Git, both variables are required: without independently
# declared source identity and epoch the script fails instead of inventing an
# unreproducible build ID.
#
# SOURCE_DATE_EPOCH is the distribution-independent reproducible-build timestamp
# contract: https://reproducible-builds.org/specs/source-date-epoch/

proc fail {message} {
    error "build_id_gen.tcl: $message"
}

proc require_commit_id {value name} {
    set normalized [string tolower $value]
    if {![regexp {^(?:[0-9a-f]{40}|[0-9a-f]{64})$} $normalized]} {
        fail "$name must be a full 40- or 64-digit hexadecimal commit ID"
    }
    return $normalized
}

proc require_epoch {value name} {
    if {![regexp {^[0-9]+$} $value]} {
        fail "$name must be non-negative integer seconds since the Unix epoch"
    }
    set epoch [expr {wide($value)}]
    # The APF date word has exactly eight decimal digits (YYYYMMDD).
    if {$epoch > 253402300799} {
        fail "$name is later than 9999-12-31T23:59:59Z"
    }
    return $epoch
}

proc git_output {root args} {
    return [string trim [exec git -C $root {*}$args]]
}

proc assert_clean_source {root} {
    set excludePath {:(exclude)src/fpga/apf/build_id.mif}
    if {[catch {exec git -C $root diff --quiet -- . $excludePath}]} {
        fail "tracked source has unstaged changes; commit it before a reproducible build"
    }
    if {[catch {exec git -C $root diff --cached --quiet -- . $excludePath}]} {
        fail "tracked source has staged changes; commit it before a reproducible build"
    }
}

proc source_metadata {} {
    global env

    set scriptDir [file dirname [file normalize [info script]]]
    set expectedRoot [file normalize [file join $scriptDir .. .. ..]]
    set haveGit 0
    if {![catch {
        set gitRoot [file normalize [git_output $expectedRoot rev-parse --show-toplevel]]
    }]} {
        if {$gitRoot ne $expectedRoot} {
            fail "script source root $expectedRoot does not match Git root $gitRoot"
        }
        set haveGit 1
    }

    set declaredCommit ""
    if {[info exists env(SWANSONG_SOURCE_COMMIT)]} {
        set declaredCommit [require_commit_id $env(SWANSONG_SOURCE_COMMIT) \
            SWANSONG_SOURCE_COMMIT]
    }

    if {$haveGit} {
        set rawHead [git_output $expectedRoot rev-parse --verify HEAD]
        set head [require_commit_id $rawHead {Git HEAD}]
        if {$declaredCommit ne "" && $declaredCommit ne $head} {
            fail "SWANSONG_SOURCE_COMMIT does not match Git HEAD $head"
        }
        assert_clean_source $expectedRoot
        set sourceCommit $head
    } else {
        if {$declaredCommit eq ""} {
            fail "SWANSONG_SOURCE_COMMIT is required outside a Git checkout"
        }
        set sourceCommit $declaredCommit
    }

    if {[info exists env(SOURCE_DATE_EPOCH)]} {
        set sourceEpoch [require_epoch $env(SOURCE_DATE_EPOCH) SOURCE_DATE_EPOCH]
    } elseif {$haveGit} {
        set commitEpoch [git_output $expectedRoot show -s --format=%ct $sourceCommit]
        set sourceEpoch [require_epoch $commitEpoch {Git commit timestamp}]
    } else {
        fail "SOURCE_DATE_EPOCH is required outside a Git checkout"
    }

    return [list $sourceCommit $sourceEpoch]
}

proc generateBuildID_MIF {} {
    lassign [source_metadata] sourceCommit sourceEpoch

    # Always format in UTC so the same declared source inputs are independent
    # of the build host's locale and timezone.
    set buildDate [clock format $sourceEpoch -gmt true -format %Y%m%d]
    set buildTime [clock format $sourceEpoch -gmt true -format %H%M%S]
    set buildTimeWord "00$buildTime"
    set buildUnique [string range $sourceCommit 0 7]

    set outputFileName "apf/build_id.mif"
    set temporaryFileName "$outputFileName.tmp"
    set outputFile [open $temporaryFileName "w"]
    fconfigure $outputFile -encoding utf-8 -translation lf
    puts $outputFile "-- Build ID Memory Initialization File"
    puts $outputFile "-- Reproducible source commit: $sourceCommit"
    puts $outputFile "-- SOURCE_DATE_EPOCH: $sourceEpoch"
    puts $outputFile ""
    puts $outputFile "DEPTH = 256;"
    puts $outputFile "WIDTH = 32;"
    puts $outputFile "ADDRESS_RADIX = HEX;"
    puts $outputFile "DATA_RADIX = HEX;"
    puts $outputFile ""
    puts $outputFile "CONTENT"
    puts $outputFile "BEGIN"
    puts $outputFile ""
    puts $outputFile "   0E0 : $buildDate;"
    puts $outputFile "   0E1 : $buildTimeWord;"
    puts $outputFile "   0E2 : $buildUnique;"
    puts $outputFile ""
    puts $outputFile "END;"
    close $outputFile
    file rename -force $temporaryFileName $outputFileName

    set message "APF reproducible source ID $buildUnique generated: [pwd]/$outputFileName"
    if {[llength [info commands post_message]]} {
        post_message $message
    } else {
        puts $message
    }
}

generateBuildID_MIF
