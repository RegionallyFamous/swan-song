#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_orientation_transition_guard_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator \
    --binary \
    --timing \
    --top-module apf_orientation_transition_guard_tb \
    -Mdir "$BUILD/obj_dir" \
    -o apf_orientation_transition_guard_tb \
    "$ROOT/src/fpga/core/apf_framebank_arbiter.sv" \
    "$ROOT/src/fpga/core/apf_frame_orientation.sv" \
    "$ROOT/src/fpga/core/apf_orientation_transition_guard.sv" \
    "$ROOT/sim/rtl/apf_orientation_transition_guard_tb.sv"

output="$("$BUILD/obj_dir/apf_orientation_transition_guard_tb" 2>&1)"
printf '%s\n' "$output"
grep -q '^PASS APF orientation transition defers=3 protected_drops=3 menu_defer=1 direct_black=1 cold_black=1$' <<<"$output"
