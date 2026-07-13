#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REQUIRE_YOSYS="${SWAN_REQUIRE_YOSYS-0}"
case "$REQUIRE_YOSYS" in
  0|1) ;;
  *)
    echo "ERROR: SWAN_REQUIRE_YOSYS must be 0 or 1" >&2
    exit 2
    ;;
esac

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_savestate_v2_eeprom_walker_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

SOURCES=(
  "$ROOT/src/fpga/core/apf_savestate_v2_layout_pkg.sv"
  "$ROOT/src/fpga/core/apf_savestate_v2_eeprom_walker_pkg.sv"
  "$ROOT/src/fpga/core/apf_savestate_v2_eeprom_walker.sv"
)

if ! verilator \
    --binary --timing --Wno-fatal \
    --top-module apf_savestate_v2_eeprom_walker_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_savestate_v2_eeprom_walker_tb \
    "${SOURCES[@]}" \
    "$ROOT/sim/rtl/apf_savestate_v2_eeprom_walker_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_savestate_v2_eeprom_walker_tb" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
grep -q '^PASS APF savestate v2 EEPROM walker ' <<<"$output"

# Synthesis is an explicit local/CI gate. The immutable behavior-test image
# does not include Yosys, so ordinary regression must not silently depend on
# whichever unpinned host package happens to be installed.
if [[ "$REQUIRE_YOSYS" == 1 ]]; then
  if ! command -v yosys >/dev/null 2>&1; then
    echo "ERROR: SWAN_REQUIRE_YOSYS=1 but yosys is unavailable" >&2
    exit 1
  fi
  yosys -q -p \
    "read_verilog -sv $ROOT/src/fpga/core/apf_savestate_v2_eeprom_walker.sv; \
     hierarchy -top apf_savestate_v2_eeprom_walker; \
     proc; opt; memory; opt; check; \
     write_json $BUILD/eeprom_walker_synth.json"
  test -s "$BUILD/eeprom_walker_synth.json"
  echo "PASS APF savestate v2 EEPROM walker synthesis"
else
  echo "SKIP APF savestate v2 EEPROM walker synthesis (set SWAN_REQUIRE_YOSYS=1)"
fi
