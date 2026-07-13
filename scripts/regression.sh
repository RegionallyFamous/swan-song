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
"${CXX:-c++}" -std=c++17 -Wall -Wextra -Werror \
  -I"$ROOT/sim/verilator" \
  "$ROOT/sim/verilator/input_script_test.cpp" \
  -o "$BUILD/input_script_test"
"$BUILD/input_script_test"
echo "PASS deterministic controller input-script parser"
python3 "$ROOT/sim/verilator/verify_trace_test.py"
python3 "$ROOT/sim/verilator/correlate_provenance_test.py"
python3 "$ROOT/sim/verilator/correlate_bg_cells_test.py"
python3 "$ROOT/sim/verilator/correlate_sprite_rows_test.py"
python3 "$ROOT/sim/verilator/verify_cpu_rep_movsb_test.py"
python3 "$ROOT/sim/verilator/report_glyphs_test.py"
python3 "$ROOT/sim/verilator/generate_4bpp_probe_test.py"
python3 "$ROOT/sim/verilator/generate_color_sprite_priority_probe_test.py"
python3 "$ROOT/sim/verilator/verify_mapper_memory_probe_test.py"
python3 "$ROOT/sim/verilator/verify_boot_overlay_probe_test.py"
python3 "$ROOT/sim/verilator/verify_sdma_probe_test.py"
python3 "$ROOT/sim/verilator/verify_input_script_manifest_test.py"
python3 "$ROOT/sim/verilator/verify_frame_manifest_test.py"
python3 "$ROOT/sim/verilator/verify_input_replay_probe_test.py"
python3 "$ROOT/sim/verilator/verify_80186_quirks_test.py"
python3 "$ROOT/sim/verilator/verify_cpu_quirks_probe_test.py"
python3 "$ROOT/src/fpga/apf/build_id_gen_test.py"
python3 "$ROOT/scripts/package_core_test.py"

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

# Prove that cycle-addressed controller replay crosses the real keypad matrix.
# The generated mono ROM selects B5's horizontal row, waits for physical X2,
# emits the exact bank-register marker "IN", waits for release, then emits
# "P". Without a script the same ROM completes a frame but cannot emit any
# marker. Two routed runs must be byte-identical, and their success manifests
# bind both the raw script and its normalized full-state schedule.
INPUT_OUT="$BUILD/input-replay-probe"
rm -rf "$INPUT_OUT"
python3 "$ROOT/sim/verilator/generate_input_replay_probe.py" \
  "$INPUT_OUT/fixture" >/dev/null
"$SIM" \
  --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
  --frames 1 --max-cycles 1000000 \
  --out "$INPUT_OUT/no-input/frames" \
  --event-trace "$INPUT_OUT/no-input/events.csv" \
  --trace-events bank >/dev/null
for replay_run in a b; do
  "$SIM" \
    --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
    --input-script "$INPUT_OUT/fixture/input_replay_probe.input" \
    --frames 1 --max-cycles 1000000 \
    --out "$INPUT_OUT/run-$replay_run/frames" \
    --event-trace "$INPUT_OUT/run-$replay_run/events.csv" \
    --trace-events bank >/dev/null
done
python3 "$ROOT/sim/verilator/verify_input_replay_probe.py" \
  --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
  --script "$INPUT_OUT/fixture/input_replay_probe.input" \
  --no-input-trace "$INPUT_OUT/no-input/events.csv" \
  --trace-a "$INPUT_OUT/run-a/events.csv" \
  --frame-a "$INPUT_OUT/run-a/frames/frame-0.rgb" \
  --trace-b "$INPUT_OUT/run-b/events.csv" \
  --frame-b "$INPUT_OUT/run-b/frames/frame-0.rgb"
python3 "$ROOT/sim/verilator/verify_input_script_manifest.py" \
  "$INPUT_OUT/run-a/events.csv" \
  "$INPUT_OUT/fixture/input_replay_probe.input"
python3 "$ROOT/sim/verilator/verify_input_script_manifest.py" \
  "$INPUT_OUT/run-b/events.csv" \
  "$INPUT_OUT/fixture/input_replay_probe.input"

