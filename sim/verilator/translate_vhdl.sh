#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build/sim/ghdl"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"

mkdir -p "$BUILD"
rm -f "$BUILD"/*.cf "$BUILD/swantop.v"

# GHDL synthesis requires the constrained actual/formal integer subtypes to
# match exactly. Quartus accepts the upstream unconstrained declaration.
sed 's/savestate_number    : in    integer;/savestate_number    : in    integer range 0 to 3;/' \
  "$ROOT/src/fpga/core/rtl/statemanager.vhd" > "$BUILD/statemanager.vhd"

files=(
  src/fpga/core/rtl/export.vhd
  sim/rtl/dpram_sim.vhd
  src/fpga/core/rtl/registerpackage.vhd
  src/fpga/core/rtl/reg_swan.vhd
  src/fpga/core/rtl/bus_savestates.vhd
  src/fpga/core/rtl/reg_savestates.vhd
  build/sim/ghdl/statemanager.vhd
  src/fpga/core/rtl/savestates.vhd
  src/fpga/core/rtl/swanbios.vhd
  src/fpga/core/rtl/swanbioscolor.vhd
  src/fpga/core/rtl/dummyregs.vhd
  src/fpga/core/rtl/sound_module1.vhd
  src/fpga/core/rtl/sound_module2.vhd
  src/fpga/core/rtl/sound_module3.vhd
  src/fpga/core/rtl/sound_module4.vhd
  src/fpga/core/rtl/sound_module5.vhd
  src/fpga/core/rtl/sound.vhd
  src/fpga/core/rtl/joypad.vhd
  src/fpga/core/rtl/gpu_bg.vhd
  src/fpga/core/rtl/sprites.vhd
  src/fpga/core/rtl/gpu.vhd
  src/fpga/core/rtl/divider.vhd
  src/fpga/core/rtl/cpu.vhd
  src/fpga/core/rtl/dma.vhd
  src/fpga/core/rtl/eeprom.vhd
  src/fpga/core/rtl/memorymux.vhd
  src/fpga/core/rtl/IRQ.vhd
  src/fpga/core/rtl/rtc.vhd
  src/fpga/core/rtl/swanTop.vhd
)

docker_args=(--rm --platform linux/amd64 -v "$ROOT:/work" -w /work)

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=/work/build/sim/ghdl "${files[@]}"

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=/work/build/sim/ghdl \
    --out=verilog "-gis_simu='1'" SwanTop > "$BUILD/swantop.v"

# `packed` is a legal VHDL identifier used by the upstream GPU, but a reserved
# SystemVerilog word understood by Verilator even for a .v input.
perl -pi -e 's/\bpacked\b/packed_i/g' "$BUILD/swantop.v"

echo "Generated $BUILD/swantop.v"
