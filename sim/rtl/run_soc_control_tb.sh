#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
SOC_CONTROL_RTL_INPUT="${SOC_CONTROL_RTL:-src/fpga/core/rtl/soc_control.vhd}"

if [[ "$SOC_CONTROL_RTL_INPUT" = /* ]]; then
  SOC_CONTROL_RTL_PATH="$(realpath "$SOC_CONTROL_RTL_INPUT")"
else
  SOC_CONTROL_RTL_PATH="$(realpath "$ROOT/$SOC_CONTROL_RTL_INPUT")"
fi
case "$SOC_CONTROL_RTL_PATH" in
  "$ROOT"/*) ;;
  *)
    echo "SOC_CONTROL_RTL must resolve inside $ROOT" >&2
    exit 2
    ;;
esac
SOC_CONTROL_RTL_CONTAINER="/work/${SOC_CONTROL_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/soc_control_tb.XXXXXX")"
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
    "$SOC_CONTROL_RTL_CONTAINER" \
    /work/sim/rtl/soc_control_tb.vhd

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o soc_control_tb soc_control_tb

set +e
output="$(docker run "${docker_args[@]}" "$IMAGE" \
  ./soc_control_tb --assert-level=error 2>&1)"
status=$?
set -e
printf '%s\n' "$output"
if (( status != 0 )); then
  exit "$status"
fi
grep -q 'soc_control_tb.vhd:.*PASS soc_control' <<<"$output"

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=. \
    --out=verilog soc_control > "$BUILD/soc_control.v"

test -s "$BUILD/soc_control.v"
echo "PASS GHDL synthesized soc_control"
