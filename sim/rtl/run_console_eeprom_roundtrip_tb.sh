#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
EEPROM_RTL_INPUT="${EEPROM_RTL:-src/fpga/core/rtl/eeprom.vhd}"

if [[ "$EEPROM_RTL_INPUT" = /* ]]; then
  EEPROM_RTL_PATH="$(realpath "$EEPROM_RTL_INPUT")"
else
  EEPROM_RTL_PATH="$(realpath "$ROOT/$EEPROM_RTL_INPUT")"
fi
case "$EEPROM_RTL_PATH" in
  "$ROOT"/*) ;;
  *)
    echo "EEPROM_RTL must resolve inside $ROOT" >&2
    exit 2
    ;;
esac
EEPROM_RTL_CONTAINER="/work/${EEPROM_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/console_eeprom_roundtrip_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules \
    --workdir=. \
    /work/sim/rtl/dpram_sim.vhd \
    /work/src/fpga/core/rtl/registerpackage.vhd \
    /work/src/fpga/core/rtl/bus_savestates.vhd \
    "$EEPROM_RTL_CONTAINER" \
    /work/sim/rtl/console_eeprom_roundtrip_tb.vhd \
    /work/sim/rtl/external_eeprom_backing_tb.vhd

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o console_eeprom_roundtrip_tb console_eeprom_roundtrip_tb

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./console_eeprom_roundtrip_tb --assert-level=error

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o external_eeprom_backing_tb external_eeprom_backing_tb

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./external_eeprom_backing_tb --assert-level=error