# The opt-in manifest v2 binds each raw RGB artifact to the exact trace cycle
# containing its final visible-pixel write. Two repeated captures must report
# identical publication cycles, and the option must not alter trace/frame bytes
# relative to the otherwise identical legacy manifest-v1 capture above.
for frame_run in a b; do
  "$SIM" \
    --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
    --input-script "$INPUT_OUT/fixture/input_replay_probe.input" \
    --frames 1 --max-cycles 1000000 \
    --out "$INPUT_OUT/frame-bound-$frame_run/frames" \
    --event-trace "$INPUT_OUT/frame-bound-$frame_run/events.csv" \
    --trace-frame-artifacts --trace-events bank >/dev/null
done
FRAME_BOUND_A="$(python3 "$ROOT/sim/verilator/verify_frame_manifest.py" \
  "$INPUT_OUT/frame-bound-a/events.csv")"
FRAME_BOUND_B="$(python3 "$ROOT/sim/verilator/verify_frame_manifest.py" \
  "$INPUT_OUT/frame-bound-b/events.csv")"
test "$FRAME_BOUND_A" = "$FRAME_BOUND_B"
echo "$FRAME_BOUND_A"
cmp "$INPUT_OUT/run-a/events.csv" "$INPUT_OUT/frame-bound-a/events.csv"
cmp "$INPUT_OUT/run-a/frames/frame-0.rgb" \
  "$INPUT_OUT/frame-bound-a/frames/frame-0.rgb"
python3 "$ROOT/sim/verilator/verify_input_script_manifest.py" \
  "$INPUT_OUT/frame-bound-a/events.csv" \
  "$INPUT_OUT/fixture/input_replay_probe.input"

# Repeat the same legacy/bound comparison with sprite_row selected so the
# conditional v6 event schema is locked independently of v5.
"$SIM" \
  --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
  --input-script "$INPUT_OUT/fixture/input_replay_probe.input" \
  --frames 2 --max-cycles 1500000 \
  --out "$INPUT_OUT/legacy-v6/frames" \
  --event-trace "$INPUT_OUT/legacy-v6/events.csv" \
  --trace-events bank,sprite_row >/dev/null
mkdir -p "$INPUT_OUT/frame-bound-v6/frames"
touch "$INPUT_OUT/frame-bound-v6/frames/frame-0.rgb"
ln "$INPUT_OUT/frame-bound-v6/frames/frame-0.rgb" \
  "$INPUT_OUT/frame-bound-v6/frames/frame-1.rgb"
"$SIM" \
  --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
  --input-script "$INPUT_OUT/fixture/input_replay_probe.input" \
  --frames 2 --max-cycles 1500000 \
  --out "$INPUT_OUT/frame-bound-v6/frames" \
  --event-trace "$INPUT_OUT/frame-bound-v6/events.csv" \
  --trace-frame-artifacts --trace-events bank,sprite_row >/dev/null
python3 "$ROOT/sim/verilator/verify_frame_manifest.py" \
  "$INPUT_OUT/frame-bound-v6/events.csv"
cmp "$INPUT_OUT/legacy-v6/events.csv" \
  "$INPUT_OUT/frame-bound-v6/events.csv"
cmp "$INPUT_OUT/legacy-v6/frames/frame-0.rgb" \
  "$INPUT_OUT/frame-bound-v6/frames/frame-0.rgb"
cmp "$INPUT_OUT/legacy-v6/frames/frame-1.rgb" \
  "$INPUT_OUT/frame-bound-v6/frames/frame-1.rgb"
if [[ "$INPUT_OUT/frame-bound-v6/frames/frame-0.rgb" \
      -ef "$INPUT_OUT/frame-bound-v6/frames/frame-1.rgb" ]]; then
  echo "atomic frame publication retained a hardlink alias" >&2
  exit 1
fi

COLLISION_OUT="$INPUT_OUT/trace-frame-collision"
if ( "$SIM" \
  --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
  --frames 1 --max-cycles 1000000 \
  --out "$COLLISION_OUT" \
  --event-trace "$COLLISION_OUT/frame-0.rgb" \
  --trace-frame-artifacts --trace-events bank ) >/dev/null 2>&1; then
  echo "event trace at a raw frame path unexpectedly ran" >&2
  exit 1
fi
test ! -e "$COLLISION_OUT/frame-0.rgb.manifest.json"

