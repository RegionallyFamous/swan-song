#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_orientation_delivery_e2e_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator --binary --timing -Wall -Wno-fatal -Wno-SYNCASYNCNET \
    --Mdir "$BUILD/obj_dir" \
    --top-module apf_orientation_delivery_e2e_tb \
    -o apf_orientation_delivery_e2e_tb \
    "$ROOT/src/fpga/core/apf_orientation_transition_guard.sv" \
    "$ROOT/src/fpga/core/apf_scaler_selector.sv" \
    "$ROOT/sim/rtl/apf_orientation_delivery_e2e_tb.sv"

output="$("$BUILD/obj_dir/apf_orientation_delivery_e2e_tb" 2>&1)"
printf '%s\n' "$output"
grep -q "PASS APF orientation delivery e2e" <<<"$output"
