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
"${CXX:-c++}" -std=c++17 -Wall -Wextra -Werror \
  -I"$ROOT/sim/verilator" \
  "$ROOT/sim/verilator/rom_image_test.cpp" \
  -o "$BUILD/rom_image_test"
python3 "$ROOT/sim/verilator/generate_non_power_two_probe.py" \
  "$BUILD/wsc_896k_compact_probe.wsc" >/dev/null
"$BUILD/rom_image_test" "$BUILD/wsc_896k_compact_probe.wsc"
echo "PASS compact-ROM host mapping and negative mutations"
python3 "$ROOT/scripts/with_native_macos_ghdl_test.py"
python3 "$ROOT/scripts/soc_control_contract_test.py"
python3 "$ROOT/scripts/soc_control_integration_test.py"
python3 "$ROOT/scripts/soc_video_mode_equivalence_test.py"
"$ROOT/sim/rtl/run_soc_control_tb.sh"
"$ROOT/sim/rtl/run_dma_pending_tb.sh"
"$ROOT/sim/rtl/run_dma_savestate_tb.sh"
"$ROOT/sim/rtl/run_cpu_halt_savestate_tb.sh"
"$ROOT/sim/rtl/run_savestate_disabled_reset_tb.sh"
"$ROOT/sim/rtl/run_memories_pause_tb.sh"
"$ROOT/sim/rtl/run_swantop_menu_pause_tb.sh"
"$ROOT/sim/rtl/run_cpu_prefix_irq_shadow_tb.sh"
"$ROOT/sim/rtl/run_irq_controller_tb.sh"
"$ROOT/sim/rtl/run_gpu_timer_irq_tb.sh"
"$ROOT/sim/rtl/run_dma_gdma_tb.sh"
python3 "$ROOT/scripts/gpu_final144_sprite_stream_model.py"
"$ROOT/sim/rtl/run_sprites_startx_equivalence_tb.sh"
"$ROOT/sim/rtl/run_gpu_sprite_dma_timing_tb.sh"
"$ROOT/sim/rtl/run_gpu_vtotal_timing_tb.sh"
"$ROOT/sim/rtl/run_cpu_rotate_tb.sh"
"$ROOT/sim/rtl/run_apf_crc64_ecma32_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_v2_layout_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_v2_device_abi_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_v2_eeprom_walker_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_v2_load_settle_guard_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_v2_owner_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_v2_restore_preflight_tb.sh"
"$ROOT/sim/rtl/run_rtc_state_tb.sh"
"$ROOT/sim/rtl/run_eeprom_state_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_sdram_writer_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_sdram_reader_tb.sh"
python3 "$ROOT/scripts/apf_a0_prefetch_service_model_test.py"
"$ROOT/sim/rtl/run_apf_savestate_envelope_tb.sh"
"$ROOT/sim/rtl/run_apf_host_notify_tb.sh"
"$ROOT/sim/rtl/run_apf_grayscale_video_tb.sh"
"$ROOT/sim/rtl/run_apf_video_bus_tb.sh"
"$ROOT/sim/rtl/run_apf_boot_lifecycle_tb.sh"
"$ROOT/sim/rtl/run_apf_settings_boot_barrier_tb.sh"
"$ROOT/sim/rtl/run_apf_system_type_reset_composition_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_commands_tb.sh"
"$ROOT/sim/rtl/run_apf_savestate_staging_tb.sh"
"$ROOT/sim/rtl/run_apf_i2s_waveform_tb.sh"
"$ROOT/sim/rtl/run_apf_rtc_cdc_tb.sh"
"$ROOT/sim/rtl/run_apf_rtc_save_loader_tb.sh"
"$ROOT/sim/rtl/run_apf_reset_sync_tb.sh"
"$ROOT/sim/rtl/run_apf_pll_boot_reset_tb.sh"
"$ROOT/sim/rtl/run_apf_gamepad_filter_tb.sh"
"$ROOT/sim/rtl/run_apf_input_blocked_cdc_tb.sh"
"$ROOT/sim/rtl/run_apf_menu_focus_cdc_tb.sh"
"$ROOT/sim/rtl/run_apf_menu_focus_pause_tb.sh"
"$ROOT/sim/rtl/run_apf_fast_forward_control_tb.sh"
"$ROOT/sim/rtl/run_apf_settings_cdc_tb.sh"
"$ROOT/sim/rtl/run_apf_interact_readback_tb.sh"
"$ROOT/sim/rtl/run_apf_control_layout_tb.sh"
"$ROOT/sim/rtl/run_apf_framebank_ram_tb.sh"
"$ROOT/sim/rtl/run_apf_framebank_arbiter_tb.sh"
"$ROOT/sim/rtl/run_apf_frame_orientation_tb.sh"
"$ROOT/sim/rtl/run_apf_orientation_transition_guard_tb.sh"
"$ROOT/sim/rtl/run_apf_orientation_delivery_e2e_tb.sh"
"$ROOT/sim/rtl/run_apf_beam_race_candidate_tb.sh"
"$ROOT/sim/rtl/run_apf_late_frame_candidate_tb.sh"
"$ROOT/sim/rtl/run_apf_scanout_cadence_tb.sh"
"$ROOT/sim/rtl/run_apf_scaler_selector_tb.sh"
"$ROOT/sim/rtl/run_apf_temporal_blend_tb.sh"
"$ROOT/sim/rtl/run_apf_dataslot_guard_tb.sh"
"$ROOT/sim/rtl/run_apf_rom_plan_cdc_tb.sh"
"$ROOT/sim/rtl/run_apf_rom_loader_adapter_tb.sh"
"$ROOT/sim/rtl/run_apf_sdram_channel1_mux_tb.sh"
"$ROOT/sim/rtl/run_sdram_cl3_capture_tb.sh"
"$ROOT/sim/rtl/run_sdram_quiescent_tb.sh"
python3 "$ROOT/scripts/memories_channel1_contract_test.py"
"$ROOT/sim/rtl/run_apf_save_metadata_cdc_tb.sh"
"$ROOT/sim/rtl/run_footer_snapshot_tb.sh"
"$ROOT/sim/rtl/run_apf_startup_sequencer_tb.sh"
"$ROOT/sim/rtl/run_internal_eeprom_tb.sh"
"$ROOT/sim/rtl/run_pocket_console_eeprom_init_tb.sh"
"$ROOT/sim/rtl/run_console_eeprom_roundtrip_tb.sh"
python3 "$ROOT/scripts/mapper_2003_gpo_contract_test.py"
"$ROOT/sim/rtl/run_mapper_2003_alias_tb.sh"
"$ROOT/sim/rtl/run_mapper_2003_flash_ce_tb.sh"
"$ROOT/sim/rtl/run_pocket_save_init_tb.sh"
python3 "$ROOT/sim/verilator/verify_trace_test.py"
python3 "$ROOT/sim/verilator/correlate_provenance_test.py"
python3 "$ROOT/sim/verilator/correlate_bg_cells_test.py"
python3 "$ROOT/sim/verilator/correlate_sprite_rows_test.py"
python3 "$ROOT/sim/verilator/verify_rep_movsb_probe_test.py"
python3 "$ROOT/sim/verilator/generate_window_boundary_probe_test.py"
python3 "$ROOT/sim/verilator/verify_window_boundary_probe_test.py"
python3 "$ROOT/sim/verilator/report_glyphs_test.py"
python3 "$ROOT/sim/verilator/generate_4bpp_probe_test.py"
python3 "$ROOT/sim/verilator/generate_non_power_two_probe_test.py"
python3 "$ROOT/sim/verilator/generate_provenance_probe_test.py"
python3 "$ROOT/sim/verilator/generate_sram_persistence_probes_test.py"
python3 "$ROOT/sim/verilator/verify_sram_persistence_save_test.py"
python3 "$ROOT/sim/verilator/generate_color_sprite_priority_probe_test.py"
python3 "$ROOT/sim/verilator/verify_mapper_memory_probe_test.py"
python3 "$ROOT/sim/verilator/verify_sram_32k_probe_test.py"
python3 "$ROOT/sim/verilator/sram_32k_apf_contract_test.py"
python3 "$ROOT/sim/verilator/verify_boot_overlay_probe_test.py"
python3 "$ROOT/sim/verilator/verify_sdma_probe_test.py"
python3 "$ROOT/sim/verilator/verify_sdma_modes_probe_test.py"
python3 "$ROOT/sim/verilator/verify_input_script_manifest_test.py"
python3 "$ROOT/sim/verilator/verify_frame_manifest_test.py"
python3 "$ROOT/sim/verilator/verify_input_replay_probe_test.py"
python3 "$ROOT/sim/verilator/verify_interrupt_input_probe_test.py"
python3 "$ROOT/sim/verilator/verify_80186_quirks_test.py"
python3 "$ROOT/sim/verilator/verify_interrupts_fixture_test.py"
python3 "$ROOT/sim/verilator/verify_sound_dma_fixture_test.py"
python3 "$ROOT/sim/verilator/verify_internal_eeprom_fixture_test.py"
python3 "$ROOT/sim/verilator/verify_cpu_quirks_probe_test.py"
python3 "$ROOT/sim/verilator/verify_wonderful_medium_sram_fixture_test.py"
python3 "$ROOT/sim/verilator/verify_wonderwitch_athena_fixture_test.py"
python3 "$ROOT/scripts/wonderwitch_sdk_contract_test.py"
python3 "$ROOT/scripts/migrate_type01_save_test.py"
python3 "$ROOT/scripts/migrate_legacy_eeprom_save_test.py"
python3 "$ROOT/scripts/migrate_swan_song_namespace_test.py"
python3 "$ROOT/scripts/migrate_cartridge_save_namespace_test.py"
python3 "$ROOT/scripts/pocket_per_game_preset_test.py"
python3 "$ROOT/scripts/swan_song_doctor_test.py"
python3 "$ROOT/scripts/wiki_publication_check_test.py"
python3 "$ROOT/scripts/wiki_sync_test.py"
python3 "$ROOT/scripts/prepare_launch_pr_test.py"
python3 "$ROOT/scripts/frame_delivery_metrics_test.py"
python3 "$ROOT/scripts/beam_race_safety_test.py"
python3 "$ROOT/scripts/late_frame_delivery_test.py"
python3 "$ROOT/scripts/pocket_synchronizer_attribute_contract_test.py"
python3 "$ROOT/scripts/dma_gdma_contract_test.py"
python3 "$ROOT/scripts/gpu_timer_irq_contract_test.py"
python3 "$ROOT/scripts/gpu_vtotal_contract_test.py"
python3 "$ROOT/scripts/pocket_pll_reset_contract_test.py"
python3 "$ROOT/scripts/pocket_first_class_contract_test.py"
python3 "$ROOT/scripts/pocket_launcher_library_contract_test.py"
python3 "$ROOT/scripts/pocket_save_metadata_constraint_test.py"
python3 "$ROOT/scripts/pocket_footer_snapshot_contract_test.py"
python3 "$ROOT/scripts/pocket_sdram_constraint_test.py"
python3 "$ROOT/scripts/pocket_apf_boundary_constraint_test.py"
python3 "$ROOT/scripts/pocket_control_cdc_contract_test.py"
python3 "$ROOT/scripts/pocket_control_layout_contract_test.py"
python3 "$ROOT/scripts/pocket_pad_contract_test.py"
python3 "$ROOT/scripts/pocket_console_setup_contract_test.py"
python3 "$ROOT/scripts/pocket_input_dock_contract_test.py"
python3 "$ROOT/scripts/pocket_menu_focus_contract_test.py"
python3 "$ROOT/scripts/build_chip32_pending_diagnostic_test.py"
python3 "$ROOT/scripts/prepare_hardware_qa_workspace_test.py"
python3 "$ROOT/scripts/pocket_hardware_qa_test.py"
python3 "$ROOT/scripts/pocket_hardware_qa_session_test.py"
python3 "$ROOT/scripts/known_title_compatibility_test.py"
python3 "$ROOT/scripts/prepare_known_title_qa_workspace_test.py"
python3 "$ROOT/scripts/import_private_corpus_test.py"
python3 "$ROOT/scripts/run_private_corpus_test.py"
python3 "$ROOT/scripts/pocket_settings_constraint_test.py"
python3 "$ROOT/scripts/pocket_video_contract_test.py"
python3 "$ROOT/scripts/pocket_savestate_contract_test.py"
python3 "$ROOT/scripts/pocket_nv_size_contract_test.py"
python3 "$ROOT/scripts/pocket_console_eeprom_contract_test.py"
python3 "$ROOT/scripts/pocket_rtc_integration_contract_test.py"
python3 "$ROOT/src/fpga/apf/build_id_gen_test.py"
python3 "$ROOT/scripts/quartus_archive_test.py"
python3 "$ROOT/scripts/verify_hosted_regression_test.py"
python3 "$ROOT/scripts/quartus_container_provenance_test.py"
python3 "$ROOT/scripts/build_core_test.py"
python3 "$ROOT/scripts/quartus_docker_contract_test.py"
python3 "$ROOT/scripts/quartus_evidence_test.py"
python3 "$ROOT/scripts/quartus_connectivity_policy_test.py"
python3 "$ROOT/scripts/quartus_connectivity_source_closure_test.py"
python3 "$ROOT/scripts/quartus_connectivity_policy_refresh_test.py"
python3 "$ROOT/scripts/quartus_connectivity_refresh_gate_test.py"
python3 "$ROOT/scripts/quartus_signoff_paths_test.py"
python3 "$ROOT/scripts/quartus_fit_audit_test.py"
python3 "$ROOT/scripts/swan_song_lab_test.py"
python3 "$ROOT/scripts/generate_core_icon_test.py"
python3 "$ROOT/scripts/generate_platform_art_test.py"
python3 "$ROOT/scripts/license_manifest_test.py"
python3 "$ROOT/scripts/package_core_test.py"
python3 "$ROOT/scripts/build_release_evidence_test.py"
python3 "$ROOT/scripts/assemble_stable_release_test.py"
python3 "$ROOT/scripts/stage_pocket_sd_test.py"

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
# edit can be checked against a stale VSwanTop binary left in build/sim. This
# generated clean-room ROM proves two independent 2 KiB REP MOVSB transfers
# and their exact instruction-attributed read/write histories.
REP_MOVSB_OUT="$BUILD/rep-movsb-probe"
rm -rf "$REP_MOVSB_OUT"
python3 "$ROOT/sim/verilator/generate_rep_movsb_probe.py" \
  "$REP_MOVSB_OUT/roms" >/dev/null
