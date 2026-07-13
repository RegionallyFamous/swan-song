#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_savestate_staging_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
     --binary \
     --timing --Wno-fatal \
     --top-module apf_savestate_staging_tb \
     --Mdir "$BUILD/obj_dir" \
     -o apf_savestate_staging_tb \
     "$ROOT/src/fpga/core/apf_savestate_envelope.sv" \
     "$ROOT/src/fpga/core/apf_savestate_staging.sv" \
     "$ROOT/sim/rtl/apf_savestate_staging_tb.sv" \
     >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

output="$("$BUILD/obj_dir/apf_savestate_staging_tb" 2>&1)"
printf '%s\n' "$output"
grep -q '^PASS APF savestate staging ' <<<"$output"
