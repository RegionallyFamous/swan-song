#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_host_notify_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --Wno-PINMISSING \
    --top-module apf_host_notify_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_host_notify_tb \
    "$ROOT/src/fpga/core/core_bridge_cmd.v" \
    "$ROOT/sim/rtl/apf_host_notify_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

"$BUILD/obj_dir/apf_host_notify_tb"