VCD_COLLISION_OUT="$INPUT_OUT/vcd-frame-collision"
mkdir -p "$VCD_COLLISION_OUT"
ln -s frame-0.rgb "$VCD_COLLISION_OUT/capture.vcd"
if ( "$SIM" \
  --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
  --frames 1 --max-cycles 1000000 \
  --out "$VCD_COLLISION_OUT" \
  --trace "$VCD_COLLISION_OUT/capture.vcd" \
  --event-trace "$VCD_COLLISION_OUT/events.csv" \
  --trace-frame-artifacts --trace-events bank ) >/dev/null 2>&1; then
  echo "symlinked VCD at a raw frame path unexpectedly ran" >&2
  exit 1
fi
test ! -e "$VCD_COLLISION_OUT/events.csv.manifest.json"

if ( "$SIM" \
  --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
  --frames 1 --trace-frame-artifacts ) >/dev/null 2>&1; then
  echo "frame artifacts without an event trace unexpectedly ran" >&2
  exit 1
fi
echo "PASS frame-bound trace bytes preserve legacy v5 output"

# A final event at --max-cycles can never be applied because simulation runs
# [0,max-cycles). Reject it before simulation and invalidate the prior success
# certificate for a reused trace path.
test -f "$INPUT_OUT/run-a/events.csv.manifest.json"
if "$SIM" \
  --rom "$INPUT_OUT/fixture/input_replay_probe.ws" \
  --input-script "$INPUT_OUT/fixture/input_replay_probe.input" \
  --frames 1 --max-cycles 5000 \
  --out "$INPUT_OUT/impossible-frames" \
  --event-trace "$INPUT_OUT/run-a/events.csv" \
  --trace-events bank >/dev/null 2>&1; then
  echo "input script ending at max-cycles unexpectedly ran" >&2
  exit 1
fi
test ! -e "$INPUT_OUT/run-a/events.csv.manifest.json"
echo "PASS impossible input schedule invalidates prior trace certificate"

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

# Exercise both documented WonderSwan Color 4bpp tile encodings with
# repository-authored, build-generated cartridges that are never checked in.
# The ROM payloads differ at the byte level but decode to the same asymmetric
# 15-color tile. Four placements cover normal, horizontal, vertical, and
# combined flips; the paired verifier
# binds both exact GDMA chains through atomic rows, glyph reports, and pixels.
BPP4_OUT="$BUILD/4bpp-probe"
rm -rf "$BPP4_OUT"
python3 "$ROOT/sim/verilator/generate_4bpp_probe.py" \
  --output-dir "$BPP4_OUT/roms" >/dev/null
for variant in planar packed; do
  BPP4_VARIANT_OUT="$BPP4_OUT/$variant"
  "$SIM" \
    --rom "$BPP4_OUT/roms/wsc_4bpp_${variant}_probe.wsc" \
    --frames 2 --max-cycles 4000000 --out "$BPP4_VARIANT_OUT/frames" \
    --event-trace "$BPP4_VARIANT_OUT/events.csv" \
    --trace-events mem,vram,bg_cell >/dev/null
  python3 "$ROOT/sim/verilator/verify_trace.py" \
    "$BPP4_VARIANT_OUT/events.csv" \
    --allowed mem,vram,bg_cell --require mem,vram,bg_cell \
    --require-fetch-values --reject-fetch-collisions \
    --require-mem-initiators cpu,gdma \
    --require-origin-statuses exact,unattributed,not_applicable
  python3 "$ROOT/sim/verilator/correlate_provenance.py" \
    "$BPP4_VARIANT_OUT/events.csv" \
    --output "$BPP4_VARIANT_OUT/provenance.csv" \
    --fail-on-mismatch --require-complete-coverage --require-exact-fetches \
    --expect-count fetches=25669 --expect-count match=25669 \
    --expect-count collision=0 --expect-count cpu_exact=8493 \
    --expect-count initial_powerup=17048 --expect-count gdma_rom=128 \
    --expect-count cpu_rom_movsb=0 \
    --expect-count cpu_rom_movsb_bytes=0 \
    --expect-count cpu_rom_movsb_origins=0
  BPP4_BG_SUMMARY="$(python3 "$ROOT/sim/verilator/correlate_bg_cells.py" \
    "$BPP4_VARIANT_OUT/events.csv" \
    --output "$BPP4_VARIANT_OUT/bg-cells.csv" \
    --require-complete-coverage)"
  echo "$BPP4_BG_SUMMARY"
  require_bg_layers "$BPP4_BG_SUMMARY" screen1
  require_bg_counts "$BPP4_BG_SUMMARY" \
    cells=8493 screen1=8493 screen2=0 bpp2=0 bpp4=8493 \
    raw_superseded=60 raw_unpromoted=2 raw_inflight=0 \
    cpu_rom_movsb_cells=0 cpu_rom_movsb_bytes=0 \
    cpu_rom_movsb_origins=0
  python3 "$ROOT/sim/verilator/report_glyphs.py" \
    "$BPP4_VARIANT_OUT/bg-cells.csv" \
    --csv "$BPP4_VARIANT_OUT/glyph-epochs.csv" \
    --png "$BPP4_VARIANT_OUT/glyph-contact.png" \
    --columns 4 --contact-mode unique-exact
