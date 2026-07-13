#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/sim/regression"
SIM="$ROOT/build/sim/obj_dir/VSwanTop"

# Always rebuild the VHDL translation and simulator. Otherwise a local source
# edit can be checked against a stale VSwanTop binary left in build/sim.
rm -rf "$BUILD/bootstrap"
"$ROOT/sim/verilator/run.sh" \
  --rom "$ROOT/testroms/spritepriority/spritepriority.ws" \
  --frames 1 --max-cycles 4000000 --out "$BUILD/bootstrap" >/dev/null

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

run_case spritepriority 68795a02ed971aa598f556941cccae8b6545c99dacbf061d3d63e7d66eb88ee4
run_case windowtest b6378fe99bcc143c089643d9941170e8f8dd15039b4a0490379794ed16cebfc8
