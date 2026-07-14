#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
GPU_RTL_INPUT="${GPU_RTL:-src/fpga/core/rtl/gpu.vhd}"

if [[ "$GPU_RTL_INPUT" = /* ]]; then
  GPU_RTL_PATH="$(realpath "$GPU_RTL_INPUT")"
else
  GPU_RTL_PATH="$(realpath "$ROOT/$GPU_RTL_INPUT")"
fi
case "$GPU_RTL_PATH" in
  "$ROOT"/*) ;;
  *)
    echo "GPU_RTL must resolve inside $ROOT" >&2
    exit 2
    ;;
esac
GPU_RTL_CONTAINER="/work/${GPU_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/gpu_timer_irq_tb.XXXXXX")"
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
    "$GPU_RTL_CONTAINER" \
    /work/sim/rtl/gpu_timer_irq_tb.vhd

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o gpu_timer_irq_tb gpu_timer_irq_tb

set +e
output="$(docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./gpu_timer_irq_tb --assert-level=error 2>&1)"
status=$?
set -e
printf '%s\n' "$output"
if (( status != 0 )); then
  exit "$status"
fi
grep -q 'gpu_timer_irq_tb.vhd:.*PASS GPU timer IRQ disabled-countdown quirk and enabled modes' <<<"$output"
