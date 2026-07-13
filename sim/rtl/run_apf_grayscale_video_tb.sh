#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_grayscale_video_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --top-module apf_grayscale_video_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_grayscale_video_tb \
    "$ROOT/src/fpga/core/apf_grayscale_video.sv" \
    "$ROOT/sim/rtl/apf_grayscale_video_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

"$BUILD/obj_dir/apf_grayscale_video_tb"
