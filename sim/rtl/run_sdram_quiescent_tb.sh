#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/sdram_quiescent_tb.XXXXXX")"
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
  --top-module sdram_quiescent_tb \
  -Mdir "$BUILD/obj_dir" \
  -o sdram_quiescent_tb \
  "$ROOT/sim/rtl/altddio_out_stub.sv" \
  "$ROOT/src/fpga/core/rtl/sdram.sv" \
  "$ROOT/sim/rtl/sdram_quiescent_tb.sv"

output="$($BUILD/obj_dir/sdram_quiescent_tb 2>&1)"
printf '%s\n' "$output"
grep -q '^PASS SDRAM quiescence init/read/write/refresh ' <<<"$output"
