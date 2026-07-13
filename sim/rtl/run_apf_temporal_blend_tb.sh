#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_temporal_blend_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --top-module apf_temporal_blend_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_temporal_blend_tb \
    "$ROOT/src/fpga/core/apf_temporal_blend.sv" \
    "$ROOT/sim/rtl/apf_temporal_blend_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_temporal_blend_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS APF temporal blend ' <<<"$output"; then
  echo "missing APF temporal blend PASS marker" >&2
  exit 1
fi
