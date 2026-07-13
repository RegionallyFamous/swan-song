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
python3 "$ROOT/sim/verilator/verify_trace_test.py"
python3 "$ROOT/sim/verilator/correlate_provenance_test.py"
python3 "$ROOT/sim/verilator/correlate_bg_cells_test.py"
python3 "$ROOT/sim/verilator/verify_cpu_rep_movsb_test.py"
python3 "$ROOT/sim/verilator/report_glyphs_test.py"
python3 "$ROOT/sim/verilator/verify_mapper_memory_probe_test.py"
python3 "$ROOT/sim/verilator/verify_boot_overlay_probe_test.py"
python3 "$ROOT/sim/verilator/verify_sdma_probe_test.py"

require_bg_layers() {
  local summary="$1"
  shift
  if [[ ! "$summary" =~ cells=[1-9][0-9]* ]]; then
    echo "background-cell correlation produced no cells: $summary" >&2
    exit 1
  fi
  local layer
  for layer in "$@"; do
    if [[ ! "$summary" =~ ${layer}=[1-9][0-9]* ]]; then
      echo "background-cell correlation did not cover $layer: $summary" >&2
      exit 1
    fi
  done
}

require_bg_counts() {
  local summary="$1"
  shift
  local expected
  for expected in "$@"; do
    if [[ " $summary " != *" $expected "* ]]; then
      echo "background-cell correlation expected $expected: $summary" >&2
      exit 1
    fi
  done
}

# Always rebuild the VHDL translation and simulator. Otherwise a local source
# edit can be checked against a stale VSwanTop binary left in build/sim.
rm -rf "$BUILD/bootstrap"
"$ROOT/sim/verilator/run.sh" \
  --rom "$ROOT/testroms/spritepriority/spritepriority.ws" \
  --frames 6 --max-cycles 4000000 --out "$BUILD/bootstrap" \
  --event-trace "$BUILD/bootstrap/events.csv" \
  --trace-events cpu,vram,mem,bg_cell \
  --trace-pc 0xf0000-0xf0fff,0xff000-0xfffff \
  >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$BUILD/bootstrap/events.csv" \
  --allowed cpu,vram,mem,bg_cell --require cpu,vram,mem,bg_cell \
  --pc-range 0xf0000-0xf0fff,0xff000-0xfffff \
  --vram-role all --require-vram-roles all \
  --vram-address 0x0000-0xbfff \
  --require-fetch-values --require-mem-initiators cpu \
  --require-origin-statuses exact,unattributed
python3 "$ROOT/sim/verilator/verify_cpu_rep_movsb.py" \
  "$ROOT/testroms/spritepriority/spritepriority.ws" \
  "$BUILD/bootstrap/events.csv"
python3 "$ROOT/sim/verilator/correlate_provenance.py" \
  "$BUILD/bootstrap/events.csv" \
  --output "$BUILD/bootstrap/provenance.csv" \
  --fail-on-mismatch --require-complete-coverage --require-exact-fetches \
  --expect-count fetches=78940 --expect-count match=78940 \
  --expect-count collision=0 --expect-count cpu_exact=78750 \
  --expect-count initial_powerup=190 --expect-count gdma_rom=0 \
  --expect-count cpu_rom_movsb=52512 \
  --expect-count cpu_rom_movsb_bytes=4096 \
  --expect-count cpu_rom_movsb_origins=2
BOOTSTRAP_BG_SUMMARY="$(python3 "$ROOT/sim/verilator/correlate_bg_cells.py" \
  "$BUILD/bootstrap/events.csv" \
  --output "$BUILD/bootstrap/bg-cells.csv" \
  --require-complete-coverage)"
echo "$BOOTSTRAP_BG_SUMMARY"
require_bg_layers "$BOOTSTRAP_BG_SUMMARY" screen1 screen2
require_bg_counts "$BOOTSTRAP_BG_SUMMARY" \
  cells=26224 screen1=13112 screen2=13112 bpp2=26224 bpp4=0 \
  raw_superseded=60 raw_unpromoted=2 raw_inflight=0 \
  cpu_rom_movsb_cells=26222 cpu_rom_movsb_bytes=4096 \
  cpu_rom_movsb_origins=2

# Generate a build-only probe that writes each cartridge bank register. The
# open sprite-priority ROM supplies only its reset vector/header footer; see
# generate_bank_probe.py and UPSTREAMS.md for provenance.
python3 "$ROOT/sim/verilator/verify_bank_probe_test.py"
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
python3 "$ROOT/sim/verilator/verify_bank_probe.py" \
  "$BUILD/bank-probe/events.csv"

