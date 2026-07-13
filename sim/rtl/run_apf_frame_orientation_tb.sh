#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_frame_orientation_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator \
    --binary \
    --assert \
    --top-module apf_frame_orientation_tb \
    -Wno-fatal \
    -o apf_frame_orientation_tb \
    "$ROOT/src/fpga/core/apf_framebank_arbiter.sv" \
    "$ROOT/src/fpga/core/apf_frame_orientation.sv" \
    "$ROOT/sim/rtl/apf_frame_orientation_tb.sv" \
    --Mdir "$BUILD/obj_dir" >/dev/null

output="$("$BUILD/obj_dir/apf_frame_orientation_tb")"
printf '%s\n' "$output"
grep -q '^PASS APF frame orientation ' <<<"$output"
