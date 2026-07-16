# Analogue Pocket first-class compliance matrix

Last audited: **2026-07-16**
Audit scope: protected `main` candidate
`a897ecbf2838fe6997628406b23de2020c04772e`; the exact public-release commit is
not frozen yet.

This is a source-and-evidence audit, not a hardware certification. The working
tree after the baseline snapshot integrates host notifications `00B1`, `00B2`,
and `00B8`, destination-domain reset/download controls, clock-domain-safe
frame-boundary grayscale, Pocket's required `0x444D` affirmation, generic LCD
modes, a guarded 48-bit data-slot interface, atomic save-metadata publication,
the official Setup/Idle/Running lifecycle, and focused APF simulations. Those
paths are source-verified below. Two distinct signed Quartus workflow executions
for the protected-main candidate pass their accepted evidence audits and produce
a byte-identical RBF and build ID. Physical Pocket/Dock gates, distribution
clearance, and fresh signed workflow executions after release-facing source,
documentation, metadata, or policy changes remain open.

Swan Song is maintained by Regionally Famous and uses the independent APF
publisher identity `RegionallyFamous.SwanSong`. The Robert Peip system core,
Adam Gastineau Pocket port, and predecessor platform-art provenance remain in
`README.md` and `UPSTREAMS.md`. The current Swan Song icon and **Swan Wake**
platform artwork are original Regionally Famous-authored, deterministic assets.

## Verdict

The repository is a strong functional-development tree, but it is **not yet a
first-class Pocket release**. The deterministic console regression, package
builder, accepted protected-main Quartus candidate pair, four-corner timing
audits, and byte-identical outputs are strong software and FPGA evidence;
they do not prove save behavior on Analogue OS, Pocket/Dock operation, or legal
authorization to distribute a public release.

The supported product boundary is an openFPGA SD-card asset launch: one `.ws`
or `.wsc` cartridge image, the core's built-in Open IPL, and APF-owned video,
audio, input, settings, saves, menus, and Dock transport. It is not Pocket's
first-party physical-cartridge or Library flow. Cartridge power is off, the
cartridge and link ports are unused, and game data is never bundled.
PocketChallenge v2 and `.pc2` assets are outside the boundary because this
core does not implement that machine's pinstrap boot, distinct keypad matrix,
or absent internal EEPROM.

The new core ID may be installed beside `agg23.WonderSwan`. Platform-common
ROM assets remain shared. Slot-0-mirrored cartridge saves, fixed console
EEPROM, Settings, Presets, browser history, and Memories use separate core-ID
namespaces. Legacy shared cartridge saves require the ROM/footer-aware,
no-clobber migration helper; EEPROM/settings/presets may be copied only with a
backup, no destination overwrite, and post-copy validation. Memories must not
be copied: they are disabled and there is no cross-ID format migration.

Release blockers, in order:

1. Prove the guarded dynamic nonvolatile lifecycle through the complete wrapper
   and on hardware, including missing/truncated/oversized files, normal Quit,
   manual power-off, the dedicated firmware-2.6 Auto Off dirty-save flush with
   no manual/menu/input/Dock/USB-SD intervention, and the documented
   legacy migration paths.
2. Prove the `00A0`/`00A4` state machine end to end and on Pocket before
   re-enabling `sleep_supported` or advertising Memories and sleep/wake.
3. Exercise Interact persistence, the complete video/audio path, all eight Open
   IPL model/bus/owner-policy variants, title changes, screenshots, and Dock transport
   on physical Pocket hardware;
   keep the completed APF-boundary simulations green.
4. Complete the upstream distribution/licensing review and explicitly authorize
   Regionally Famous publication without weakening the historical provenance.
5. The exact development commit `a897ecbf` has two clean Quartus 21.1.1
   candidates from distinct signed workflow executions with different fresh job
   nonces. Both pass the full candidate audit and produce byte-identical RBF and
   build-ID files. After release source, documentation, metadata, and policy are
   frozen, repeat that pair if the public commit or epoch differs, then feed both
   complete signed bundles only to the stable assembler; direct Release Evidence
   or release-package CLIs are not public release paths. The signatures prove
   distinct workflow executions, not distinct physical hosts. The development
   package cannot be promoted without the remaining hardware and licensing gates.

## How status is assigned

- **Compliant (source):** the checked-in declaration/logic matches the cited
  software contract. Hardware confirmation may still be a separate gate.
- **Partial:** a required path exists but is incomplete, stale, insufficiently
  bounded, or not demonstrated end to end.
- **Missing:** no implementation or release gate was found.
- **Unverifiable here:** the behavior belongs to Analogue OS or physical
  hardware and cannot be honestly established from this repository alone.

`I`, `V`, and `D` below mean **implement**, **verify**, and **defer to a
host/hardware gate**, respectively.

## Prioritized matrix

