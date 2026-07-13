#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_rom_loader_adapter_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

python3 "$ROOT/sim/verilator/generate_non_power_two_probe.py" \
  "$BUILD/compact.wsc" --memh "$BUILD/compact.memh" >/dev/null

if ! verilator \
    --binary \
    --timing \
    --Wno-fatal \
    --top-module apf_rom_loader_adapter_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_rom_loader_adapter_tb \
    "$ROOT/src/fpga/core/apf_sdram_channel1_mux.sv" \
    "$ROOT/src/fpga/core/apf_rom_loader_adapter.sv" \
    "$ROOT/sim/rtl/apf_rom_loader_adapter_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_rom_loader_adapter_tb" \
    +ROM="$BUILD/compact.memh" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
if ! grep -q '^PASS APF 896 KiB load, validation failure recovery, and direct bypass$' <<<"$output"; then
  echo "missing compact-ROM adapter PASS marker" >&2
  exit 1
fi