done
python3 "$ROOT/sim/verilator/verify_4bpp_probe.py" --root "$BPP4_OUT"
python3 "$ROOT/sim/verilator/verify_4bpp_probe_test.py" --root "$BPP4_OUT"

# Prove the Color compositor does not let an earlier low-priority sprite that
# is hidden by opaque Screen 2 suppress a later high-priority sprite. Three
# adjacent controls independently lock low/high Screen 2 priority and normal
# sprite-list order. The build-only ROM and every diagnostic tile are authored
# here; its full trace binds the descriptor words and ROM-to-IRAM GDMA chain.
COLOR_SPRITE_OUT="$BUILD/color-sprite-priority-probe"
rm -rf "$COLOR_SPRITE_OUT"
python3 "$ROOT/sim/verilator/generate_color_sprite_priority_probe.py" \
  --output-dir "$COLOR_SPRITE_OUT/roms" >/dev/null
"$SIM" \
  --rom "$COLOR_SPRITE_OUT/roms/wsc_color_sprite_priority_probe.wsc" \
  --frames 2 --max-cycles 1500000 --out "$COLOR_SPRITE_OUT/frames" \
  --event-trace "$COLOR_SPRITE_OUT/events.csv" \
  --trace-events mem,vram,sprite_row >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$COLOR_SPRITE_OUT/events.csv" \
  --allowed mem,vram,sprite_row --require mem,vram,sprite_row \
  --require-fetch-values --reject-fetch-collisions \
  --require-mem-initiators cpu,gdma \
  --require-origin-statuses exact,unattributed,not_applicable
python3 "$ROOT/sim/verilator/verify_color_sprite_priority_probe.py" \
  --root "$COLOR_SPRITE_OUT"
python3 "$ROOT/sim/verilator/correlate_sprite_rows.py" \
  "$COLOR_SPRITE_OUT/events.csv" \
  --output "$COLOR_SPRITE_OUT/sprite-rows.csv" \
  --require-complete-coverage \
  --expect-count sprite_rows=48 --expect-count bpp2=0 \
  --expect-count bpp4=48 --expect-count planar=0 \
  --expect-count packed=48 --expect-count raw_table_groups=12 \
  --expect-count raw_table_unused=6 --expect-count raw_tile_groups=48 \
  --expect-count raw_tile_unpromoted=0 \
  --expect-count raw_table_inflight=0 --expect-count raw_tile_inflight=0 \
  --expect-count descriptor_collision=0 --expect-count row_collision=0 \
  --expect-count descriptor_cpu_exact=48 --expect-count row_cpu_exact=0 \
  --expect-count row_gdma=48 --expect-count row_source_gdma_rom=48
python3 "$ROOT/sim/verilator/verify_color_sprite_priority_probe_test.py" \
  --root "$COLOR_SPRITE_OUT"

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

# Generate a self-contained CPU probe to cover the flag and exception details
# outside the upstream fixture: AL-derived AAM flags, AAD's full byte-ADD flags,
# AAM base-zero INT0 return state, and SALC's full before/after PUSHF plus AH
# preservation with no data-memory transaction. The ROM is build-only authored
# machine code.
CPU_QUIRKS_OUT="$BUILD/cpu-quirks-probe"
rm -rf "$CPU_QUIRKS_OUT"
python3 "$ROOT/sim/verilator/generate_cpu_quirks_probe.py" "$CPU_QUIRKS_OUT" >/dev/null
"$SIM" --rom "$CPU_QUIRKS_OUT/cpu_quirks_probe.ws" \
  --frames 1 --max-cycles 1000000 --out "$CPU_QUIRKS_OUT/frames" \
  --event-trace "$CPU_QUIRKS_OUT/events.csv" --trace-events cpu,mem >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$CPU_QUIRKS_OUT/events.csv" --allowed cpu,mem --require cpu,mem \
  --require-mem-initiators cpu --require-origin-statuses exact,unattributed
