#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_scaler_selector_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --top-module apf_scaler_selector_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_scaler_selector_tb \
    "$ROOT/src/fpga/core/apf_scaler_selector.sv" \
    "$ROOT/sim/rtl/apf_scaler_selector_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_scaler_selector_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS APF scaler selector ' <<<"$output"; then
  echo "missing APF scaler selector PASS marker" >&2
  exit 1
fi
