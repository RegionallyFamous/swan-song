#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WONDERFUL_TOOLCHAIN="${WONDERFUL_TOOLCHAIN:-/opt/wonderful}"
FIXTURE="$ROOT/testroms/swan-song/wonderwitch_athena_hello"
ARTIFACTS="$ROOT/build/wonderwitch-athena/fixture"
OUTPUT="$ROOT/build/sim/wonderwitch-athena"
SIM="${SWAN_SIM:-$ROOT/build/sim/obj_dir/VSwanTop}"
VERIFY="$ROOT/sim/verilator/verify_wonderwitch_athena_fixture.py"

if [[ ! -x "$WONDERFUL_TOOLCHAIN/bin/wf-pacman" ]]; then
  echo "Wonderful toolchain not found at $WONDERFUL_TOOLCHAIN" >&2
  exit 1
fi
if [[ ! -x "$SIM" ]]; then
  echo "Translated simulator not found at $SIM; run make regression first" >&2
  exit 1
fi

python3 "$VERIFY" "$FIXTURE" --toolchain "$WONDERFUL_TOOLCHAIN"
make -C "$FIXTURE" clean all WONDERFUL_TOOLCHAIN="$WONDERFUL_TOOLCHAIN"
python3 "$VERIFY" "$FIXTURE" \
  --fx "$ARTIFACTS/athena_hello.fx" \
  --rom "$ARTIFACTS/athena_hello.ws"

rm -rf "$OUTPUT"
"$SIM" \
  --rom "$ARTIFACTS/athena_hello.ws" \
  --frames 5 --max-cycles 6000000 --out "$OUTPUT" \
  --event-trace "$OUTPUT/events.csv" \
  --trace-events cpu,bg_cell \
  --trace-pc 0xdfe80-0xdffff \
  >/dev/null

python3 "$VERIFY" "$FIXTURE" \
  --fx "$ARTIFACTS/athena_hello.fx" \
  --rom "$ARTIFACTS/athena_hello.ws" \
  --trace "$OUTPUT/events.csv" \
  --frames "$OUTPUT/frame-0.rgb" "$OUTPUT/frame-1.rgb" \
    "$OUTPUT/frame-2.rgb" "$OUTPUT/frame-3.rgb" "$OUTPUT/frame-4.rgb"
