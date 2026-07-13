#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
CPU_RTL_INPUT="${CPU_RTL:-src/fpga/core/rtl/cpu.vhd}"

if [[ "$CPU_RTL_INPUT" = /* ]]; then
  CPU_RTL_PATH="$(realpath "$CPU_RTL_INPUT")"
else
  CPU_RTL_PATH="$(realpath "$ROOT/$CPU_RTL_INPUT")"
fi
case "$CPU_RTL_PATH" in
  "$ROOT"/*) ;;
  *)
    echo "CPU_RTL must resolve inside $ROOT" >&2
    exit 2
    ;;
esac
CPU_RTL_CONTAINER="/work/${CPU_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/cpu_prefix_irq_shadow_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker_args=(
  --rm
  --platform linux/amd64
  -v "$ROOT:/work"
  -w "$BUILD_CONTAINER"
)

sources=(
  /work/src/fpga/core/rtl/export.vhd
  /work/src/fpga/core/rtl/registerpackage.vhd
  /work/src/fpga/core/rtl/bus_savestates.vhd
  /work/src/fpga/core/rtl/reg_savestates.vhd
  /work/src/fpga/core/rtl/divider.vhd
  "$CPU_RTL_CONTAINER"
  /work/sim/rtl/cpu_prefix_irq_shadow_tb.vhd
)

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. "${sources[@]}"

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o cpu_prefix_irq_shadow_tb cpu_prefix_irq_shadow_tb

docker run "${docker_args[@]}" "$IMAGE" \
  ./cpu_prefix_irq_shadow_tb --assert-level=error

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=. \
    --out=verilog cpu > "$BUILD/cpu.v"

test -s "$BUILD/cpu.v"
echo "PASS GHDL synthesized CPU after prefix/IRQ-shadow test"
