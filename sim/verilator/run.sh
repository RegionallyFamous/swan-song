#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build/sim"

"$ROOT/sim/verilator/translate_vhdl.sh"

verilator --cc --exe --build --trace --top-module SwanTop \
  -CFLAGS -std=c++17 \
  -Wno-fatal -Wno-DECLFILENAME -Wno-PINCONNECTEMPTY -Wno-UNUSEDSIGNAL \
  -Wno-UNUSEDPARAM -Wno-CMPCONST -Wno-MULTIDRIVEN \
  --Mdir "$BUILD/obj_dir" \
  "$BUILD/ghdl/swantop.v" "$ROOT/sim/verilator/sim_main.cpp"

frames_file="$(mktemp "${TMPDIR:-/tmp}/swansong-frames.XXXXXX")"
trap 'rm -f "$frames_file"' EXIT

# tee preserves the simulator's normal path output while giving the converter a
# reliable input file. With pipefail, a simulation timeout remains a hard error.
"$BUILD/obj_dir/VSwanTop" "$@" | tee "$frames_file"

while IFS= read -r frame; do
  [[ "$frame" == *.rgb ]] || continue
  python3 "$ROOT/sim/verilator/rgb_to_png.py" "$frame"
done < "$frames_file"
