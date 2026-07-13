#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build/rtl/pocket-save-init"

rm -rf "$BUILD"
mkdir -p "$BUILD"
verilator --binary --timing --Wno-fatal --Wno-TIMESCALEMOD \
  --top-module pocket_save_init_tb \
  --Mdir "$BUILD/obj_dir" \
  "$ROOT/src/fpga/core/pocket_save_init.sv" \
  "$ROOT/sim/rtl/pocket_save_init_tb.sv"
"$BUILD/obj_dir/Vpocket_save_init_tb"