"$ROOT/sim/verilator/run.sh" \
  --rom "$REP_MOVSB_OUT/roms/rep_movsb_probe.ws" \
  --frames 1 --max-cycles 4000000 --out "$REP_MOVSB_OUT/frames" \
  --event-trace "$REP_MOVSB_OUT/events.csv" \
  --trace-events cpu,mem >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$REP_MOVSB_OUT/events.csv" \
  --allowed cpu,mem --require cpu,mem \
  --require-fetch-values --reject-fetch-collisions \
  --require-mem-initiators cpu \
  --require-origin-statuses exact,unattributed
python3 "$ROOT/sim/verilator/verify_rep_movsb_probe.py" \
  "$REP_MOVSB_OUT/roms/rep_movsb_probe.ws" \
  "$REP_MOVSB_OUT/events.csv"

# Carry exact cartridge SRAM across three separate translated-core processes
# for every 128/256/512 KiB footer geometry on mono and Color hardware. The
# open probes first initialize generation 1, then require 1->2 and 2->1
# persistence before publishing their headless IRAM success byte.
"$ROOT/sim/verilator/run_sram_persistence_e2e.sh"

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

# Exercise the corrected key interrupt path independently of the visual
# hardware fixture. The generated Color program uses an intentionally
# unaligned B0 base, dispatches through vector 81h, and emits one exact marker
# only after each disabled/held/repress/retention/ACK/combined-row assertion.
# Without routed input it can emit only the initial base-mask marker.
IRQ_INPUT_OUT="$BUILD/interrupt-input-probe"
rm -rf "$IRQ_INPUT_OUT"
python3 "$ROOT/sim/verilator/generate_interrupt_input_probe.py" \
  "$IRQ_INPUT_OUT/fixture" >/dev/null
