#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_scanout_cadence_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator \
    --binary \
    --timing \
    --top-module apf_scanout_cadence_tb \
    -Mdir "$BUILD/obj_dir" \
    -o apf_scanout_cadence_tb \
    "$ROOT/src/fpga/core/apf_scanout_cadence.sv" \
    "$ROOT/sim/rtl/apf_scanout_cadence_tb.sv"

output="$("$BUILD/obj_dir/apf_scanout_cadence_tb" 2>&1)"
printf '%s\n' "$output"
grep -q '^PASS APF scanout cadence standard=397x258@59.984769Hz smooth=391x258@60.905252Hz mode-switch=frame-atomic$' <<<"$output"
