#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
IRQ_RTL_INPUT="${IRQ_RTL:-src/fpga/core/rtl/IRQ.vhd}"

if [[ "$IRQ_RTL_INPUT" = /* ]]; then
  IRQ_RTL_PATH="$(realpath "$IRQ_RTL_INPUT")"
else
  IRQ_RTL_PATH="$(realpath "$ROOT/$IRQ_RTL_INPUT")"
fi
case "$IRQ_RTL_PATH" in
  "$ROOT"/*) ;;
  *)
    echo "IRQ_RTL must resolve inside $ROOT" >&2
    exit 2
    ;;
esac
IRQ_RTL_CONTAINER="/work/${IRQ_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/irq_controller_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker_args=(
  --rm
  --platform linux/amd64
  -v "$ROOT:/work"
  -w "$BUILD_CONTAINER"
)

sources=(
  /work/src/fpga/core/rtl/registerpackage.vhd
  /work/src/fpga/core/rtl/reg_swan.vhd
  /work/src/fpga/core/rtl/bus_savestates.vhd
  /work/src/fpga/core/rtl/reg_savestates.vhd
  "$IRQ_RTL_CONTAINER"
  /work/sim/rtl/irq_controller_tb.vhd
)

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. "${sources[@]}"

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o irq_controller_tb irq_controller_tb

set +e
output="$(docker run "${docker_args[@]}" "$IMAGE" \
  ./irq_controller_tb --assert-level=error 2>&1)"
status=$?
set -e
printf '%s\n' "$output"
if (( status != 0 )); then
  exit "$status"
fi
grep -q 'irq_controller_tb.vhd:.*PASS IRQ controller eight-source mapping, priority, persistence, W1C, and levels' <<<"$output"

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=. \
    --out=verilog IRQ > "$BUILD/irq.v"

test -s "$BUILD/irq.v"
echo "PASS GHDL synthesized IRQ controller"
