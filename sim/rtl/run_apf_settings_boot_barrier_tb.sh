#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_settings_boot_barrier_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --Wno-PINMISSING \
    --top-module apf_settings_boot_barrier_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_settings_boot_barrier_tb \
    "$ROOT/src/fpga/core/core_bridge_cmd.v" \
    "$ROOT/src/fpga/core/apf_settings_cdc.sv" \
    "$ROOT/sim/rtl/apf_settings_boot_barrier_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_settings_boot_barrier_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
grep -q '^PASS APF settings boot barrier ' <<<"$output"
