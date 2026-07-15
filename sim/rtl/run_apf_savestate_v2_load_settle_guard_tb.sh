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

BUILD="$(mktemp -d "$ROOT/build/sim/apf_savestate_v2_load_settle_guard.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! command -v verilator >/dev/null 2>&1; then
  echo "ERROR: verilator is required" >&2
  exit 1
fi

verilator \
  --binary \
  --timing \
  --top-module apf_savestate_v2_load_settle_guard_tb \
  -Wno-fatal \
  --Mdir "$BUILD/obj_dir" \
  -o apf_savestate_v2_load_settle_guard_tb \
  "$ROOT/src/fpga/core/apf_savestate_v2_load_settle_guard.sv" \
  "$ROOT/src/fpga/core/apf_savestate_v2_owner.sv" \
  "$ROOT/sim/rtl/apf_savestate_v2_load_settle_guard_tb.sv" \
  >/dev/null

"$BUILD/obj_dir/apf_savestate_v2_load_settle_guard_tb"

if [[ "$REQUIRE_YOSYS" == 1 ]]; then
  if ! command -v yosys >/dev/null 2>&1; then
    echo "ERROR: SWAN_REQUIRE_YOSYS=1 but yosys is unavailable" >&2
    exit 1
  fi
  yosys -q -p \
    "read_verilog -sv $ROOT/src/fpga/core/apf_savestate_v2_load_settle_guard.sv; \
     hierarchy -top apf_savestate_v2_load_settle_guard; \
     proc; opt; memory; opt; check; \
     write_json $BUILD/load_settle_guard_synth.json"
  test -s "$BUILD/load_settle_guard_synth.json"
  echo "PASS APF savestate v2 EEPROM settle guard synthesis"
else
  echo "SKIP APF savestate v2 EEPROM settle guard synthesis (set SWAN_REQUIRE_YOSYS=1)"
fi