"$SIM" \
  --rom "$IRQ_INPUT_OUT/fixture/interrupt_input_probe.wsc" \
  --frames 1 --max-cycles 1000000 \
  --out "$IRQ_INPUT_OUT/no-input/frames" \
  --event-trace "$IRQ_INPUT_OUT/no-input/events.csv" \
  --trace-events bank >/dev/null
for irq_input_run in a b; do
  "$SIM" \
    --rom "$IRQ_INPUT_OUT/fixture/interrupt_input_probe.wsc" \
    --input-script "$IRQ_INPUT_OUT/fixture/interrupt_input_probe.input" \
    --frames 1 --max-cycles 1000000 \
    --out "$IRQ_INPUT_OUT/run-$irq_input_run/frames" \
    --event-trace "$IRQ_INPUT_OUT/run-$irq_input_run/events.csv" \
    --trace-events bank >/dev/null
done
python3 "$ROOT/sim/verilator/verify_interrupt_input_probe.py" \
  --rom "$IRQ_INPUT_OUT/fixture/interrupt_input_probe.wsc" \
  --script "$IRQ_INPUT_OUT/fixture/interrupt_input_probe.input" \
  --no-input-trace "$IRQ_INPUT_OUT/no-input/events.csv" \
  --trace-a "$IRQ_INPUT_OUT/run-a/events.csv" \
  --frame-a "$IRQ_INPUT_OUT/run-a/frames/frame-0.rgb" \
  --trace-b "$IRQ_INPUT_OUT/run-b/events.csv" \
  --frame-b "$IRQ_INPUT_OUT/run-b/frames/frame-0.rgb"

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