# Reusing a trace path for a failed capture must not leave the preceding
# success manifest beside a newly truncated trace.
test -f "$BUILD/bank-probe/events.csv.manifest.json"
if "$SIM" \
  --rom "$BUILD/bank-probe/bank_probe.ws" \
  --frames 1 --max-cycles 1 --out "$BUILD/bank-probe/failed-frames" \
  --event-trace "$BUILD/bank-probe/events.csv" \
  --trace-events bank >/dev/null 2>&1; then
  echo "one-cycle manifest invalidation probe unexpectedly completed" >&2
  exit 1
fi
test ! -e "$BUILD/bank-probe/events.csv.manifest.json"
if python3 "$ROOT/sim/verilator/correlate_provenance.py" \
  "$BUILD/bank-probe/events.csv" \
  --output "$BUILD/bank-probe/failed-provenance.csv" \
  --require-complete-coverage >/dev/null 2>&1; then
  echo "failed capture retained complete-coverage authority" >&2
  exit 1
fi
echo "PASS failed capture invalidates trace completeness manifest"

# Generate an open WSC probe that copies two known words from mapped ROM into
# IRAM. The exact completed GDMA read/write sequence proves resolved-offset and
# value capture without relying on a commercial game.
rm -rf "$BUILD/provenance-probe"
python3 "$ROOT/sim/verilator/generate_provenance_probe.py" \
  "$ROOT/testroms/spritepriority/spritepriority.ws" \
  "$BUILD/provenance-probe/probe.wsc" >/dev/null
"$SIM" \
  --rom "$BUILD/provenance-probe/probe.wsc" \
  --frames 1 --max-cycles 1000000 --out "$BUILD/provenance-probe/frames" \
  --event-trace "$BUILD/provenance-probe/events.csv" \
  --trace-events mem --trace-mem-initiator gdma >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$BUILD/provenance-probe/events.csv" \
  --allowed mem --require mem --mem-initiator gdma \
  --mem-origin not_applicable
python3 "$ROOT/sim/verilator/verify_provenance_probe.py" \
  "$BUILD/provenance-probe/events.csv"

# Prove the integrated WSC sound-DMA path and its trace filter with an open,
# self-contained four-byte ROM stream. At the fastest rate the four completed
# byte steps are 1536 trace clocks apart (128 CPU clocks at 12 trace clocks per
# CPU clock). The raw inherited DMA bus drives byte_enable=3 even though SDMA
# advances and consumes one addressed byte per transfer; the dedicated
# verifier locks both facts without conflating the bus mask with sample width.
SDMA_OUT="$BUILD/sdma-probe"
rm -rf "$SDMA_OUT"
python3 "$ROOT/sim/verilator/generate_sdma_probe.py" "$SDMA_OUT" >/dev/null
"$SIM" \
  --rom "$SDMA_OUT/sdma_probe.wsc" \
  --frames 1 --max-cycles 1000000 --out "$SDMA_OUT/frames" \
  --event-trace "$SDMA_OUT/events.csv" \
  --trace-events mem --trace-mem-initiator sdma >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$SDMA_OUT/events.csv" \
  --allowed mem --require mem --mem-initiator sdma \
  --require-mem-initiators sdma --require-origin-statuses not_applicable
python3 "$ROOT/sim/verilator/verify_sdma_probe.py" \
  "$SDMA_OUT/sdma_probe.wsc" "$SDMA_OUT/events.csv"

# Exercise every memory-space classification that can be reached with open,
# generated stimuli. The paired ROMs differ only in their unambiguous 128 KiB
# SRAM declaration; both use the same generated mono boot image and complete,
# unfiltered mem+bank capture. The dedicated verifier binds all three inputs,
# both traces, exact mapper origins, bank masks, lane masks, and resolved
# offsets without treating the core's absent-SRAM value as a hardware oracle.
MAPPER_OUT="$BUILD/mapper-memory-probe"
rm -rf "$MAPPER_OUT"
python3 "$ROOT/sim/verilator/generate_mapper_memory_probe.py" "$MAPPER_OUT" \
  >/dev/null
for variant in present absent; do
  "$SIM" \
    --rom "$MAPPER_OUT/mapper_memory_${variant}.ws" \
    --bios "$MAPPER_OUT/mapper_memory_boot.bin" \
    --frames 1 --max-cycles 1000000 \
    --out "$MAPPER_OUT/${variant}-frames" \
    --event-trace "$MAPPER_OUT/${variant}.csv" \
    --trace-events mem,bank >/dev/null
  python3 "$ROOT/sim/verilator/verify_trace.py" \
    "$MAPPER_OUT/${variant}.csv" \
    --allowed mem,bank --require mem,bank \
    --require-bank-addresses 0xc0,0xc1,0xc2,0xc3 \
    --require-mem-initiators cpu \
    --require-origin-statuses exact,unattributed
