#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/sprites_startx_equivalence_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. \
    /work/src/fpga/core/rtl/sprites.vhd \
    /work/sim/rtl/sprites_startx_equivalence_tb.vhd

docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o sprites_startx_equivalence_tb sprites_startx_equivalence_tb

set +e
output="$(docker run --rm --platform linux/amd64 \
  -v "$ROOT:/work" -w "$BUILD_CONTAINER" "$IMAGE" \
  ./sprites_startx_equivalence_tb --assert-level=error 2>&1)"
status=$?
set -e
printf '%s\n' "$output"
if (( status != 0 )); then
  exit "$status"
fi
grep -q 'sprites_startx_equivalence_tb.vhd:.*PASS sprites startX offset 1/2 equivalence' <<<"$output"