# Generate a fully project-authored build-only probe that writes each
# cartridge bank register.
python3 "$ROOT/sim/verilator/verify_bank_probe_test.py"
rm -rf "$BUILD/bank-probe"
python3 "$ROOT/sim/verilator/generate_bank_probe.py" \
  "$BUILD/bank-probe/bank_probe.ws" >/dev/null
"$SIM" \
  --rom "$BUILD/bank-probe/bank_probe.ws" \
  --frames 1 --max-cycles 4000000 --out "$BUILD/bank-probe/frames" \
  --event-trace "$BUILD/bank-probe/events.csv" \
  --trace-events bank >/dev/null
python3 "$ROOT/sim/verilator/verify_trace.py" \
  "$BUILD/bank-probe/events.csv" \
  --allowed bank --require bank \
  --require-bank-addresses 0xc0,0xc1,0xc2,0xc3,0xce,0xcf,0xd0,0xd1,0xd2,0xd3,0xd4,0xd5
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

# Exercise the documented Sound-DMA counter/control modes with a self-checking
# open WSC program.  Success markers are emitted only after live register,
# pause/resume, zero-length, repeat-shadow, decrement, and held-zero checks.
# Two exact filtered captures bind those software assertions to every selected
# SDMA read.  Held reads are locked as the translated core's Mesen-aligned bus
# policy, not claimed as hardware behavior; physical bus-steal phase is open.
SDMA_MODES_OUT="$BUILD/sdma-modes-probe"
rm -rf "$SDMA_MODES_OUT"
python3 "$ROOT/sim/verilator/generate_sdma_modes_probe.py" \
  "$SDMA_MODES_OUT" >/dev/null
