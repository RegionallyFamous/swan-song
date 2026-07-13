#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_savestate_commands_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --Wno-PINMISSING \
    --top-module apf_savestate_commands_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_savestate_commands_tb \
    "$ROOT/src/fpga/core/core_bridge_cmd.v" \
    "$ROOT/sim/rtl/apf_savestate_commands_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

output="$("$BUILD/obj_dir/apf_savestate_commands_tb" 2>&1)"
printf '%s\n' "$output"
if ! grep -q '^PASS APF savestate ' <<<"$output"; then
  echo "missing APF savestate PASS marker" >&2
  exit 1
fi
