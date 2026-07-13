#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_dataslot_guard_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module apf_dataslot_guard_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_dataslot_guard_tb \
    "$ROOT/src/fpga/core/apf_dataslot_guard.sv" \
    "$ROOT/sim/rtl/apf_dataslot_guard_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_dataslot_guard_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS APF data-slot guard delayed results, bounds, capture, and reset$' <<<"$output"; then
  echo "missing APF data-slot guard PASS marker" >&2
  exit 1
fi