| Priority | Area | Status | Exact repository evidence | Required disposition and acceptance test |
|---|---|---|---|---|
| P0-I | Framework level and APF baseline | **Definition aligned; hardware pending** | The core declares APF v1 metadata and requires Pocket firmware `2.3`: display modes/`00B8` require 2.0, while 2.3 fixes **Reset all to defaults** clearing the persisted browser history used by the cartridge slot ([`core.json`](dist/Cores/RegionallyFamous.SwanSong/core.json), [firmware 2.3](https://www.analogue.co/support/pocket/firmware/2.3)). Dock remains enabled while `sleep_supported` is deliberately false until Memories is certified. The PAD wrapper and top-level retain the official 32-bit key word, accept Pocket/Dock gamepad types, and reject absent, keyboard, mouse, and reserved types with focused RTL and mutation coverage ([`io_pad_controller.v`](src/fpga/apf/io_pad_controller.v), [`apf_gamepad_filter.sv`](src/fpga/core/apf_gamepad_filter.sv)). | Keep the typed-PAD and host-definition gates green; validate **Reset all to defaults** on 2.3 and the Recent/relaunch flow on current [Pocket firmware 2.6.0](https://www.analogue.co/support/pocket/firmware/2.6.0), then resolve the remaining lifecycle/hardware gaps before release. |
| P0-I/V | Boot/status/data-slot command flow | **Integrated and focused-simulated; wrapper/hardware pending** | `0082` now captures the documented full 48-bit expected length, and separate read/write results preserve `0` ready, `1` never, and `2` later ([`core_bridge_cmd.v`](src/fpga/core/core_bridge_cmd.v), [`apf_dataslot_guard.sv`](src/fpga/core/apf_dataslot_guard.sv)). The integrated startup path holds requirements through `008F`, delivered receipt of `0090`, metadata/table publication, and loader/initializer readiness; the sequencer issues target `0140` once, while the command handler keeps Pocket-visible status in Setup until acknowledgement and requires `0011` before Running. An early `0011` remains busy and holds reset, and a new title invalidates the preceding title's acknowledgement ([`apf_startup_sequencer.sv`](src/fpga/core/apf_startup_sequencer.sv), [`core_top.v`](src/fpga/core/core_top.v)). Shutdown `0080` returns retry until `reset_n=0`, the synchronized execution level is stopped, and a fixed 31-`clk_74a` drain guard has elapsed. Focused command, guard, sequencer, and source-contract tests cover results, readiness transitions, ordering, and target acknowledgement. | Keep the focused gates green and exercise the same order through the compiled full wrapper. Hardware gate: Setup -> `008F` -> delivered `0090` plus metadata/table/init readiness -> acknowledged `0140` -> Idle -> `0011` -> Running, with Reset Enter holding execution stopped through final nonvolatile read. |
| P0-V | RTC host command `0090` | **Command and CDC compliant in focused simulation; persistence hardware pending** | `0090` captures epoch/date/time, pulses `rtc_valid` for exactly one bridge clock, and returns OK ([`core_bridge_cmd.v:401-409`](src/fpga/core/core_bridge_cmd.v#L401-L409)); the command bench locks all three payload words. An acknowledged bundled-data CDC now holds the epoch stable, rejects rather than overwrites an in-flight event, and emits one coherent console-domain pulse; its asynchronous-clock bench delivers six boundary-pattern payloads with no tear, duplicate, or loss ([`apf_rtc_cdc.sv`](src/fpga/core/apf_rtc_cdc.sv)). The console consumes the synchronized valid edge, resets per-title trailer state, and emits `RTC_load` once only after the current timestamp and validated trailer are both ready ([`wonderswan.sv:955-1040`](src/fpga/core/wonderswan.sv#L955-L1040)). | Keep the command/CDC gates green. Pocket gate: RTC and non-RTC cartridges across cold boot, quit/relaunch, title reload, power cycle, sleep/wake, and minute/day crossings preserve the intended clock and never append or reuse a trailer for the wrong title. |
| P0-I/V | Nonvolatile slot flags and bounds | **Integrated source contract and focused RTL/CDC verified; wrapper/hardware pending** | Save slot 11 is core-specific, cloned from slot 0, nonvolatile, restart-on-reload (`0x86`), dynamic, and capped at `512 KiB + 12` ([`data.json`](dist/Cores/RegionallyFamous.SwanSong/data.json)). Core-specific storage prevents Swan Song's corrected layouts from silently replacing an incompatible shared save. Canonical payloads are `0/32K/128K/256K/512K` for none/SRAM and `128/2048/1024` for EEPROM `10/20/50`, plus an exact 12-byte trailer only when the footer declares RTC. Footer metadata crosses atomically to `clk_74a`; after `008F`, table index 1 / ID 11 is published as payload plus optional trailer and remains valid across Reset Enter for shutdown flush ([`apf_save_metadata_cdc.sv`](src/fpga/core/apf_save_metadata_cdc.sv), [`core_top.v`](src/fpga/core/core_top.v)). The guard returns `2` while slot-11 metadata is not ready, then accepts only absent, canonical, or the supported 2,060-byte legacy RTC EEPROM layout and returns `1` for type-inconsistent/malformed lengths. Initialization and legacy-loader benches cover absent/loaded data and exact type capacities. | Keep the namespace, guard, metadata CDC, table-publication, initialization, and legacy-loader gates green. Full-wrapper and Pocket gates still require every type with absent, exact, short, legacy, oversized, malformed-RTC, title reload, quit, restart, and power-off cases, plus the protocol's exact firmware-2.6 Auto Off dirty-save flush/reload case; Memories/Sleep remain disabled and are not inferred from this work. |
| P0-I/V | Legacy save migration | **Converters and runtime rejection/compatibility implemented; hardware survival pending** | Non-destructive converters validate checksummed ROM footers and exact inherited layouts, then atomically create new paths without overwrite: type `0x01` expands 8,204 bytes to 32,780, while padded type `0x10`/`0x50` saves shrink from 2,060 bytes to 140/1,036 by preserving the exact EEPROM payload and relocating the opaque RTC trailer ([`migrate_type01_save.py`](scripts/migrate_type01_save.py), [`migrate_legacy_eeprom_save.py`](scripts/migrate_legacy_eeprom_save.py)). Focused tests cover hashes, determinism, wrong types/checksums/lengths, aliases, and existing destinations. Once footer metadata is ready, the integrated guard rejects the obsolete type-`01` length with result `1`; it accepts 2,060-byte type-`10`/`50` only as the documented padded RTC compatibility case, and runtime publication remains canonical. | Keep the original-file-preserving converters and fail-closed guard tests green. Prove migrated files survive play/quit/reload on Pocket, including type-`01` addresses above `0x1fff` remaining distinct and both external-EEPROM RTC trailers retaining time. A Pocket-visible diagnostic for rejected legacy type-`01` would improve first-class UX but is not yet implemented. |
| P0-I/V | Memories and `00A0`/`00A4` | **Control/staging contracts plus disabled SDRAM ownership/drain boundary focused-simulated; feature safely disabled** | The handler implements the documented query/result states and rejects hostile Request Start/Load commands when support is false, regardless of stale controller flags ([`core_bridge_cmd.v`](src/fpga/core/core_bridge_cmd.v)). The maximum MiSTer payload is source-derived as `0x90300`, correcting the inherited value that was 256 bytes short; Pocket's future exact query size is `0x90320` after a 32-byte `SWAN` envelope. In addition to adversarial envelope coverage, the isolated staging coordinator proves that malformed, partial, gapped, or backend-failed A4 copies cannot authorize a payload read or pulse the sole live-mutation entry point, and that A0 remains unreadable until every exact payload word has been accepted ([`SAVESTATE_FORMAT.md`](SAVESTATE_FORMAT.md), [`MEMORIES_STAGING.md`](MEMORIES_STAGING.md), [`apf_savestate_staging.sv`](src/fpga/core/apf_savestate_staging.sv)). A compiled channel-1 owner now sits in the live ROM path and proves cartridge priority, outstanding-request drain, exclusive ready/data routing, full staging address width, held-ROM preservation, mandatory low guards, and fail-closed illegal stage access; production staging inputs remain tied low. The SDRAM controller now deterministically clears queued/delayed transaction state on PLL init and exports focused-tested global quiescence through request, command, CAS/read capture, write/cooldown, refresh, and startup phases; the wrapper retains channel-3 ready plus named channel-2/channel-3 requests for the future coordinator. The full coordinator remains absent from `ap_core.qsf`: APF requires the complete A4 blob before Request Load and copies A0 only after done, while the inherited FIFOs hold only 16 KiB inbound and 32 bytes outbound. The 590,624-byte blob also exceeds the device's entire raw M10K capacity, so production requires protected external SDRAM plus lossless CDC. Top-level and `core.json` therefore remain unsupported. | Add cooperative dispatch/prefetch/SDMA quiescence and consume the new memory-domain drain acknowledgement, replace fixed-delay savestate SRAM access with real channel-3 completion, then connect serialized state-engine/channel-1 transfers, exact smaller-RAM padding, lossless bridge/memory crossings, bounded bridge reads, cancellation, compatibility identity, and payload integrity. Prove bridge copy/load/repeat, reset/menu interruption, title binding, malformed blobs, and older-format rejection end to end. Pocket gate: mono/color, every RAM type, EEPROM/RTC, both orientations, fast-forward, audio activity, sleep/wake, and an older-release Memory. |
| P0-D | Sleep/wake claim | **Correctly disabled; certification still open** | `sleep_supported` is false, top-level reports savestates unsupported, and README/info explicitly say Memories and Sleep + Wake are disabled pending validation ([`core.json:13-20`](dist/Cores/RegionallyFamous.SwanSong/core.json#L13-L20), [`README.md`](README.md), [`info.txt`](dist/Cores/RegionallyFamous.SwanSong/info.txt)). The repository also says this branch has not been validated on Pocket ([`README.md`](README.md)). | Re-enable only after at least 50 sleep/wake cycles distributed across the state matrix above, with save-file hash/semantic checks and continued audio/video/input/RTC operation. A single successful wake is not sufficient. |
| P0-I/V | `00B8`, grayscale, and display modes | **Compliant (source and focused simulation); hardware pending** | `video.json` advertises only Analogue's forward-compatible generic grayscale, reflective-color, and backlit-color LCD modes (`0x20`, `0x30`, `0x40`) with sharpness 3 ([`video.json`](dist/Cores/RegionallyFamous.SwanSong/video.json)). These host modes are not mislabeled as WonderSwan-specific profiles. The handler stores the mode/request, remains busy until the applied state returns across the CDC, fails closed on X/Z, and emits `0x444D` only for active grayscale. Top-level synchronizes the request, applies a tested full-range 1:2:1 grayscale conversion at a frame boundary, and synchronizes the applied state back. Focused benches cover delayed enable/disable, exact responses, bypass, endpoints, and a 4,096-color matrix. | Keep the source gate green. Physical gate: each advertised mode on all three scaler slots, transition frames, both core color profiles, Pocket screenshots, Dock insertion/removal, and color restoration must show no unequal-channel grayscale pixel, partial-frame switch, resync, or stale mode. |
| P0-I/V | `00B2` Dock notification | **Compliant (source and focused simulation); hardware pending** | Core metadata permits Dock ([`core.json:17-20`](dist/Cores/RegionallyFamous.SwanSong/core.json#L17-L20)). The handler accepts, stores, and acknowledges `00B2`; `core_top` connects the held state, while no console behavior is intentionally conditional on Dock ([`core_bridge_cmd.v:473-477`](src/fpga/core/core_bridge_cmd.v#L473-L477), [`core_top.v:573-650`](src/fpga/core/core_top.v#L573-L650)). The focused command bench verifies set/clear without altering unknown-command behavior. | Pocket must still enter/leave Dock without reset, lost input, video resync, save corruption, or audio channel/rate change. Add Dock-specific behavior only if a demonstrated requirement emerges. |
| P1-V | `00B1` cartridge-adapter notification | **Compliant (source and focused simulation); hardware pending** | The core declares `cartridge_adapter: -1`, keeps the cartridge pins inactive, and now explicitly accepts Pocket's unconditional startup `00B1` notification as a no-op. The host-notify bench supplies representative play/power/adapter fields and proves an OK response without changing menu, Dock, or display-mode state. Reset and cartridge/Open-IPL initialization controls have distinct `clk_mem` and `clk_sys` copies; a mutation contract rejects direct memory-domain use by system-domain logic, including the save-clear reset hold. | Keep the explicit OK response and destination-domain contract green. Pocket gate: boot and repeated title reloads must complete without a stuck command or reset, including Dock transitions and absent physical cartridge hardware. |
| P1-V | `00B0` menu behavior | **Integrated and translated-core simulated; hardware pending** | `00B0` is accepted and stored ([`core_bridge_cmd.v`](src/fpga/core/core_bridge_cmd.v)). `core_top` feeds that held state independently into the typed gamepad filter and a dedicated three-register menu-focus level CDC ([`apf_menu_focus_cdc.sv`](src/fpga/core/apf_menu_focus_cdc.sv)). The synchronized level pauses the existing SwanTop console clock-enable path while the physical guard separately blocks buttons, clears Fast Forward history, and waits for a fresh neutral PAD packet; menu exit therefore resumes the emulated console without waiting for input rearm ([`wonderswan.sv`](src/fpga/core/wonderswan.sv)). CPU, DMA, GPU, and sound share the gated enables, while SDRAM refresh and raw-clock cartridge RTC advancement continue through the existing three-cycle scheduler warmup. Focused Verilator tests prove the CDC and PAD/Fast Forward independence. A current-source 31-file GHDL 6 translation plus 178-module Verilator build passes the real SwanTop bench in all eight normal/Fast Forward and `0/833/1666/2499` ps RAM-phase cases. Each case pauses with a live external request and proves one ROM read, one SRAM write/readback, exact transaction cardinality, delayed read retention and IRAM markers, gated console/DMA/GPU/audio, continuing refresh/RTC, held frame/sample state, and the three-cycle resume. The structure and matrix also pass lint and 47 mutation tests. The separate I2S waveform test remains complementary rather than a direct `00B0` end-to-end proof. Analogue permits `00B0` to be ignored for compatibility, so this is Swan Song's product choice, not a protocol requirement. | Keep the explicit OK response, separate CDC/ownership paths, focused pause tests, and complete eight-case translated bench green. Pocket/Dock gate: repeated menu entry/exit during action and Fast Forward must pause/resume without a stuck button, leaked menu chord, duplicated memory/DMA action, audio pop, partial/resynchronized display, save damage, or RTC error. Source and simulation do not establish physical timing or presentation quality. |
| P1-I/V | Interact actions, readback, and persistence | **Read/write contract and focused simulation complete; physical UX pending** | All nine persistent runtime settings now use Analogue's documented frame read/write behavior rather than `writeonly` declarations ([`interact.json`](dist/Cores/RegionallyFamous.SwanSong/interact.json)). A dedicated exact-address readback block returns the zero-extended thirteen-bit requested settings bundle at `0x100`, `0x110`, `0x200`-`0x214`, and `0x300`; exhaustive focused simulation covers every bundle value and rejects aliases. **System Type (reset)** deliberately reads back the requested persistent choice, not the active model resolved from the cartridge footer. Top-level implements their writes and transfers the complete package, including color profile and independent Control Layout, through an acknowledged bundled CDC, so legal multi-bit list transitions cannot expose a torn intermediate value; its defaults match the JSON and normal Reset Enter does not discard it ([`apf_settings_cdc.sv`](src/fpga/core/apf_settings_cdc.sv)). Reset Exit remains busy until both Ready-to-Run and acknowledgement of the latest complete settings package, preventing execution under stale startup defaults. Runtime System Type changes remain inert until host, title-load, or external reset, while Auto continues to use the captured cartridge footer ([`wonderswan.sv`](src/fpga/core/wonderswan.sv), [`footer_snapshot_tb.sv`](sim/rtl/footer_snapshot_tb.sv)). | Keep exact-address readback, JSON readability, CDC, and focused simulation green. Pocket gate: defaults arrive before reset exit, every option reads back and persists over quit/relaunch, **Reset all to defaults** restores both UI and RTL, and Reset core remains momentary. |
| P1-V | Input mappings and display presentation | **Source and focused simulation complete; physical UX pending** | One default controller exposes exactly the allowed maximum of eight mappings ([`input.json:4-50`](dist/Cores/RegionallyFamous.SwanSong/input.json#L4-L50)). The console uses player 1. **Control Layout** defaults to Auto, where the running WonderSwan's native `vertical` signal selects the face/shoulder-button matrix; forced Horizontal and Vertical select only that matrix, fail closed to Auto for unadvertised values, and never alter the native D-pad matrix. The separate `Display Orientation` and `Landscape 180°` controls select only Pocket presentation, while an exhaustive mapper bench covers every button vector, native orientation, and legal/invalid layout encoding. The PAD path retains the official 32-bit key word and fails closed unless type `[31:28]` identifies a Pocket, digital Dock, or analog Dock gamepad. The core consumes APF host-normalized packets and does not enumerate USB HID devices, so Analogue OS/Dock support for a particular controller is a separate prerequisite ([`io_pad_controller.v`](src/fpga/apf/io_pad_controller.v), [`apf_gamepad_filter.sv`](src/fpga/core/apf_gamepad_filter.sv), [`apf_control_layout.sv`](src/fpga/core/apf_control_layout.sv)). | Keep controller-type filtering, layout mapping, and frame-atomic scaler selection focused gates green. Pocket gate: every mapping, simultaneous directions, fast-forward latch/release, runtime native-orientation changes under all three Control Layout choices, all Display Orientation choices, Landscape 180°, and exact scaler-slot command placement. Pocket and Dock coverage must include built-in controls plus at least two representative wired/wireless Dock pads and prove display forcing never remaps game controls. Do not promise every USB gamepad without host compatibility evidence. |
| P1/3-V | Base video bus, color, and temporal response | **Complete digital contract simulated; physical timing/panel match unverified** | The definition is 224x144 RGB with 0/270/180-degree scaler slots ([`video.json`](dist/Cores/RegionallyFamous.SwanSong/video.json)). Slot changes cross atomically and apply only at VS; the related 36.864/6.144 MHz RGB/control bundle is staged on the intervening system falling edge and remains visible to TimeQuest. The APF adapter has a full two-frame bus test proving exactly 224x144 active pixels, 258 one-HS lines, one-cycle HS/VS, one scaler command per active line, zero reserved words, frame-atomic grayscale, and the exact 102,426-pixel-clock cadence (59.984769 Hz at 6.144 MHz) ([`apf_video_bus.sv`](src/fpga/core/apf_video_bus.sv), [`apf_video_bus_tb.sv`](sim/rtl/apf_video_bus_tb.sv)). A separate exhaustive raster bench proves 614,556 system clocks per 397x258 output frame; exact native-to-output frame-age and drop-rate derivations are executable and documented ([`apf_scanout_cadence.sv`](src/fpga/core/apf_scanout_cadence.sv), [`FRAME_DELIVERY.md`](FRAME_DELIVERY.md)). Framebank ownership keeps completed histories immutable, while split 10+2-bit M10K memories target 200 blocks instead of a naïve 240; the all-address RAM bench preserves every RGB444 value and read latency ([`apf_framebank_ram.sv`](src/fpga/core/apf_framebank_ram.sv)). The neutral Mednafen-compatible `×17` expansion remains default. Optional pinned-ares color correction, rounded two-frame blending, and a project-designed finite 50/25/25 approximation of ares' recursive response are frame-atomic and exhaustively arithmetic-tested ([`SCREEN_AUTHENTICITY.md`](SCREEN_AUTHENTICITY.md)). | Keep the bus and focused unit gates green. Both signed `a897ecbf` candidates fit at 277/308 M10Ks and pass strict four-corner timing with byte-identical RBF/build-ID outputs. Gate on Pocket/Dock for all rotations, direct/buffered output, both color profiles, every LCD response, tearing/latency, generic display modes, and screenshots. Do not call either optional transform panel-accurate until controlled WSC/SwanCrystal capture data exists. |
| P1-V | Audio, 48 kHz I2S | **Compliant in focused waveform simulation; physical CDC pending** | `sound_i2s` now derives SCLK from the same accumulator event that raises MCLK, changes DAC only on falling SCLK, and emits signed stereo 16-bit samples with a one-bit I2S delay and zero spacer positions ([`sound_i2s.sv:47-72`](src/fpga/core/sound_i2s.sv#L47-L72), [`sound_i2s.sv:128-158`](src/fpga/core/sound_i2s.sv#L128-L158)). A randomized-seed 10 ms bench proves 12.288 MHz MCLK, 3.072 MHz SCLK, 48 kHz stereo, coincident clock edges, LRCK-low left/high right, asymmetric exact samples, zero startup, and all spacer bits. Top instantiates signed 16-bit stereo ([`core_top.v:1601-1614`](src/fpga/core/core_top.v#L1601-L1614)). The bench substitutes a behavioral CDC FIFO and host reset does not restart serializer phase. | Keep the waveform gate green. The signed `a897ecbf` candidates close Quartus fit/static timing for the production Intel FIFO path. Physical hardware must still cover FIFO overflow margins, Reset Enter/Exit phase expectations, silence, left/right tones, clipping extrema, fast-forward, menu, sleep/wake, Dock transitions, and a long run with no pops, drift, or swapped channels; rebuild if the exact final public commit differs. |
| P1-I/V | Platform metadata, image, icon, and info | **Source metadata and installed copy aligned; hardware presentation pending** | `wonderswan` is a valid lowercase platform ID and has matching JSON ([`core.json:4-11`](dist/Cores/RegionallyFamous.SwanSong/core.json#L4-L11), [`wonderswan.json:1-8`](dist/Platforms/wonderswan.json#L1-L8)). The family platform is now named “WonderSwan,” dated to Bandai's 1999 launch, rather than mislabeling mono support as “WonderSwan Color.” The current [`wonderswan.bin`](dist/Platforms/_images/wonderswan.bin) is Regionally Famous's original **Swan Wake** design: exactly `521*165*2 = 171930` bytes, deterministically rendered with integer primitives from the same authored 18x18 swan grid as the core icon, and bound to a reviewed digest by independent generator, validator, and package tests ([`PLATFORM_ART.md`](PLATFORM_ART.md)). Pocket displays [`info.txt`](dist/Cores/RegionallyFamous.SwanSong/info.txt) in Platform Detail/About under the official [32-line plain-text contract](https://www.analogue.co/developer/docs/core-definition-files); its Open IPL, firmware, feature, unsupported-hardware, and pending-validation claims are cross-checked against the shipped JSON definitions, and the package test proves the exact bytes reach the ZIP. The optional [`icon.bin`](dist/Cores/RegionallyFamous.SwanSong/icon.bin) is an original generic swan mark, deterministically generated at Analogue's recommended 2x2 scale with the documented 36x36, 16-bit monochrome, counter-clockwise storage format; its focused test binds the upright source, binary, and reviewed digest ([`CORE_ICON.md`](CORE_ICON.md)). Metadata now identifies the independent development snapshot as `0.1.0-dev.1` dated 2026-07-13; this is not a claimed public release. | Keep the art/icon/metadata/package contracts green. Gate: fresh-SD openFPGA Platform Detail plus positive/negative Core List and Core Boot Screen inspection for legibility, centering, contrast, clipping, and no stale or misleading claims; replace the development version/date with the actual release values only in the reviewed release change. |
| P1-V | Core/asset metadata and hardware declarations | **Mostly compliant (source)** | APF magic, target product, bitstream/Chip32 names, Dock true, link false, and cartridge power-off compatibility value `-1` are declared ([`core.json`](dist/Cores/RegionallyFamous.SwanSong/core.json)). The release-profile validator checks every shipped APF/platform JSON, rejects unknown members and undocumented values, enforces official limits and cross-file identity, and locks the implemented four-slot/single-controller/no-variant shape ([`package_validator.py`](scripts/package_validator.py)). ROM, cartridge-save, and fixed console-EEPROM addresses are outside reserved `0xF8...` ([`data.json`](dist/Cores/RegionallyFamous.SwanSong/data.json)); top-level puts unused IR/link/cart pins into safe states. Slot 0 accepts whole-64-KiB-bank images from 64 KiB through the implemented 16 MiB cap, while compact images require a valid footer/checksum and are `0xff`-prefilled/right-aligned. Conventional power-of-two images retain the inherited direct loader; their model/bus/owner fields are snapshot from the footer without an APF checksum gate. Slot 11 is the dynamic cartridge save; optional fixed-name slots 12/13 load and unload exact 128/2,048-byte mono/Color console EEPROM images. The reviewed `open-bootstrap-v3` IPL is embedded in the core and its model, bus width, and owner-area policy are selected from that footer snapshot, so APF has no external firmware slot or prompt. Only Auto, WonderSwan, and WonderSwan Color are advertised; PocketChallenge v2 and `.pc2` remain excluded. | Exercise `.ws`/`.wsc`, minimum/maximum/896 KiB ROMs, title reload, all eight Open IPL model/bus/owner-policy variants, fixed EEPROM creation/persistence, and Auto/forced system models. Confirm cartridge/link/IR power and pin behavior on Pocket; source tie-offs alone are not an electrical measurement. |
| P1-I/V | Packaging | **Host release gate and development candidate evidence complete; final release V2 and authorization absent** | Packaging requires a nonempty RBF, applies a complete release-path allowlist, validates every shipped definition and artwork contract, materializes the bit-reversed stream and pinned Chip32 image, and emits a deterministic ZIP plus SHA-256 provenance sidecar ([`package_core.py`](scripts/package_core.py), [`package_validator.py`](scripts/package_validator.py)). Release mode requires the metadata-derived `Author.Core_version_date.zip` name and `SWAN_SONG_RELEASE_EVIDENCE_V2`. V2 binds the exact RBF, generated build-ID MIF, Quartus 21.1.1 reports, and two candidate audits from distinct signed workflow runs that the packager recomputes from the complete artifact bundles. Signed runs `29503168418` and `29505865127` satisfy that two-run shape for development commit `a897ecbf`; they are not release authorization and do not bind a later commit. Final V2 packaging re-verifies and hash-binds the exact private inventory and accepted 31-case Pocket/Dock manifest, including the `open-bootstrap-v3` identity and footer-derived variant set, then requires its RBF, installed bitstream, definitions, version, date, and nine persistent settings to match the release. Release policy still keeps distribution-and-licensing authorization false. | Complete the physical 31-case run—including the exact Auto Off dirty-save case—and licensing review, choose the first public Swan Song version/date/firmware floor, authorize distribution-and-licensing, and freshly reproduce the exact release commit in two distinct signed workflow executions if it differs before running the stable assembler; no stable release package is currently claimed. |
| P0-I/V | Quartus bitstream and TimeQuest | **Protected-main signed candidate pair accepted and byte-identical; physical/public-release gates open** | The pinned Quartus Lite 21.1.1 Linux/amd64 flow completed fresh synthesis, fitting, assembly, RBF generation, and four-corner TimeQuest for `5CEBA4F23C8` from protected `main` commit `a897ecbf2838fe6997628406b23de2020c04772e`, using the current 5.9/2.5 ns SDRAM constraints. Signed workflow runs `29503168418` and `29505865127` use different fresh nonces, pass both candidate audits, and produce byte-identical RBF/build-ID files. The fit uses 12,974/18,480 ALMs, 16,174 registers, 2,524,544/3,153,920 memory bits, 277/308 M10Ks, 23/66 DSP blocks, and 1/4 PLLs. Minimum setup/hold/recovery/removal/pulse-width slack is `+0.255/+0.083/+5.037/+0.272/+0.753 ns`; all total negative slack values, eight `check_timing` diagnostics, and unconstrained-path counts are zero; all reviewed connectivity rows match the exact allowlist; and there are zero critical warnings. Both 2,037,952-byte RBFs have SHA-256 `951e114b1ed2e70ed11628bcfac9bc6138922cbfe45250ab56981fcdf971c03d`; both build-ID MIFs have SHA-256 `8d1c9fb08f2a1ff95de1b326b7ef6b66952f8dc2986c2aec9c0aec32cc544a17`. Both audits correctly record `release_eligible: false`. | Use this exact development candidate for controlled Pocket/Dock QA. After licensing, policy, version, documentation, and release metadata are frozen, produce two candidates for the exact public commit and epoch if it differs, require byte-identical RBF/build-ID outputs, and pass both complete bundles to the stable assembler; do not promote the development package without the remaining gates. |
| P0-D | Pocket/Dock hardware QA and release truth | **Unverifiable here; mandatory** | Project status explicitly says hardware equivalence is not tested and requires Pocket validation ([`PHASE_STATUS.md:29-35`](PHASE_STATUS.md#L29-L35)); simulation excludes Pocket wrappers and physical SDRAM behavior ([`PHASE_STATUS.md:7-12`](PHASE_STATUS.md#L7-L12)). | Use a fresh SD card and current stable Analogue OS plus the declared minimum firmware if retained. Record device/OS/Dock versions, core ZIP/RBF SHA-256, ROM hashes from legally owned dumps, test duration, results, photos/captures where useful, and tester. Do not label the release first-class until every Gate 3 item below passes with no unexplained critical warning or data loss. |
| P2-D | Screenshots | **Unverifiable/host-owned** | Analogue says openFPGA cores [automatically support screenshots](https://www.analogue.co/developer/docs/changelog/1-1-beta-7); there is no core-side screenshot command or JSON integration. This core supplies the video bus on which that host feature depends. | Treat screenshot creation as an Analogue OS acceptance test, not a new RTL feature. On Pocket and Dock, capture horizontal/vertical/180-degree presentation, mono/color, each generic display mode, and all three scaler slots; verify orientation, aspect, full frame, colors/grayscale, and file readability after relaunch. A failure may still reveal a video-bus or scaler-slot defect. |

## Acceptance gates

### Gate 0 — declarations and deterministic host-side checks

All must pass before building a candidate:

- APF JSON validation, unique IDs, length/range/address checks, and coherent
  framework/platform/release metadata.
- Save-slot bound and initialization policy are explicit; legacy type-`01`
  inputs cannot be silently loaded as corrected saves.
- Package tests pass twice byte-for-byte; the ZIP allowlist contains no game
  ROM, save, placeholder, trace, or temporary file. The open IPL is reviewed
  source-generated core content, not a user-supplied firmware asset.
- Existing deterministic regression passes from a clean checkout with its
  pinned dependencies. This remains console-logic evidence, not Pocket proof.

### Gate 1 — APF integration simulation

Self-checking benches must pass for:

- boot/status/reset/`0080`/full-48-bit `0082`/`008A`/`008F`/delivered
  `0090`/acknowledged `0140` ordering, including exact `0` ready, `1` never,
  and `2` later results, new-title invalidation of stale `0140`, and shutdown
  `0080` retry through the fixed 31-`clk_74a` drain guard;
- `00A0` and `00A4` query, request, busy, done, error, malformed length, and
  repeated save/load sequences;
- `00B0`, `00B1`, `00B2`, and `00B8`, including destination-domain control
  synchronization and a fail-closed grayscale acknowledgement;
- slot 0/11 direction and exact-size policy, permanent rejection of retired
  firmware IDs 9/10, atomic slot-11 metadata/table
  publication, canonical/legacy loaded sizes, and every supported save type;
- Interact defaults, persistence, readback policy, and **Reset all to defaults**;
- PAD type plus all eight mappings and all three orientation scaler slots;
- VIDEO timing assertions and exact grayscale pixels; and
- 48 kHz I2S frequency, phase, bit order, channel order, spacer, and reset.

### Gate 2 — two signed reproducible FPGA candidates

- Two clean Quartus Prime Lite 21.1.1 candidates for `5CEBA4F23C8`, the same
  exact commit, and the same source epoch, produced by distinct signed workflow
  executions with different fresh job nonces.
- Both use the checked-in workflow's candidate build class. A direct local
  `quartus_docker.sh build` is development output, emits no candidate audit, and
  cannot satisfy this gate.
- TimeQuest passes all clock domains with no negative slack and no unexplained
  unconstrained path or critical warning.
- Both candidate audits and GitHub attestation bundles are retained; their RBF
  and build-ID files are byte-identical, and the RBF is nonempty, compressed as
  intended, bit-reversed once, and bound to the archived reports, Git commit,
  and final ZIP. Distinct signatures prove distinct workflow executions, not
  different physical hosts.
- The stable assembler verifies both signed origins and emits
  `signed-quartus-provenance.tar`; lower-level evidence/package CLIs are not
  alternative public release paths.
- Install is tested from the ZIP on a freshly prepared SD, not from loose files
  left by development.

### Gate 3 — physical Pocket and Dock release matrix

At minimum:

- cold boot/reboot/quit/relaunch with WS and WSC using the embedded Open IPL;
  prove mono/Color, 8/16-bit bus, and owner-protection selection from the
  footers without any external firmware prompt;
- every supported SRAM/EEPROM size, no-save creation, normal reload, RTC,
  corrected type-`01`, rejected legacy/short/long inputs, and save-file hashes
  before/after controlled operations; separately prove an undocked firmware-2.6
  Auto Off shutdown flushes a dirty generated type-`03` save and that the next
  launch loads it, with Auto Dim disabled and no manual power, menu, input,
  Dock, or USB SD intervention;
- after Memories is implemented, create/load/delete plus a deliberately
  compatible older `RegionallyFamous.SwanSong` Memory, never a renamed
  `agg23.WonderSwan` Memory, then run the repeated sleep/wake campaign above;
- native horizontal/vertical input orientation, every `Display Orientation`
  setting, `Landscape 180°`, triple buffer, both color profiles, every LCD
  response, generic mono/color display modes, grayscale response, and screenshots;
- all controls, combinations, fast-forward behavior, menu enter/exit, at least
  two Dock controllers, Dock insert/remove, and loss/reacquisition of focus;
- stereo channel/frequency/listening checks across silence, extrema, menu,
  fast-forward, sleep, and at least a two-hour soak; and
- repeated launch/quit/Dock/sleep cycles with no crash, stuck reset, video loss,
  audio drift, save damage, or corrupted persistent setting.

Pass/fail evidence belongs in a dated release report. “Booted once” is not a
substitute for this matrix.

## Deliberately deferred or optional items

- A core author `icon.bin` is optional in the official packaging docs. Swan
  Song now supplies one from deterministic source, but positive/negative Core
  List and Core Boot Screen appearance remains a physical Pocket polish gate.
- `00B0` may be ignored; using it to pause is a product decision.
- Analog Dock output is described as an upcoming feature in `core.json`; false
  is appropriate.
- Four-player and analog-stick gameplay are irrelevant to a one-player digital
  WonderSwan core, but PAD **type safety** still matters for Dock peripherals.
- Screenshots are host-owned in the audited public contract and remain a
  physical acceptance test.
- No physical-hardware result, Analogue OS behavior, or timing closure should be
  inferred from translated-RTL/game regression alone.

## Normative research baseline

Accessed **2026-07-15**. The live Analogue developer pages are the normative APF
contract; dated archive links are retained only where useful for older
changelog history.

- [Analogue changelog 2.3](https://www.analogue.co/developer/docs/changelog/2-3) — framework 2.3 and current display-mode changes.
- [Pocket firmware 2.6.0](https://www.analogue.co/support/pocket/firmware/2.6.0) — the pinned QA firmware and its Auto Dim/Auto Off power-saving controls.
- [Analogue changelog 1.1 beta 7](https://www.analogue.co/developer/docs/changelog/1-1-beta-7) — automatic Screenshot support for openFPGA cores, user-invoked with **Menu + Start**, and its Memories integration.
- [Analogue `core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json) — minimum firmware, sleep, Dock, hardware, and bitstream declarations.
- [Analogue `data.json`](https://www.analogue.co/developer/docs/core-definition-files/data-json) — slot flags, bounds, nonvolatile flush, and dynamic sizes.
- [Analogue `interact.json`](https://www.analogue.co/developer/docs/core-definition-files/interact-json) — frame read-modify-write, `writeonly`, IDs, and persistence.
- [Analogue `input.json`](https://www.analogue.co/developer/docs/core-definition-files/input-json) — four-controller/eight-mapping limits.
- [Analogue `video.json`](https://www.analogue.co/developer/docs/core-definition-files/video-json) — scaler/display modes and grayscale LCD behavior.
- [Analogue bus communication](https://www.analogue.co/developer/docs/bus-communication) — BRIDGE, PAD, VIDEO, and exact 48 kHz I2S requirements.
- [Analogue host/target commands](https://www.analogue.co/developer/docs/host-target-commands) — 48-bit `0082`, results `0/1/2`, the data-slot table, `008F`, `0090`, target `0140`, and runtime notifications.
- [Analogue core boot process](https://www.analogue.co/developer/docs/core-boot-process) — the Setup -> slot loads -> `008F` -> `0090` -> acknowledged `0140`/Idle -> `0011`/Running sequence and shutdown flush.
- [Analogue debugging aids](https://www.analogue.co/developer/docs/debugging-aids) — USB SD behavior and the warning that forced power-off can lose in-progress saves.
- [Analogue platform metadata](https://www.analogue.co/developer/docs/platform-metadata) — platform IDs, JSON, and image location.
- [Analogue packaging](https://www.analogue.co/developer/docs/packaging-a-core) — ZIP layout, RBF_R conversion, platform art, and optional icon.
- [Analogue SD directory structure](https://www.analogue.co/developer/docs/directories-and-sd-folder-structure) — Assets, Saves, Settings, and up to 128 Memories per core.
- [WSdev ROM header](https://ws.nesdev.org/wiki/ROM_header) — known cartridge header ROM/save/RTC encodings, including ROM sizes through 16 MiB.
- [WSdev mapper](https://ws.nesdev.org/wiki/Mapper) and [Bandai 2003 pinout](https://ws.nesdev.org/wiki/2003_Mapper_pinout) — later mapper bank width and ROM A25, the basis for a theoretical 64 MiB address capacity that is not implemented by this core.
- [Wonderful WonderSwan target](https://wonderful.asie.pl/docs/target/wswan/) — modern homebrew toolchain and memory-model documentation used by the open validation workload.

Primary implementation reference, accessed **2026-07-13**:

- [`open-fpga/core-template` v1.3.0 tip `da3a021...`, `core.json`](https://github.com/open-fpga/core-template/blob/da3a021b1eaf742604d86d8dc9b33a6666263e6a/core.json#L13-L30)
- [`open-fpga/core-template` host-command handler](https://github.com/open-fpga/core-template/blob/da3a021b1eaf742604d86d8dc9b33a6666263e6a/src/fpga/core/core_bridge_cmd.v#L393-L450)

The template is useful provenance for the inherited wrapper and `0090`/`00A0`/
`00A4`/`00B0` implementation. Its last commit is from 2023 and it lacks current
`00B2`/`00B8` handling, so the current Analogue protocol documentation above is
normative where they differ.
