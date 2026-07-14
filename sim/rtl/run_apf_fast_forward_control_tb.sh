#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_fast_forward_control_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module apf_fast_forward_control_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_fast_forward_control_tb \
    "$ROOT/src/fpga/core/apf_fast_forward_control.sv" \
    "$ROOT/sim/rtl/apf_fast_forward_control_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_fast_forward_control_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS Fast Forward tap, hold, focus/reset/title clear, and neutral rearm contract$' <<<"$output"; then
  echo "missing Fast Forward control PASS marker" >&2
  exit 1
fi