done
python3 "$ROOT/sim/verilator/verify_mapper_memory_probe.py" \
  "$MAPPER_OUT/mapper_memory_boot.bin" \
  "$MAPPER_OUT/mapper_memory_present.ws" "$MAPPER_OUT/present.csv" \
  "$MAPPER_OUT/mapper_memory_absent.ws" "$MAPPER_OUT/absent.csv"

# Independently cover both boot-ROM sizes. The open test images execute from
# byte zero, read a low-window marker, lock port A0, and prove that physical
# FFFF0-FFFFE then resolves to the generated cartridge footer. This also
# regression-locks the simulator's initial low-clock evaluation, which is
# required for BIOS bytes 0/1 to be programmed.
BOOT_OUT="$BUILD/boot-overlay-probe"
rm -rf "$BOOT_OUT"
python3 "$ROOT/sim/verilator/generate_boot_overlay_probe.py" "$BOOT_OUT" \
  >/dev/null
for model in mono color; do
  "$SIM" \
    --rom "$BOOT_OUT/boot_overlay_carrier.ws" \
    --bios "$BOOT_OUT/boot_overlay_${model}.bin" \
    --frames 1 --max-cycles 1000000 \
    --out "$BOOT_OUT/${model}-frames" \
    --event-trace "$BOOT_OUT/${model}.csv" \
    --trace-events mem >/dev/null
  python3 "$ROOT/sim/verilator/verify_trace.py" \
    "$BOOT_OUT/${model}.csv" \
    --allowed mem --require mem --require-mem-initiators cpu \
    --require-origin-statuses exact,unattributed
  python3 "$ROOT/sim/verilator/verify_boot_overlay_probe.py" \
    "$model" "$BOOT_OUT/${model}.csv" \
    "$BOOT_OUT/boot_overlay_carrier.ws" \
    "$BOOT_OUT/boot_overlay_${model}.bin"
done

# Run a native Wonderful-built Shift-JIS renderer over six licensed Misaki
# glyphs. This binds Japanese character identity to exact ROM offsets, GDMA
# tile writes, CPU map writes, promoted background rows, and final pixels.
SJIS_ROM="$ROOT/testroms/swan-song/sjis_glyph_provenance/sjis_glyph_provenance.wsc"
SJIS_OUT="$BUILD/sjis-glyph-provenance"
python3 "$ROOT/sim/verilator/verify_sjis_glyph_fixture_test.py"
rm -rf "$SJIS_OUT"
"$SIM" --rom "$SJIS_ROM" --frames 2 --max-cycles 4000000 --out "$SJIS_OUT" \
  --event-trace "$SJIS_OUT/events.csv" --trace-events mem,vram,bg_cell >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$SJIS_OUT/events.csv" --allowed mem,vram,bg_cell --require mem,vram,bg_cell \
  --require-fetch-values --reject-fetch-collisions \
  --require-mem-initiators cpu,gdma \
  --require-origin-statuses exact,unattributed,not_applicable
python3 "$ROOT/sim/verilator/correlate_provenance.py" \
  "$SJIS_OUT/events.csv" --output "$SJIS_OUT/provenance.csv" \
  --fail-on-mismatch --require-complete-coverage --require-exact-fetches \
  --expect-count fetches=25111 --expect-count match=25111 \
  --expect-count collision=0 --expect-count cpu_exact=24729 \
  --expect-count initial_powerup=190 --expect-count gdma_rom=192 \
  --expect-count cpu_rom_movsb=0 \
  --expect-count cpu_rom_movsb_bytes=0 \
  --expect-count cpu_rom_movsb_origins=0
SJIS_BG_SUMMARY="$(python3 "$ROOT/sim/verilator/correlate_bg_cells.py" \
  "$SJIS_OUT/events.csv" --output "$SJIS_OUT/bg-cells.csv" \
  --require-complete-coverage)"
echo "$SJIS_BG_SUMMARY"
require_bg_layers "$SJIS_BG_SUMMARY" screen1
require_bg_counts "$SJIS_BG_SUMMARY" \
  cells=8307 screen1=8307 screen2=0 bpp2=8307 bpp4=0 \
  raw_superseded=60 raw_unpromoted=2 raw_inflight=0 \
  cpu_rom_movsb_cells=0 cpu_rom_movsb_bytes=0 \
  cpu_rom_movsb_origins=0
