#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/sdram_cl3_capture_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator \
  --binary \
  --timing \
  --assert \
  -Wall \
  -Wno-fatal \
  -Wno-PROCASSINIT \
  -Wno-DECLFILENAME \
  -Wno-UNUSEDSIGNAL \
  -Wno-UNUSEDPARAM \
  -Wno-WIDTHTRUNC \
  --top-module sdram_cl3_capture_tb \
  -Mdir "$BUILD/obj_dir" \
  -o sdram_cl3_capture_tb \
  "$ROOT/sim/rtl/altddio_out_stub.sv" \
  "$ROOT/src/fpga/core/rtl/sdram.sv" \
  "$ROOT/sim/rtl/sdram_cl3_capture_tb.sv"

output="$($BUILD/obj_dir/sdram_cl3_capture_tb 2>&1)"
printf '%s\n' "$output"
grep -q '^PASS SDRAM CL3 capture/latency/reset channels=3 latency=5$' <<<"$output"