for run in a b; do
  "$SIM" \
    --rom "$SDMA_MODES_OUT/sdma_modes_probe.wsc" \
    --input-script "$SDMA_MODES_OUT/sdma_modes_probe.input" \
    --frames 1 --max-cycles 1000000 \
    --out "$SDMA_MODES_OUT/frames-$run" \
    --event-trace "$SDMA_MODES_OUT/events-$run.csv" \
    --trace-events mem,bank --trace-mem-initiator sdma >/dev/null
done
python3 "$ROOT/sim/verilator/verify_sdma_modes_probe.py" \
  --rom "$SDMA_MODES_OUT/sdma_modes_probe.wsc" \
  --script "$SDMA_MODES_OUT/sdma_modes_probe.input" \
  --trace-a "$SDMA_MODES_OUT/events-a.csv" \
  --trace-b "$SDMA_MODES_OUT/events-b.csv"

# Exercise every memory-space classification that can be reached with open,
# generated stimuli. The paired ROMs differ only in their unambiguous 128 KiB
# SRAM declaration; both boot through the built-in mono Open IPL and use
# complete, unfiltered mem+bank capture. The verifier binds both ROM inputs,
# both traces, exact mapper origins, bank masks, lane masks, and resolved
# offsets without treating the core's absent-SRAM value as a hardware oracle.
MAPPER_OUT="$BUILD/mapper-memory-probe"
rm -rf "$MAPPER_OUT"
python3 "$ROOT/sim/verilator/generate_mapper_memory_probe.py" "$MAPPER_OUT" \
  >/dev/null
for variant in present absent; do
  "$SIM" \
    --rom "$MAPPER_OUT/mapper_memory_${variant}.ws" \
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
  "$MAPPER_OUT/mapper_memory_present.ws" "$MAPPER_OUT/present.csv" \
  "$MAPPER_OUT/mapper_memory_absent.ws" "$MAPPER_OUT/absent.csv"

# Type 0x01 and type 0x02 both identify 32 KiB SRAM. Paired generated ROMs
# prove that 0000, 2000, and 7fff remain distinct, 8000 mirrors 0000, and the
# two header values produce byte-identical bus traces. The focused contract
# above independently locks the matching save-state and Pocket/APF sizes.
SRAM_32K_OUT="$BUILD/sram-32k-probe"
rm -rf "$SRAM_32K_OUT"
python3 "$ROOT/sim/verilator/generate_sram_32k_probe.py" \
  "$SRAM_32K_OUT" >/dev/null
for sram_type in 01 02; do
  "$SIM" \
    --rom "$SRAM_32K_OUT/sram_type${sram_type}_32k.ws" \
    --frames 1 --max-cycles 1000000 \
    --out "$SRAM_32K_OUT/type${sram_type}-frames" \
    --event-trace "$SRAM_32K_OUT/type${sram_type}.csv" \
    --trace-events mem --trace-mem-address 0x10000-0x18000 >/dev/null
  python3 "$ROOT/sim/verilator/verify_trace.py" \
    "$SRAM_32K_OUT/type${sram_type}.csv" \
    --allowed mem --require mem --mem-address 0x10000-0x18000 \
    --require-mem-initiators cpu --require-origin-statuses exact
done
python3 "$ROOT/sim/verilator/verify_sram_32k_probe.py" \
  "$SRAM_32K_OUT/sram_type01_32k.ws" "$SRAM_32K_OUT/type01.csv" \
  "$SRAM_32K_OUT/sram_type02_32k.ws" "$SRAM_32K_OUT/type02.csv"

# Independently cover all eight built-in Open IPL variants. Normal mono/color
# cartridge footers select every 8/16-bit and protected/writable-owner policy
# without any BIOS input. Complete trace provenance binds each reset-vector and
# sequential IPL startup fetch to open-bootstrap-v3, then proves that the RAM
# handoff locks port A0 and physical FFFF0-FFFFE resolves to the cartridge footer.
BOOT_OUT="$BUILD/boot-overlay-probe"
rm -rf "$BOOT_OUT"
python3 "$ROOT/sim/verilator/generate_boot_overlay_probe.py" "$BOOT_OUT" \
  >/dev/null
