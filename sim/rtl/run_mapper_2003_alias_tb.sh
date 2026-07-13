#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/mapper_2003_alias_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules \
    --workdir=. \
    /work/sim/rtl/dpram_sim.vhd \
    /work/src/fpga/core/rtl/registerpackage.vhd \
    /work/src/fpga/core/rtl/bus_savestates.vhd \
    /work/src/fpga/core/rtl/reg_savestates.vhd \
    /work/src/fpga/core/rtl/reg_swan.vhd \
    /work/src/fpga/core/rtl/swanbios.vhd \
    /work/src/fpga/core/rtl/swanbioscolor.vhd \
    /work/src/fpga/core/rtl/eeprom.vhd \
    /work/src/fpga/core/rtl/memorymux.vhd \
    /work/sim/rtl/mapper_2003_alias_tb.vhd

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o mapper_2003_alias_tb mapper_2003_alias_tb

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./mapper_2003_alias_tb --assert-level=error
