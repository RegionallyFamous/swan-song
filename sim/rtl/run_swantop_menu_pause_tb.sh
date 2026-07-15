#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

"$ROOT/sim/verilator/translate_vhdl.sh"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/swantop_menu_pause_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

if ! verilator \
    --binary \
    --timing \
    --x-initial unique \
    --Wno-fatal \
    --top-module swantop_menu_pause_tb \
    --Mdir "$BUILD/obj_dir" \
    -o swantop_menu_pause_tb \
    "$ROOT/build/sim/ghdl/swantop.v" \
    "$ROOT/sim/rtl/swantop_menu_pause_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

passes=0
for fastforward in 0 1; do
  for ram_phase_ps in 0 833 1666 2499; do
    if ! output="$(
      "$BUILD/obj_dir/swantop_menu_pause_tb" \
        "+fastforward=$fastforward" \
        "+ram_phase_ps=$ram_phase_ps" 2>&1
    )"; then
      printf '%s\n' "$output" >&2
      exit 1
    fi
    printf '%s\n' "$output"
    if ! grep -q '^PASS real SwanTop pause external transactions exactly once ' <<<"$output"; then
      echo "missing real SwanTop menu-pause PASS marker" >&2
      exit 1
    fi
    passes=$((passes + 1))
  done
done

if [[ "$passes" -ne 8 ]]; then
  echo "expected 8 SwanTop pause phase/mode cases, got $passes" >&2
  exit 1
fi