for variant in \
  mono-word8-owner-writable mono-word8-owner-protected \
  mono-word16-owner-writable mono-word16-owner-protected \
  color-word8-owner-writable color-word8-owner-protected \
  color-word16-owner-writable color-word16-owner-protected; do
  if [[ "$variant" == mono-* ]]; then
    extension=ws
  else
    extension=wsc
  fi
  if [[ "$variant" == "mono-word16-owner-protected" ]]; then
    BOOT_ROM="$BOOT_OUT/boot_overlay_mono.ws"
  elif [[ "$variant" == "color-word16-owner-protected" ]]; then
    BOOT_ROM="$BOOT_OUT/boot_overlay_color.wsc"
  else
    BOOT_ROM="$BOOT_OUT/boot_overlay_${variant//-/_}.${extension}"
  fi
  "$SIM" \
    --rom "$BOOT_ROM" \
    --frames 1 --max-cycles 1000000 \
    --out "$BOOT_OUT/${variant}-frames" \
    --event-trace "$BOOT_OUT/${variant}.csv" \
    --trace-events mem >/dev/null
  python3 "$ROOT/sim/verilator/verify_trace.py" \
    "$BOOT_OUT/${variant}.csv" \
    --allowed mem --require mem --require-mem-initiators cpu \
    --require-origin-statuses exact,unattributed
  python3 "$ROOT/sim/verilator/verify_boot_overlay_probe.py" \
    "$variant" "$BOOT_OUT/${variant}.csv" \
    "$BOOT_ROM"
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
    --expect-count fetches=26170 --expect-count match=26170 \
    --expect-count collision=0 --expect-count cpu_exact=8494 \
    --expect-count initial_powerup=17548 --expect-count gdma_rom=128 \
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
    cells=8494 screen1=8494 screen2=0 bpp2=0 bpp4=8494 \
    raw_superseded=60 raw_unpromoted=2 raw_inflight=0 raw_prefix_truncated=2 \
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

# Boot the same authored packed-4bpp payload from a 896 KiB compact image.
# The host mapper inserts the documented 128 KiB erased prefix and the exact
# frame identities prove that the translated core reaches the right-aligned
# reset vector and payload through its 1 MiB aperture.
COMPACT_ROM_OUT="$BUILD/compact-rom-probe"
rm -rf "$COMPACT_ROM_OUT"
python3 "$ROOT/sim/verilator/generate_non_power_two_probe.py" \
  "$COMPACT_ROM_OUT/wsc_896k_compact_probe.wsc" >/dev/null
"$SIM" \
  --rom "$COMPACT_ROM_OUT/wsc_896k_compact_probe.wsc" \
  --frames 2 --max-cycles 4000000 --out "$COMPACT_ROM_OUT/frames" \
  >/dev/null
python3 "$ROOT/sim/verilator/verify_non_power_two_probe.py" \
  "$COMPACT_ROM_OUT/wsc_896k_compact_probe.wsc" \
  "$COMPACT_ROM_OUT/frames"

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
  --expect-count packed=48 --expect-count raw_table_groups=250 \
  --expect-count raw_table_unused=244 --expect-count raw_tile_groups=48 \
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
  --expect-count fetches=25612 --expect-count match=25612 \
  --expect-count collision=0 --expect-count cpu_exact=24758 \
  --expect-count initial_powerup=662 --expect-count gdma_rom=192 \
  --expect-count cpu_rom_movsb=0 \
  --expect-count cpu_rom_movsb_bytes=0 \
  --expect-count cpu_rom_movsb_origins=0
SJIS_BG_SUMMARY="$(python3 "$ROOT/sim/verilator/correlate_bg_cells.py" \
  "$SJIS_OUT/events.csv" --output "$SJIS_OUT/bg-cells.csv" \
  --require-complete-coverage)"
echo "$SJIS_BG_SUMMARY"
require_bg_layers "$SJIS_BG_SUMMARY" screen1
require_bg_counts "$SJIS_BG_SUMMARY" \
  cells=8308 screen1=8308 screen2=0 bpp2=8308 bpp4=0 \
  raw_superseded=60 raw_unpromoted=2 raw_inflight=0 raw_prefix_truncated=2 \
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

# Validate Wonderful's current advanced C runtime path: medium-model far code
# plus a 32 KiB cartridge-SRAM data segment. The open Color fixture's CRT must
# initialize .bss/.data in SRAM, enter main through a far jump, survive exact
# mutation/readback checks, render the success string, and halt.
WONDERFUL_SRAM_FIXTURE="$ROOT/testroms/swan-song/wonderful_medium_sram"
WONDERFUL_SRAM_OUT="$BUILD/wonderful-medium-sram"
rm -rf "$WONDERFUL_SRAM_OUT"
"$SIM" \
  --rom "$WONDERFUL_SRAM_FIXTURE/medium_sram_probe.wsc" \
  --frames 2 --max-cycles 4000000 --out "$WONDERFUL_SRAM_OUT" \
  --event-trace "$WONDERFUL_SRAM_OUT/events.csv" \
  --trace-events cpu,mem,bg_cell \
  --trace-pc 0xfff20-0xfffa2,0xff130-0xff1b7 \
  --trace-mem-space cart_sram \
  --trace-mem-address 0x10012-0x10015 \
  >/dev/null
python3 "$ROOT/sim/verilator/verify_wonderful_medium_sram_fixture.py" \
  "$WONDERFUL_SRAM_FIXTURE" \
  "$WONDERFUL_SRAM_OUT/events.csv" \
  "$WONDERFUL_SRAM_OUT/frame-0.rgb" \
  "$WONDERFUL_SRAM_OUT/frame-1.rgb"

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

