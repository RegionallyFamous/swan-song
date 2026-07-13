#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${GHDL_IMAGE:-ghdl/ghdl:6.0.0-llvm-ubuntu-24.04}"
CPU_RTL_INPUT="${CPU_RTL:-src/fpga/core/rtl/cpu.vhd}"
REG_SAVESTATES_RTL_INPUT="${REG_SAVESTATES_RTL:-src/fpga/core/rtl/reg_savestates.vhd}"

in_root_path() {
  local label="$1"
  local input="$2"
  local path
  if [[ "$input" = /* ]]; then
    path="$(realpath "$input")"
  else
    path="$(realpath "$ROOT/$input")"
  fi
  case "$path" in
    "$ROOT"/*) printf '%s\n' "$path" ;;
    *)
      echo "$label must resolve inside $ROOT" >&2
      exit 2
      ;;
  esac
}

CPU_RTL_PATH="$(in_root_path CPU_RTL "$CPU_RTL_INPUT")"
REG_SAVESTATES_RTL_PATH="$(
  in_root_path REG_SAVESTATES_RTL "$REG_SAVESTATES_RTL_INPUT"
)"
CPU_RTL_CONTAINER="/work/${CPU_RTL_PATH#"$ROOT"/}"
REG_SAVESTATES_RTL_CONTAINER="/work/${REG_SAVESTATES_RTL_PATH#"$ROOT"/}"

mkdir -p "$ROOT/build/sim"
BUILD="$(mktemp -d "$ROOT/build/sim/cpu_halt_savestate_tb.XXXXXX")"
BUILD_CONTAINER="/work/${BUILD#"$ROOT"/}"
trap 'rm -rf "$BUILD"' EXIT

docker_args=(
  --rm
  --platform linux/amd64
  -v "$ROOT:/work"
  -w "$BUILD_CONTAINER"
)

sources=(
  /work/src/fpga/core/rtl/export.vhd
  /work/src/fpga/core/rtl/registerpackage.vhd
  /work/src/fpga/core/rtl/bus_savestates.vhd
  "$REG_SAVESTATES_RTL_CONTAINER"
  /work/src/fpga/core/rtl/divider.vhd
  "$CPU_RTL_CONTAINER"
  /work/sim/rtl/cpu_halt_savestate_tb.vhd
)

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -a --std=08 -frelaxed-rules --workdir=. "${sources[@]}"

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl -e --std=08 -frelaxed-rules --workdir=. \
    -o cpu_halt_savestate_tb cpu_halt_savestate_tb

docker run "${docker_args[@]}" "$IMAGE" \
  ./cpu_halt_savestate_tb --assert-level=error

docker run "${docker_args[@]}" "$IMAGE" \
  ghdl synth --std=08 -frelaxed-rules --workdir=. \
    --out=verilog cpu > "$BUILD/cpu.v"

test -s "$BUILD/cpu.v"
echo "PASS GHDL synthesized CPU after HALT savestate test"