python3 "$ROOT/sim/verilator/verify_cpu_quirks_probe.py" \
  "$CPU_QUIRKS_OUT/cpu_quirks_probe.ws" "$CPU_QUIRKS_OUT/events.csv"

# Exercise the V30MZ's 80186-compatible AAM/AAD immediate-base behavior and
# undocumented SALC opcode with the pinned open ws-test-suite ROM. Two complete
# CPU/background captures must agree byte for byte, end in the fixture's idle
# loop, promote the PASS tile for all three tests, and render the exact frame.
QUIRKS_FIXTURE="$ROOT/testroms/ws-test-suite/80186_quirks"
QUIRKS_OUT="$BUILD/80186-quirks"
rm -rf "$QUIRKS_OUT"
for quirks_run in a b; do
  "$SIM" --rom "$QUIRKS_FIXTURE/80186_quirks.ws" \
    --frames 2 --max-cycles 4000000 \
    --out "$QUIRKS_OUT/$quirks_run/frames" \
    --event-trace "$QUIRKS_OUT/$quirks_run/events.csv" \
    --trace-events cpu,bg_cell >/dev/null
done
python3 "$ROOT/sim/verilator/verify_80186_quirks.py" \
  --fixture "$QUIRKS_FIXTURE" \
  --trace-a "$QUIRKS_OUT/a/events.csv" \
  --frame0-a "$QUIRKS_OUT/a/frames/frame-0.rgb" \
  --frame1-a "$QUIRKS_OUT/a/frames/frame-1.rgb" \
  --trace-b "$QUIRKS_OUT/b/events.csv" \
  --frame0-b "$QUIRKS_OUT/b/frames/frame-0.rgb" \
  --frame1-b "$QUIRKS_OUT/b/frames/frame-1.rgb"

# Wonderful's open WSC fixture distinguishes the valid 2bpp Color extended
# screen/tile/sprite ranges from their 16-KiB aliases. Verify the visible PASS
# fields and exact fetch semantics, then independently reconstruct every word.
EXT_ROM="$ROOT/testroms/ws-test-suite/tile_screen_extended_range/tile_screen_extended_range.wsc"
EXT_OUT="$BUILD/tile-screen-extended-range"
rm -rf "$EXT_OUT"
"$SIM" --rom "$EXT_ROM" --frames 2 --max-cycles 4000000 --out "$EXT_OUT" \
  --event-trace "$EXT_OUT/events.csv" \
  --trace-events mem,vram,bg_cell,sprite_row >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$EXT_OUT/events.csv" --allowed mem,vram,bg_cell,sprite_row \
  --require mem,vram,bg_cell,sprite_row \
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
python3 "$ROOT/sim/verilator/correlate_sprite_rows.py" \
  "$EXT_OUT/events.csv" --output "$EXT_OUT/sprite-rows.csv" \
  --require-complete-coverage \
  --expect-count sprite_rows=32 --expect-count bpp2=32 \
  --expect-count bpp4=0 --expect-count planar=32 \
  --expect-count packed=0 --expect-count raw_table_groups=8 \
  --expect-count raw_table_unused=4 --expect-count raw_tile_groups=32 \
  --expect-count raw_tile_unpromoted=0 \
  --expect-count raw_table_inflight=0 --expect-count raw_tile_inflight=0 \
  --expect-count descriptor_collision=0 --expect-count row_collision=0 \
  --expect-count descriptor_cpu_exact=32 --expect-count row_cpu_exact=32 \
  --expect-count row_gdma=0 --expect-count row_source_gdma_rom=0
python3 "$ROOT/sim/verilator/verify_extended_range.py" \
  "$EXT_ROM" "$EXT_OUT/events.csv" "$EXT_OUT/frame-1.rgb"
check_case tile-screen-extended-range \
  4a79f141e6f47dd902c67a77996ca83bb1b4684eae527109321491d93365e4a5 \
  "$EXT_OUT" 1

# The bootstrap run above is also the sprite-priority golden run, avoiding a
# duplicate six-frame simulation after rebuilding the model.
check_case spritepriority c7e9cd656f0e156aa34956492d2ed1b8a482e72d71c2d3caf73c77b3604538fd "$BUILD/bootstrap"
run_case windowtest c51c7a7681dd3d80667bfa2c5c236932c227d49036e0ae59a9fe6e39a12cf680
