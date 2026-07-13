#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/eeprom_state_tb.XXXXXX")"
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
  /work/src/fpga/core/rtl/eeprom.vhd
  /work/sim/rtl/eeprom_state_tb.vhd
)

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. "${sources[@]}"

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o eeprom_state_tb eeprom_state_tb

docker run "${docker_args[@]}" "$IMAGE" \
  ./eeprom_state_tb --assert-level=error

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=. \
    --out=verilog eeprom_state_synth > "$BUILD/eeprom_state_synth.v"

test -s "$BUILD/eeprom_state_synth.v"
echo "PASS GHDL synthesized EEPROM exact-state wrapper"
