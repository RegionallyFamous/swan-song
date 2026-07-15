#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_savestate_v2_restore_preflight_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary --timing --Wno-fatal \
    --top-module apf_savestate_v2_restore_preflight_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_savestate_v2_restore_preflight_tb \
    "$ROOT/src/fpga/core/apf_savestate_v2_layout_pkg.sv" \
    "$ROOT/src/fpga/core/apf_savestate_v2_device_abi_pkg.sv" \
    "$ROOT/src/fpga/core/apf_crc64_ecma32.sv" \
    "$ROOT/src/fpga/core/apf_savestate_v2_restore_preflight.sv" \
    "$ROOT/src/fpga/core/apf_savestate_v2_owner.sv" \
    "$ROOT/sim/rtl/apf_savestate_v2_restore_preflight_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_savestate_v2_restore_preflight_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
grep -q '^PASS APF savestate v2 structural/integrity/profile/device preflight ' \
  <<<"$output"
