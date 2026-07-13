#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_gamepad_filter_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module apf_gamepad_filter_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_gamepad_filter_tb \
    "$ROOT/src/fpga/apf/common.v" \
    "$ROOT/src/fpga/apf/io_pad_controller.v" \
    "$ROOT/src/fpga/core/apf_gamepad_filter.sv" \
    "$ROOT/sim/rtl/apf_gamepad_filter_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_gamepad_filter_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS APF PAD 32-bit transport, type safety, disconnect, timeout, and reset$' <<<"$output"; then
  echo "missing APF gamepad filter PASS marker" >&2
  exit 1
fi
