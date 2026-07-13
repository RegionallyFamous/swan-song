#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_savestate_sdram_writer_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary --timing --Wno-fatal \
    --top-module apf_savestate_sdram_writer_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_savestate_sdram_writer_tb \
    "$ROOT/src/fpga/core/apf_savestate_sdram_writer.sv" \
    "$ROOT/sim/rtl/apf_savestate_sdram_writer_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_savestate_sdram_writer_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
grep -q '^PASS APF savestate SDRAM writer ' <<<"$output"
