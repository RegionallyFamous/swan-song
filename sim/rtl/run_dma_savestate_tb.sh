#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
DMA_RTL_INPUT="${DMA_RTL:-src/fpga/core/rtl/dma.vhd}"
REG_SAVESTATES_RTL_INPUT="${REG_SAVESTATES_RTL:-src/fpga/core/rtl/reg_savestates.vhd}"

in_root_path() {
  local label="$1"
  local input="$2"
  local path
  if [[ "$input" = /* ]]; then
    path="$(realpath "$input")"
  else
    path="$(realpath "$ROOT/$input")"
  fi
  case "$path" in
    "$ROOT"/*) printf '%s\n' "$path" ;;
    *)
      echo "$label must resolve inside $ROOT" >&2
      exit 2
      ;;
  esac
}

DMA_RTL_PATH="$(in_root_path DMA_RTL "$DMA_RTL_INPUT")"
REG_SAVESTATES_RTL_PATH="$(
  in_root_path REG_SAVESTATES_RTL "$REG_SAVESTATES_RTL_INPUT"
)"
DMA_RTL_CONTAINER="/work/${DMA_RTL_PATH#"$ROOT"/}"
REG_SAVESTATES_RTL_CONTAINER="/work/${REG_SAVESTATES_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/dma_savestate_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules \
    --workdir=. \
    /work/src/fpga/core/rtl/registerpackage.vhd \
    /work/src/fpga/core/rtl/reg_swan.vhd \
    /work/src/fpga/core/rtl/bus_savestates.vhd \
    "$REG_SAVESTATES_RTL_CONTAINER" \
    "$DMA_RTL_CONTAINER" \
    /work/sim/rtl/dma_savestate_tb.vhd

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o dma_savestate_tb dma_savestate_tb

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./dma_savestate_tb --assert-level=error