# Run the pinned real-hardware-authored SoC interrupt fixture twice. It checks
# eight UART-send-ready level cases and five vector/status cases, including
# acknowledgement, enable-mask retention, base alignment, and priority. The
# dedicated verifier binds the exact open source/ROM/font, all 13 PASS cells,
# the terminal loop, complete background history, and final pixels.
INTERRUPTS_FIXTURE="$ROOT/testroms/ws-test-suite/interrupts"
INTERRUPTS_OUT="$BUILD/interrupts-fixture"
rm -rf "$INTERRUPTS_OUT"
for interrupts_run in a b; do
  "$SIM" --rom "$INTERRUPTS_FIXTURE/interrupts.ws" \
    --frames 6 --max-cycles 4000000 \
    --out "$INTERRUPTS_OUT/$interrupts_run/frames" \
    --event-trace "$INTERRUPTS_OUT/$interrupts_run/events.csv" \
    --trace-events cpu,bg_cell >/dev/null
  cmp \
    "$INTERRUPTS_OUT/$interrupts_run/frames/frame-4.rgb" \
    "$INTERRUPTS_OUT/$interrupts_run/frames/frame-5.rgb"
done
python3 "$ROOT/sim/verilator/verify_interrupts_fixture.py" \
  --fixture "$INTERRUPTS_FIXTURE" \
  --trace-a "$INTERRUPTS_OUT/a/events.csv" \
  --frame0-a "$INTERRUPTS_OUT/a/frames/frame-0.rgb" \
  --final-a "$INTERRUPTS_OUT/a/frames/frame-5.rgb" \
  --trace-b "$INTERRUPTS_OUT/b/events.csv" \
  --frame0-b "$INTERRUPTS_OUT/b/frames/frame-0.rgb" \
  --final-b "$INTERRUPTS_OUT/b/frames/frame-5.rgb"

# Run the pinned open WSC Sound-DMA fixture twice. The dedicated verifier
# binds the exact source, ROM, manifest, 346 functional SDMA reads, all 22 PASS
# cells, terminal loop, and final pixels. In this Wonderful build the source's
# .sram symbol has segment zero, so its two SRAM-labeled phases are explicitly
# required to resolve to IRAM; this fixture makes no cartridge-SRAM claim.
SOUND_DMA_FIXTURE="$ROOT/testroms/ws-test-suite/sound_dma"
SOUND_DMA_OUT="$BUILD/sound-dma-fixture"
rm -rf "$SOUND_DMA_OUT"
for sound_dma_run in a b; do
  "$SIM" --rom "$SOUND_DMA_FIXTURE/sound_dma.wsc" \
    --frames 15 --max-cycles 8000000 \
    --out "$SOUND_DMA_OUT/$sound_dma_run/frames" \
    --event-trace "$SOUND_DMA_OUT/$sound_dma_run/events.csv" \
    --trace-events cpu,mem,bg_cell --trace-mem-initiator sdma >/dev/null
  cmp \
    "$SOUND_DMA_OUT/$sound_dma_run/frames/frame-13.rgb" \
    "$SOUND_DMA_OUT/$sound_dma_run/frames/frame-14.rgb"
done
python3 "$ROOT/sim/verilator/verify_sound_dma_fixture.py" \
  --fixture "$SOUND_DMA_FIXTURE" \
  --trace-a "$SOUND_DMA_OUT/a/events.csv" \
  --final-a "$SOUND_DMA_OUT/a/frames/frame-14.rgb" \
  --trace-b "$SOUND_DMA_OUT/b/events.csv" \
  --final-b "$SOUND_DMA_OUT/b/frames/frame-14.rgb"

# Run the pinned open mono internal-EEPROM fixture twice. The strict verifier
# binds the source, ROM, manifest, all 23 PASS cells, terminal loop, and final
# pixels. The exact capture length is part of the fixture contract so a timing
# or protocol regression cannot silently move beyond the accepted endpoint.
INTERNAL_EEPROM_FIXTURE="$ROOT/testroms/ws-test-suite/internal_eeprom"
INTERNAL_EEPROM_OUT="$BUILD/internal-eeprom-fixture"
rm -rf "$INTERNAL_EEPROM_OUT"
for internal_eeprom_run in a b; do
  "$SIM" --rom "$INTERNAL_EEPROM_FIXTURE/internal.ws" \
    --frames 6 --max-cycles 2887553 \
    --out "$INTERNAL_EEPROM_OUT/$internal_eeprom_run/frames" \
    --event-trace "$INTERNAL_EEPROM_OUT/$internal_eeprom_run/events.csv" \
    --trace-events cpu,bg_cell >/dev/null
