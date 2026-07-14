#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_input_blocked_cdc_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module apf_input_blocked_cdc_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_input_blocked_cdc_tb \
    "$ROOT/src/fpga/core/apf_input_blocked_cdc.sv" \
    "$ROOT/sim/rtl/apf_input_blocked_cdc_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_input_blocked_cdc_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS atomic buttons+ownership CDC, coalescing, neutral rearm, and reset$' <<<"$output"; then
  echo "missing atomic physical-input state CDC PASS marker" >&2
  exit 1
fi
