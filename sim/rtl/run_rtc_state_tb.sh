#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
RTC_RTL_INPUT="${RTC_RTL:-src/fpga/core/rtl/rtc.vhd}"

if [[ "$RTC_RTL_INPUT" = /* ]]; then
  RTC_RTL_PATH="$(realpath "$RTC_RTL_INPUT")"
else
  RTC_RTL_PATH="$(realpath "$ROOT/$RTC_RTL_INPUT")"
fi
case "$RTC_RTL_PATH" in
  "$ROOT"/*) ;;
  *)
    echo "RTC_RTL must resolve inside $ROOT" >&2
    exit 2
    ;;
esac
RTC_RTL_CONTAINER="/work/${RTC_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/rtc_state_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. \
    /work/src/fpga/core/rtl/registerpackage.vhd \
    /work/src/fpga/core/rtl/reg_swan.vhd \
    "$RTC_RTL_CONTAINER" \
    /work/sim/rtl/rtc_state_tb.vhd

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o rtc_state_tb rtc_state_tb

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./rtc_state_tb --assert-level=error

# Keep a synthesis check beside the behavioral contract.  This catches test-
# only constructs or state-vector logic that GHDL can simulate but not lower.
docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=. \
    --out=verilog rtc > "$BUILD/rtc_state_synth.v"

test -s "$BUILD/rtc_state_synth.v"
echo "PASS rtc_state_synth"
