#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/apf_crc64_ecma32_tb.XXXXXX")"
trap 'rm -rf "$BUILD"' EXIT

python3 "$ROOT/sim/rtl/generate_apf_crc64_ecma32_vectors.py" \
  "$BUILD/vectors.txt" >"$BUILD/generator.log"
cat "$BUILD/generator.log"
grep -q '^PASS CRC64 vector generation ' "$BUILD/generator.log"

if ! verilator \
    --binary --timing --Wno-fatal \
    --top-module apf_crc64_ecma32_tb \
    --Mdir "$BUILD/obj_dir" \
    -o apf_crc64_ecma32_tb \
    "$ROOT/src/fpga/core/apf_crc64_ecma32.sv" \
    "$ROOT/sim/rtl/apf_crc64_ecma32_tb.sv" \
    >"$BUILD/verilator.log" 2>&1; then
  cat "$BUILD/verilator.log" >&2
  exit 1
fi

if ! output="$("$BUILD/obj_dir/apf_crc64_ecma32_tb" \
    "+VECTORS=$BUILD/vectors.txt" 2>&1)"; then
  printf '%s\n' "$output" >&2
  exit 1
fi
printf '%s\n' "$output"
grep -q '^PASS APF CRC64 ECMA32 ' <<<"$output"
