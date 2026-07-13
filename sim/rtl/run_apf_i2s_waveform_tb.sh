#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_i2s_waveform_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --Wno-PINMISSING \
    --top-module apf_i2s_waveform_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_i2s_waveform_tb \
    "$ROOT/src/fpga/core/sound_i2s.sv" \
    "$ROOT/sim/rtl/apf_i2s_waveform_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

run_seed() {
  local seed="$1"
  local output
  if ! output="$("$BUILD/obj_dir/apf_i2s_waveform_tb" "+verilator+seed+$seed" 2>&1)"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
  printf '%s\n' "$output"
  if ! grep -q '^PASS APF I2S ' <<<"$output"; then
    echo "missing APF I2S PASS marker for seed $seed" >&2
    return 1
  fi
}

run_seed 1
run_seed 987654
