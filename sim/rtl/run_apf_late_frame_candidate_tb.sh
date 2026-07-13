#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_late_frame_candidate_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator \
    --binary \
    --timing \
    --top-module apf_late_frame_candidate_tb \
    -Mdir "$BUILD/obj_dir" \
    -o apf_late_frame_candidate_tb \
    "$ROOT/src/fpga/core/apf_late_frame_candidate.sv" \
    "$ROOT/sim/rtl/apf_late_frame_candidate_tb.sv"

output="$("$BUILD/obj_dir/apf_late_frame_candidate_tb" 2>&1)"
printf '%s\n' "$output"
grep -q '^PASS APF late-frame candidate exact60=1 no_completion_repeat=1 slot_defer=2 protected=1 cold_blank=1$' <<<"$output"
