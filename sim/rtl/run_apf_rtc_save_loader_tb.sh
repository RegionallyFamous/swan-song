#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_rtc_save_loader_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module apf_rtc_save_loader_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_rtc_save_loader_tb \
    "$ROOT/src/fpga/core/apf_rtc_save_loader.sv" \
    "$ROOT/sim/rtl/apf_rtc_save_loader_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_rtc_save_loader_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS canonical and legacy padded EEPROM RTC save loading$' <<<"$output"; then
  echo "missing RTC save-loader PASS marker" >&2
  exit 1
fi
