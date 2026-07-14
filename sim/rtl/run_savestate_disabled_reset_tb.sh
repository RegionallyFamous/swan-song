#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/savestate_disabled_reset_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker_args=(
  --rm
  --platform linux/amd64
  -v "$ROOT:/work"
  -w "$BUILD_CONTAINER"
)

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. \
    /work/src/fpga/core/rtl/bus_savestates.vhd \
    /work/src/fpga/core/rtl/savestates.vhd \
    /work/sim/rtl/savestate_disabled_reset_tb.vhd

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o savestate_disabled_reset_tb savestate_disabled_reset_tb

docker run "${docker_args[@]}" "$IMAGE" \
  ./savestate_disabled_reset_tb --assert-level=error