python3 "$ROOT/sim/verilator/report_glyphs.py" \
  "$SJIS_OUT/bg-cells.csv" \
  --csv "$SJIS_OUT/glyph-epochs.csv" \
  --png "$SJIS_OUT/glyph-contact.png" \
  --columns 4 --contact-mode unique-exact
python3 "$ROOT/sim/verilator/verify_sjis_glyph_fixture.py" \
  "$SJIS_ROM" "$SJIS_OUT/events.csv" "$SJIS_OUT/frame-1.rgb" \
  --glyph-cells "$SJIS_OUT/bg-cells.csv" \
  --glyph-report "$SJIS_OUT/glyph-epochs.csv" \
  --glyph-contact "$SJIS_OUT/glyph-contact.png"

check_case() {
  local name="$1" expected="$2" output="$3" frame="${4:-5}"
  python3 "$ROOT/sim/verilator/rgb_to_png.py" "$output/frame-$frame.rgb" >/dev/null
  local actual
  actual="$(python3 - "$output/frame-$frame.png" <<'PY'
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

run_case() {
  local name="$1" expected="$2"
  local output="$BUILD/$name"
  rm -rf "$output"
  "$SIM" --rom "$ROOT/testroms/$name/$name.ws" --frames 6 \
    --max-cycles 4000000 --out "$output" >/dev/null
  check_case "$name" "$expected" "$output"
}

# Wonderful's open WSC fixture distinguishes the valid 2bpp Color extended
# screen/tile/sprite ranges from their 16-KiB aliases. Verify the visible PASS
# fields and exact fetch semantics, then independently reconstruct every word.
EXT_ROM="$ROOT/testroms/ws-test-suite/tile_screen_extended_range/tile_screen_extended_range.wsc"
EXT_OUT="$BUILD/tile-screen-extended-range"
rm -rf "$EXT_OUT"
"$SIM" --rom "$EXT_ROM" --frames 2 --max-cycles 4000000 --out "$EXT_OUT" \
  --event-trace "$EXT_OUT/events.csv" --trace-events mem,vram,bg_cell >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$EXT_OUT/events.csv" --allowed mem,vram,bg_cell --require mem,vram,bg_cell \
  --require-fetch-values --reject-fetch-collisions \
  --require-mem-initiators cpu --require-origin-statuses exact
python3 "$ROOT/sim/verilator/correlate_provenance.py" \
  "$EXT_OUT/events.csv" --output "$EXT_OUT/provenance.csv" \
  --fail-on-mismatch --require-complete-coverage --require-exact-fetches \
  --expect-count fetches=15794 --expect-count match=15794 \
  --expect-count collision=0 --expect-count cpu_exact=15608 \
  --expect-count initial_powerup=186 --expect-count gdma_rom=0 \
  --expect-count cpu_rom_movsb=0 \
  --expect-count cpu_rom_movsb_bytes=0 \
  --expect-count cpu_rom_movsb_origins=0
EXT_BG_SUMMARY="$(python3 "$ROOT/sim/verilator/correlate_bg_cells.py" \
  "$EXT_OUT/events.csv" --output "$EXT_OUT/bg-cells.csv" \
  --require-complete-coverage)"
echo "$EXT_BG_SUMMARY"
require_bg_layers "$EXT_BG_SUMMARY" screen1
require_bg_counts "$EXT_BG_SUMMARY" \
  cells=5176 screen1=5176 screen2=0 bpp2=5176 bpp4=0 \
  raw_superseded=60 raw_unpromoted=2 raw_inflight=0 \
  cpu_rom_movsb_cells=0 cpu_rom_movsb_bytes=0 \
  cpu_rom_movsb_origins=0
python3 "$ROOT/sim/verilator/verify_extended_range.py" \
  "$EXT_ROM" "$EXT_OUT/events.csv" "$EXT_OUT/frame-1.rgb"
check_case tile-screen-extended-range \
  4a79f141e6f47dd902c67a77996ca83bb1b4684eae527109321491d93365e4a5 \
  "$EXT_OUT" 1

# The bootstrap run above is also the sprite-priority golden run, avoiding a
# duplicate six-frame simulation after rebuilding the model.
check_case spritepriority c7e9cd656f0e156aa34956492d2ed1b8a482e72d71c2d3caf73c77b3604538fd "$BUILD/bootstrap"
run_case windowtest c51c7a7681dd3d80667bfa2c5c236932c227d49036e0ae59a9fe6e39a12cf680
