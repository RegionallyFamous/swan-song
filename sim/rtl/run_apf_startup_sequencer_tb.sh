#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build/rtl/apf-startup-sequencer"

rm -rf "$BUILD"
mkdir -p "$BUILD"
verilator --binary --timing --Wno-fatal --Wno-TIMESCALEMOD \
  --top-module apf_startup_sequencer_tb \
  --Mdir "$BUILD/obj_dir" \
  "$ROOT/src/fpga/core/apf_startup_sequencer.sv" \
  "$ROOT/sim/rtl/apf_startup_sequencer_tb.sv"
"$BUILD/obj_dir/Vapf_startup_sequencer_tb"
