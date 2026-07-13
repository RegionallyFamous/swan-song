#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_video_bus_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --top-module apf_video_bus_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_video_bus_tb \
    "$ROOT/src/fpga/core/apf_grayscale_video.sv" \
    "$ROOT/src/fpga/core/apf_video_bus.sv" \
    "$ROOT/sim/rtl/apf_video_bus_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

output="$("$BUILD/obj_dir/apf_video_bus_tb" 2>&1)"
printf '%s\n' "$output"
if ! grep -q '^PASS APF video bus ' <<<"$output"; then
  echo "missing APF video bus PASS marker" >&2
  exit 1
fi
