#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/gpu_vtotal_timing_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. \
    /work/src/fpga/core/rtl/registerpackage.vhd \
    /work/src/fpga/core/rtl/reg_swan.vhd \
    /work/src/fpga/core/rtl/bus_savestates.vhd \
    /work/src/fpga/core/rtl/reg_savestates.vhd \
    /work/src/fpga/core/rtl/gpu_bg.vhd \
    /work/src/fpga/core/rtl/sprites.vhd \
    /work/src/fpga/core/rtl/gpu.vhd \
    /work/sim/rtl/gpu_vtotal_timing_tb.vhd

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o gpu_vtotal_timing_tb gpu_vtotal_timing_tb

set +e
output="$(docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./gpu_vtotal_timing_tb --assert-level=error 2>&1)"
status=$?
set -e
printf '%s\n' "$output"
if (( status != 0 )); then
  exit "$status"
fi
grep -q 'gpu_vtotal_timing_tb.vhd:.*PASS GPU live programmable final line' <<<"$output"
