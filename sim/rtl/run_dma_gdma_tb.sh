#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
DMA_RTL_INPUT="${DMA_RTL:-src/fpga/core/rtl/dma.vhd}"

if [[ "$DMA_RTL_INPUT" = /* ]]; then
  DMA_RTL_PATH="$(realpath "$DMA_RTL_INPUT")"
else
  DMA_RTL_PATH="$(realpath "$ROOT/$DMA_RTL_INPUT")"
fi
case "$DMA_RTL_PATH" in
  "$ROOT"/*) ;;
  *)
    echo "DMA_RTL must resolve inside $ROOT" >&2
    exit 2
    ;;
esac
DMA_RTL_CONTAINER="/work/${DMA_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/dma_gdma_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. \
    /work/src/fpga/core/rtl/registerpackage.vhd \
    /work/src/fpga/core/rtl/reg_swan.vhd \
    /work/src/fpga/core/rtl/bus_savestates.vhd \
    /work/src/fpga/core/rtl/reg_savestates.vhd \
    "$DMA_RTL_CONTAINER" \
    /work/sim/rtl/dma_gdma_tb.vhd

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o dma_gdma_tb dma_gdma_tb

set +e
output="$(docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./dma_gdma_tb --assert-level=error 2>&1)"
status=$?
set -e
printf '%s\n' "$output"
if (( status != 0 )); then
  exit "$status"
fi
grep -q 'dma_gdma_tb.vhd:.*PASS dma_gdma_tb' <<<"$output"

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=. \
    --out=verilog dma > "$BUILD/dma.v"

test -s "$BUILD/dma.v"
echo "PASS GHDL synthesized DMA"