done
python3 "$ROOT/sim/verilator/verify_internal_eeprom_fixture.py" \
  --fixture "$INTERNAL_EEPROM_FIXTURE" \
  --trace-a "$INTERNAL_EEPROM_OUT/a/events.csv" \
  --final-a "$INTERNAL_EEPROM_OUT/a/frames/frame-5.rgb" \
  --trace-b "$INTERNAL_EEPROM_OUT/b/events.csv" \
  --final-b "$INTERNAL_EEPROM_OUT/b/frames/frame-5.rgb"

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
  --expect-count fetches=16190 --expect-count match=16190 \
  --expect-count collision=0 --expect-count cpu_exact=15518 \
  --expect-count initial_powerup=672 --expect-count gdma_rom=0 \
  --expect-count cpu_rom_movsb=0 \
  --expect-count cpu_rom_movsb_bytes=0 \
  --expect-count cpu_rom_movsb_origins=0
EXT_BG_SUMMARY="$(python3 "$ROOT/sim/verilator/correlate_bg_cells.py" \
  "$EXT_OUT/events.csv" --output "$EXT_OUT/bg-cells.csv" \
  --require-complete-coverage)"
echo "$EXT_BG_SUMMARY"
require_bg_layers "$EXT_BG_SUMMARY" screen1
require_bg_counts "$EXT_BG_SUMMARY" \
  cells=5146 screen1=5146 screen2=0 bpp2=5146 bpp4=0 \
  raw_superseded=60 raw_unpromoted=2 raw_inflight=0 raw_prefix_truncated=2 \
  cpu_rom_movsb_cells=0 cpu_rom_movsb_bytes=0 \
  cpu_rom_movsb_origins=0
python3 "$ROOT/sim/verilator/correlate_sprite_rows.py" \
  "$EXT_OUT/events.csv" --output "$EXT_OUT/sprite-rows.csv" \
  --require-complete-coverage \
  --expect-count sprite_rows=32 --expect-count bpp2=32 \
  --expect-count bpp4=0 --expect-count planar=32 \
  --expect-count packed=0 --expect-count raw_table_groups=250 \
  --expect-count raw_table_unused=246 --expect-count raw_tile_groups=32 \
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

# Lock Screen 2's inclusive window edges plus sprite inside/outside selection
# with two fully project-authored Color ROMs and independent full-frame oracles.
WINDOW_OUT="$BUILD/window-boundary-probe"
rm -rf "$WINDOW_OUT"
python3 "$ROOT/sim/verilator/generate_window_boundary_probe.py" \
  --output-dir "$WINDOW_OUT/roms" >/dev/null
for window_variant in inside outside; do
  "$SIM" \
    --rom "$WINDOW_OUT/roms/wsc_window_${window_variant}_probe.wsc" \
    --frames 2 --max-cycles 1500000 \
    --out "$WINDOW_OUT/${window_variant}-frames" \
    --event-trace "$WINDOW_OUT/${window_variant}.csv" \
    --trace-events mem,vram,bg_cell >/dev/null
  python3 "$ROOT/sim/verilator/verify_trace.py" \
    "$WINDOW_OUT/${window_variant}.csv" \
    --allowed mem,vram,bg_cell --require mem,vram,bg_cell \
    --vram-role all --require-vram-roles all \
    --require-fetch-values --reject-fetch-collisions \
    --require-mem-initiators cpu,gdma \
    --require-origin-statuses exact,unattributed,not_applicable
  python3 "$ROOT/sim/verilator/correlate_provenance.py" \
    "$WINDOW_OUT/${window_variant}.csv" \
    --output "$WINDOW_OUT/${window_variant}-provenance.csv" \
    --fail-on-mismatch --require-complete-coverage --require-exact-fetches \
    --expect-count fetches=26205 --expect-count match=26205 \
    --expect-count collision=0 --expect-count cpu_exact=8495 \
    --expect-count initial_powerup=656 --expect-count gdma_rom=17054 \
    --expect-count cpu_rom_movsb=0 \
    --expect-count cpu_rom_movsb_bytes=0 \
    --expect-count cpu_rom_movsb_origins=0
  WINDOW_BG_SUMMARY="$(python3 "$ROOT/sim/verilator/correlate_bg_cells.py" \
    "$WINDOW_OUT/${window_variant}.csv" \
    --output "$WINDOW_OUT/${window_variant}-bg-cells.csv" \
    --require-complete-coverage)"
  echo "$WINDOW_BG_SUMMARY"
  require_bg_layers "$WINDOW_BG_SUMMARY" screen2
  require_bg_counts "$WINDOW_BG_SUMMARY" \
    cells=8463 screen1=0 screen2=8463 bpp2=0 bpp4=8463 \
    raw_superseded=60 raw_unpromoted=2 raw_inflight=0 raw_prefix_truncated=2 \
    cpu_rom_movsb_cells=0 cpu_rom_movsb_bytes=0 \
    cpu_rom_movsb_origins=0
  python3 "$ROOT/sim/verilator/verify_window_boundary_probe.py" \
    --variant "$window_variant" \
    --rom "$WINDOW_OUT/roms/wsc_window_${window_variant}_probe.wsc" \
    --frame "$WINDOW_OUT/${window_variant}-frames/frame-1.rgb"
done
