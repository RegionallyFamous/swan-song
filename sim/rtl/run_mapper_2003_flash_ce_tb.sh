#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/mapper_2003_flash_ce_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker_args=(
  --rm
  --platform linux/amd64
  -v "$ROOT:/work"
  -w "$BUILD_CONTAINER"
)

sources=(
  /work/sim/rtl/dpram_sim.vhd
  /work/src/fpga/core/rtl/registerpackage.vhd
  /work/src/fpga/core/rtl/bus_savestates.vhd
  /work/src/fpga/core/rtl/reg_savestates.vhd
  /work/src/fpga/core/rtl/reg_swan.vhd
  /work/src/fpga/core/rtl/swanbios.vhd
  /work/src/fpga/core/rtl/swanbioscolor.vhd
  /work/src/fpga/core/rtl/eeprom.vhd
  /work/src/fpga/core/rtl/memorymux.vhd
  /work/sim/rtl/mapper_2003_flash_ce_tb.vhd
)

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. "${sources[@]}"

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o mapper_2003_flash_ce_tb mapper_2003_flash_ce_tb

docker run "${docker_args[@]}" "$IMAGE" \
  ./mapper_2003_flash_ce_tb --assert-level=error

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=. \
    --out=verilog memorymux > "$BUILD/memorymux.v"

test -s "$BUILD/memorymux.v"
echo "PASS GHDL synthesized memorymux after CE routing test"
