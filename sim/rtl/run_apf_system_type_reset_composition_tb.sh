#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_system_type_reset_composition_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --Wno-MODMISSING \
    --Wno-PINMISSING \
    --top-module apf_system_type_reset_composition_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_system_type_reset_composition_tb \
    "$ROOT/src/fpga/core/core_bridge_cmd.v" \
    "$ROOT/src/fpga/core/apf_settings_cdc.sv" \
    "$ROOT/src/fpga/core/apf_reset_sync.sv" \
    "$ROOT/src/fpga/core/wonderswan.sv" \
    "$ROOT/sim/rtl/apf_system_type_reset_composition_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

phase_count=0
release_count=0
for phase_ps in 125 625 1125 1625 2125 2625 3125 3625 4125 4625 5125 5625 6125 6625; do
  if ! output="$("$BUILD/obj_dir/apf_system_type_reset_composition_tb" \
      +destination_phase_ps="$phase_ps" 2>&1)"; then
    printf '%s\n' "$output" >&2
    exit 1
  fi
  printf '%s\n' "$output"
  if ! grep -q "^PASS APF System Type reset composition phase=$phase_ps releases=3 scenarios=pre/same/waiting$" <<<"$output"; then
    echo "missing System Type composition PASS marker for phase $phase_ps" >&2
    exit 1
  fi
  phase_count=$((phase_count + 1))
  release_count=$((release_count + 3))
done

echo "PASS APF System Type reset composition phase_sweep=$phase_count releases=$release_count"
