#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_console_setup_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module apf_console_setup_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_console_setup_tb \
    "$ROOT/src/fpga/core/apf_console_setup.sv" \
    "$ROOT/sim/rtl/apf_console_setup_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

run_seed() {
  local seed="$1"
  local output
  if ! output="$("$BUILD/obj_dir/apf_console_setup_tb" "+verilator+seed+$seed" 2>&1)"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
  printf '%s\n' "$output"
  grep -q '^PASS APF Console Setup ' <<<"$output"
}

run_seed 1
run_seed 982451653
