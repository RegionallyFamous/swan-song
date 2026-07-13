#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_sdram_channel1_mux_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

verilator \
  --binary \
  --timing \
  --assert \
  -Wall \
  -Wno-fatal \
  -Wno-PROCASSINIT \
  -Wno-UNUSEDSIGNAL \
  --top-module apf_sdram_channel1_mux_tb \
  -Mdir "$BUILD/obj_dir" \
  -o apf_sdram_channel1_mux_tb \
  "$ROOT/src/fpga/core/apf_sdram_channel1_mux.sv" \
  "$ROOT/sim/rtl/apf_sdram_channel1_mux_tb.sv"

output="$($BUILD/obj_dir/apf_sdram_channel1_mux_tb 2>&1)"
printf '%s\n' "$output"
grep -q '^PASS APF SDRAM channel1 mux ' <<<"$output"
