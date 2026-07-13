# MiSTer/Pocket boundary

The project is a fork of Adam Gastineau's Pocket port, not an independent
WonderSwan implementation. The comparison baseline is recorded in
`UPSTREAMS.md`.

## Console logic

The files under `src/fpga/core/rtl/` originate in the MiSTer core and retain
their upstream license notices. The Pocket and MiSTer repositories both carry
a top-level GPL v2 license file; `ddram.sv` and `sdram.sv` additionally carry
GPL-v3-or-later file headers. At the pinned heads before Swan Song development,
every shared RTL file was byte-identical except five. Phase 1 adds changes in
two shared RTL files (one was already divergent), so the current shared-RTL
differences are:

- `rtc.vhd`: comment-only Pocket annotation.
- `gpu.vhd`: adds a simulation-gated validity tap for graphics VRAM arbiter
  issue slots; it does not change address selection.
- `savestate_ui.sv`: MiSTer OSD/gamepad UI divergence; it is not instantiated by
  the Pocket top.
- `savestates.vhd`: Pocket/APF save-state layout and operation-order changes.
- `sdram.sv`: Pocket's single SDRAM chip-select adaptation and refresh-state
  changes.
- `swanTop.vhd`: exports save-state busy status to the Pocket controller and,
  for `is_simu = '1'`, CPU completion/location, register writes, and GPU fetch
  taps. The non-simulation branch drives those observability outputs to
  constants.

The Pocket tree omits MiSTer's PLL wrapper and uses APF-specific PLL IP instead.
Changes to CPU, GPU, sound, mapper, EEPROM, RTC semantics, DMA, or console timing
should be developed so they can be applied to MiSTer first or with a minimal
shared patch.

The structured-trace policy and serializers are simulation-specific and live
under `sim/verilator/`. Only the minimal observation points live in shared VHDL.
Keep future trace filtering and file-format work in the harness; do not put
analysis policy or Pocket-specific behavior into the console modules.

## Pocket integration

These areas are Pocket-specific and should not be proposed upstream to MiSTer:

- `src/fpga/apf/`
- `src/fpga/core/core_top.v`
- `src/fpga/core/core_bridge_cmd.v`
- `src/fpga/core/data_loader.sv`, `data_unloader.sv`, and
  `save_state_controller.sv`, plus their `sync_fifo.sv` helper
- `src/fpga/core/sound_i2s.sv`
- `src/fpga/core/mf_pllbase*`, `core_constraints.sdc`, and the Pocket Quartus
  project files under `src/fpga/`
- `src/fpga/core/wonderswan.sv` frame delivery, output timing, Pocket control
  mapping, APF RTC/save adaptation, and settings
- `dist/` APF manifests and `src/support/chip32.asm`

## Merge procedure

1. Fetch `mister/main` and record its new commit in `UPSTREAMS.md`.
2. Diff `mister/main:rtl/` against `src/fpga/core/rtl/`.
3. Classify each delta as console behavior, MiSTer UI/platform glue, or Pocket
   adaptation before copying it.
4. Run `make regression` before and after the merge.
5. Run Quartus synthesis and timing analysis on a supported host before calling
   the merge build-clean.
6. Confirm on a Pocket before making any hardware-behavior claim.

Do not copy MiSTer `sys/` glue into the Pocket tree, and do not move Pocket APF
behavior into shared console modules merely for convenience.
