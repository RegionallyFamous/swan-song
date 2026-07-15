#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_menu_focus_pause_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module apf_menu_focus_pause_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_menu_focus_pause_tb \
    "$ROOT/src/fpga/core/apf_gamepad_filter.sv" \
    "$ROOT/src/fpga/core/apf_input_blocked_cdc.sv" \
    "$ROOT/src/fpga/core/apf_menu_focus_cdc.sv" \
    "$ROOT/src/fpga/core/apf_fast_forward_control.sv" \
    "$ROOT/sim/rtl/apf_menu_focus_pause_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_menu_focus_pause_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS 00B0 pause/resume independent of PAD neutral rearm; Fast Forward safe$' <<<"$output"; then
  echo "missing menu-focus pause integration PASS marker" >&2
  exit 1
fi
