#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_menu_focus_cdc_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module apf_menu_focus_cdc_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_menu_focus_cdc_tb \
    "$ROOT/src/fpga/core/apf_menu_focus_cdc.sv" \
    "$ROOT/sim/rtl/apf_menu_focus_cdc_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_menu_focus_cdc_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS menu-focus level CDC assert/release/hold/asynchronous-reset$' <<<"$output"; then
  echo "missing menu-focus level CDC PASS marker" >&2
  exit 1
fi
