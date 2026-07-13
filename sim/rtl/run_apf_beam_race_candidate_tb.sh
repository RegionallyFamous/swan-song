#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_beam_race_candidate_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator \
    --binary \
    --timing \
    --top-module apf_beam_race_candidate_tb \
    -Mdir "$BUILD/obj_dir" \
    -o apf_beam_race_candidate_tb \
    "$ROOT/src/fpga/core/apf_beam_race_candidate.sv" \
    "$ROOT/sim/rtl/apf_beam_race_candidate_tb.sv"

output="$("$BUILD/obj_dir/apf_beam_race_candidate_tb" 2>&1)"
printf '%s\n' "$output"
grep -q '^PASS APF beam-race candidate fail_closed=3 writer_latched=1 protection=1 coincident_conservative=1$' <<<"$output"
