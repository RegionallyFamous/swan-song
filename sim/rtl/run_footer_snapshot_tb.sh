#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/footer_snapshot_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --Wno-MODDUP \
    --Wno-MODMISSING \
    --top-module footer_snapshot_tb \
    --Mdir "$BUILD/obj_dir" \
    -o footer_snapshot_tb \
    "$ROOT/src/fpga/core/wonderswan.sv" \
    "$ROOT/sim/rtl/footer_snapshot_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

phase_count=0
case_count=0
for phase_ps in 125 375 625 875 1125 1375 1625 1875 2125 2375 2625 2875; do
  if ! output="$("$BUILD/obj_dir/footer_snapshot_tb" \
      +sys_phase_ps="$phase_ps" 2>&1)"; then
    printf '%s\n' "$output" >&2
    exit 1
  fi
  printf '%s\n' "$output"
  if ! grep -q "^PASS footer snapshot phase=$phase_ps cases=36 .* system_type=reset_latched$" <<<"$output"; then
    echo "missing footer snapshot PASS marker for phase $phase_ps" >&2
    exit 1
  fi
  phase_count=$((phase_count + 1))
  case_count=$((case_count + 36))
done

echo "PASS footer snapshot phase sweep phases=$phase_count cases=$case_count ratio=3:1"
