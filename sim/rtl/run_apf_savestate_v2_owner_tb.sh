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

BUILD="$ROOT/build/sim/apf_savestate_v2_owner"

if ! command -v verilator >/dev/null 2>&1; then
  echo "ERROR: verilator is required" >&2
  exit 1
fi

rm -rf "$BUILD"
mkdir -p "$BUILD"

verilator \
  --binary \
  --timing \
  --top-module apf_savestate_v2_owner_tb \
  -Wno-fatal \
  --Mdir "$BUILD/obj_dir" \
  -o apf_savestate_v2_owner_tb \
  "$ROOT/src/fpga/core/apf_savestate_v2_owner.sv" \
  "$ROOT/sim/rtl/apf_savestate_v2_owner_tb.sv" \
  >/dev/null

"$BUILD/obj_dir/apf_savestate_v2_owner_tb"

# Keep synthesis opt-in so behavior regression is independent of an unpinned
# host Yosys. When explicitly requested, absence is a hard failure.
if [[ "$REQUIRE_YOSYS" == 1 ]]; then
  if ! command -v yosys >/dev/null 2>&1; then
    echo "ERROR: SWAN_REQUIRE_YOSYS=1 but yosys is unavailable" >&2
    exit 1
  fi
  yosys -q -p \
    "read_verilog -sv $ROOT/src/fpga/core/apf_savestate_v2_owner.sv; \
     hierarchy -top apf_savestate_v2_owner; \
     proc; opt; memory; opt; check; \
     write_json $BUILD/owner_synth.json"
  test -s "$BUILD/owner_synth.json"
  echo "PASS APF savestate v2 atomic owner synthesis"
else
  echo "SKIP APF savestate v2 atomic owner synthesis (set SWAN_REQUIRE_YOSYS=1)"
fi
