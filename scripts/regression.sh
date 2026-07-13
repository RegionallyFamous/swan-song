#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/sim/regression"
SIM="$ROOT/build/sim/obj_dir/VSwanTop"

mkdir -p "$BUILD"
"${CXX:-c++}" -std=c++17 -Wall -Wextra -Werror \
  -I"$ROOT/sim/verilator" \
  "$ROOT/sim/verilator/trace_logger_test.cpp" \
  -o "$BUILD/trace_logger_test"
"$BUILD/trace_logger_test"
echo "PASS structured trace parser and writer"

# Always rebuild the VHDL translation and simulator. Otherwise a local source
# edit can be checked against a stale VSwanTop binary left in build/sim.
rm -rf "$BUILD/bootstrap"
"$ROOT/sim/verilator/run.sh" \
  --rom "$ROOT/testroms/spritepriority/spritepriority.ws" \
  --frames 1 --max-cycles 4000000 --out "$BUILD/bootstrap" \
  --event-trace "$BUILD/bootstrap/events.csv" \
  --trace-events cpu,vram --trace-pc 0xf0000-0xfffff >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$BUILD/bootstrap/events.csv" \
  --allowed cpu,vram --require cpu,vram --pc-range 0xf0000-0xfffff

# Generate a build-only probe that writes each cartridge bank register. The
# open sprite-priority ROM supplies only its reset vector/header footer; see
# generate_bank_probe.py and UPSTREAMS.md for provenance.
rm -rf "$BUILD/bank-probe"
python3 "$ROOT/sim/verilator/generate_bank_probe.py" \
  "$ROOT/testroms/spritepriority/spritepriority.ws" \
  "$BUILD/bank-probe/bank_probe.ws" >/dev/null
"$SIM" \
  --rom "$BUILD/bank-probe/bank_probe.ws" \
  --frames 1 --max-cycles 4000000 --out "$BUILD/bank-probe/frames" \
  --event-trace "$BUILD/bank-probe/events.csv" \
  --trace-events bank >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$BUILD/bank-probe/events.csv" \
  --allowed bank --require bank \
  --require-bank-addresses 0xc0,0xc1,0xc2,0xc3

run_case() {
  local name="$1" expected="$2"
  local output="$BUILD/$name"
  rm -rf "$output"
  "$SIM" --rom "$ROOT/testroms/$name/$name.ws" --frames 6 \
    --max-cycles 4000000 --out "$output" >/dev/null
  python3 "$ROOT/sim/verilator/rgb_to_png.py" "$output/frame-5.rgb" >/dev/null
  local actual
  actual="$(python3 - "$output/frame-5.png" <<'PY'
import hashlib
import pathlib
import struct
import sys

path = pathlib.Path(sys.argv[1])
png = path.read_bytes()
if png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
    raise SystemExit(f"{path}: invalid PNG header")
dimensions = struct.unpack(">II", png[16:24])
if dimensions != (224, 144):
    raise SystemExit(f"{path}: expected 224x144, got {dimensions[0]}x{dimensions[1]}")
print(hashlib.sha256(png).hexdigest())
PY
)"
  [[ "$actual" == "$expected" ]] || {
    echo "$name: expected $expected, got $actual" >&2
    exit 1
  }
  echo "PASS $name $actual"
}

run_case spritepriority c7e9cd656f0e156aa34956492d2ed1b8a482e72d71c2d3caf73c77b3604538fd
run_case windowtest c51c7a7681dd3d80667bfa2c5c236932c227d49036e0ae59a9fe6e39a12cf680
