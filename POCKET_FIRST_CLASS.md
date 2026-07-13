# Analogue Pocket first-class compliance matrix

Last audited: **2026-07-13**
Repository baseline: `9f93a62937167ab54bd4f006996eeeb3e920aa89` on `codex/swan-song`

This is a source-and-evidence audit, not a hardware certification. The working
tree after the baseline snapshot integrates host notifications `00B1`, `00B2`,
and `00B8`, destination-domain reset/download controls, clock-domain-safe
frame-boundary grayscale, Pocket's required `0x444D` affirmation, generic LCD
modes, a guarded 48-bit data-slot interface, atomic save-metadata publication,
the official Setup/Idle/Running lifecycle, and focused APF simulations. Those
paths are source-verified below but still require Quartus and physical
Pocket/Dock gates.

## Verdict

The repository is a strong functional-development tree, but it is **not yet a
first-class Pocket release**. The deterministic console regression and package
builder are valuable evidence; they do not prove the complete Pocket wrapper,
Quartus timing closure, save behavior on Analogue OS, or Dock operation.

Release blockers, in order:

1. Prove the guarded dynamic nonvolatile lifecycle through the complete wrapper
   and on hardware, including missing/truncated/oversized files, shutdown flush,
   and the documented legacy migration paths.
2. Prove the `00A0`/`00A4` state machine end to end and on Pocket before
   re-enabling `sleep_supported` or advertising Memories and sleep/wake.
3. Add the remaining APF-boundary simulations for Interact persistence, base
   video timing, controller type handling, and full-wrapper unload.
4. Produce a clean Quartus 21.1.1 build, pass TimeQuest with no unconstrained or
   failing paths, package that exact RBF, and complete Pocket plus Dock QA.

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
| P0-I | Framework level and APF baseline | **Partial** | The core declares APF v1 metadata and now requires framework `2.0`, the version that introduced display modes and `00B8`; Dock remains enabled while `sleep_supported` is deliberately false until Memories is certified ([`core.json:3-25`](dist/Cores/agg23.WonderSwan/core.json#L3-L25)). Analogue's current changelog says the framework is `2.3`; the public `core-template` is still a 2023 v1.3.0 reference that declares `1.1`, so it is not the current protocol authority. The local PAD wrapper also retains the old 16-bit key interface ([`io_pad_controller.v:41-59`](src/fpga/apf/io_pad_controller.v#L41-L59)). | Treat `version_required` as the minimum actually needed, not a marketing version. The host-definition contract now binds `2.0`, the generic modes, slot limits, metadata, and wrapper hooks. Test on framework 2.0 and current 2.3 behavior, document the compatibility range, and resolve the remaining PAD/type and lifecycle gaps before release. |
| P0-I/V | Boot/status/data-slot command flow | **Integrated and focused-simulated; wrapper/hardware pending** | `0082` now captures the documented full 48-bit expected length, and separate read/write results preserve `0` ready, `1` never, and `2` later ([`core_bridge_cmd.v`](src/fpga/core/core_bridge_cmd.v), [`apf_dataslot_guard.sv`](src/fpga/core/apf_dataslot_guard.sv)). The integrated startup path holds requirements through `008F`, delivered receipt of `0090`, metadata/table publication, and loader/initializer readiness; the sequencer issues target `0140` once, while the command handler keeps Pocket-visible status in Setup until acknowledgement and requires `0011` before Running. An early `0011` remains busy and holds reset, and a new title invalidates the preceding title's acknowledgement ([`apf_startup_sequencer.sv`](src/fpga/core/apf_startup_sequencer.sv), [`core_top.v`](src/fpga/core/core_top.v)). Shutdown `0080` returns retry until `reset_n=0`, the synchronized execution level is stopped, and a fixed 31-`clk_74a` drain guard has elapsed. Focused command, guard, sequencer, and source-contract tests cover results, readiness transitions, ordering, and target acknowledgement. | Keep the focused gates green and exercise the same order through the compiled full wrapper. Hardware gate: Setup -> `008F` -> delivered `0090` plus metadata/table/init readiness -> acknowledged `0140` -> Idle -> `0011` -> Running, with Reset Enter holding execution stopped through final nonvolatile read. |
| P0-V | RTC host command `0090` | **Command and CDC compliant in focused simulation; persistence hardware pending** | `0090` captures epoch/date/time, pulses `rtc_valid` for exactly one bridge clock, and returns OK ([`core_bridge_cmd.v:388-396`](src/fpga/core/core_bridge_cmd.v#L388-L396)); the command bench locks all three payload words. An acknowledged bundled-data CDC now holds the epoch stable, rejects rather than overwrites an in-flight event, and emits one coherent console-domain pulse; its asynchronous-clock bench delivers six boundary-pattern payloads with no tear, duplicate, or loss ([`apf_rtc_cdc.sv`](src/fpga/core/apf_rtc_cdc.sv)). The console consumes the synchronized valid edge, resets per-title trailer state, and emits `RTC_load` once only after the current timestamp and validated trailer are both ready ([`wonderswan.sv:288-370`](src/fpga/core/wonderswan.sv#L288-L370), [`wonderswan.sv:621-700`](src/fpga/core/wonderswan.sv#L621-L700)). | Keep the command/CDC gates green. Pocket gate: RTC and non-RTC cartridges across cold boot, quit/relaunch, title reload, power cycle, sleep/wake, and minute/day crossings preserve the intended clock and never append or reuse a trailer for the wrong title. |
| P0-I/V | Nonvolatile slot flags and bounds | **Integrated source contract and focused RTL/CDC verified; wrapper/hardware pending** | Save slot 11 is cloned from slot 0, nonvolatile, restart-on-reload (`0x84`), dynamic, and capped at `512 KiB + 12` ([`data.json`](dist/Cores/agg23.WonderSwan/data.json)). Canonical payloads are `0/32K/128K/256K/512K` for none/SRAM and `128/2048/1024` for EEPROM `10/20/50`, plus an exact 12-byte trailer only when the footer declares RTC. Footer metadata crosses atomically to `clk_74a`; after `008F`, table index 3 / ID 11 is published as payload plus optional trailer and remains valid across Reset Enter for shutdown flush ([`apf_save_metadata_cdc.sv`](src/fpga/core/apf_save_metadata_cdc.sv), [`core_top.v`](src/fpga/core/core_top.v)). The guard returns `2` while slot-11 metadata is not ready, then accepts only absent, canonical, or the supported 2,060-byte legacy RTC EEPROM layout and returns `1` for type-inconsistent/malformed lengths. Initialization and legacy-loader benches cover absent/loaded data and exact type capacities. | Keep the guard, metadata CDC, table-publication, initialization, and legacy-loader gates green. Full-wrapper and Pocket gates still require every type with absent, exact, short, legacy, oversized, malformed-RTC, title reload, quit, restart, power-off, and flush cases; Memories/Sleep remain disabled and are not inferred from this work. |
| P0-I/V | Legacy save migration | **Converters and runtime rejection/compatibility implemented; hardware survival pending** | Non-destructive converters validate checksummed ROM footers and exact inherited layouts, then atomically create new paths without overwrite: type `0x01` expands 8,204 bytes to 32,780, while padded type `0x10`/`0x50` saves shrink from 2,060 bytes to 140/1,036 by preserving the exact EEPROM payload and relocating the opaque RTC trailer ([`migrate_type01_save.py`](scripts/migrate_type01_save.py), [`migrate_legacy_eeprom_save.py`](scripts/migrate_legacy_eeprom_save.py)). Focused tests cover hashes, determinism, wrong types/checksums/lengths, aliases, and existing destinations. Once footer metadata is ready, the integrated guard rejects the obsolete type-`01` length with result `1`; it accepts 2,060-byte type-`10`/`50` only as the documented padded RTC compatibility case, and runtime publication remains canonical. | Keep the original-file-preserving converters and fail-closed guard tests green. Prove migrated files survive play/quit/reload on Pocket, including type-`01` addresses above `0x1fff` remaining distinct and both external-EEPROM RTC trailers retaining time. A Pocket-visible diagnostic for rejected legacy type-`01` would improve first-class UX but is not yet implemented. |
| P0-I/V | Memories and `00A0`/`00A4` | **Command compliant in focused simulation; feature safely disabled** | The handler implements the documented query/result states for save and load ([`core_bridge_cmd.v:397-440`](src/fpga/core/core_bridge_cmd.v#L397-L440)). A strict command bench covers A0/A4 fields, supported and unsupported states, idle/busy/done/error with `error > done > busy > idle`, request hold through acknowledgement, mutual exclusion, result sampling, and deassertion. Top-level now reports unsupported despite retaining the controller and fixed address/size for development ([`core_top.v`](src/fpga/core/core_top.v)). The bridge/FIFO controller produces ack/busy/ok transitions ([`save_state_controller.sv:255-320`](src/fpga/core/save_state_controller.sv#L255-L320), [`save_state_controller.sv:322-368`](src/fpga/core/save_state_controller.sv#L322-L368)), but the blob has no visible magic/version/length compatibility contract. | Keep support disabled and the command gate green until bridge copy/load/repeat, reset/menu interruption, malformed/short/long blobs, and a stable state-format contract pass end to end. Pocket gate: mono/color, SRAM/EEPROM/RTC, both orientations, fast-forward, audio activity, sleep/wake, and an older-release Memory. |
| P0-D | Sleep/wake claim | **Correctly disabled; certification still open** | `sleep_supported` is false, top-level reports savestates unsupported, and README/info explicitly say Memories and Sleep + Wake are disabled pending validation ([`core.json:13-20`](dist/Cores/agg23.WonderSwan/core.json#L13-L20), [`README.md:91-94`](README.md#L91-L94), [`info.txt`](dist/Cores/agg23.WonderSwan/info.txt)). The repository also says this branch has not been validated on Pocket ([`README.md:29-31`](README.md#L29-L31)). | Re-enable only after at least 50 sleep/wake cycles distributed across the state matrix above, with save-file hash/semantic checks and continued audio/video/input/RTC operation. A single successful wake is not sufficient. |
| P0-I/V | `00B8`, grayscale, and display modes | **Compliant (source and focused simulation); hardware pending** | `video.json` advertises only generic grayscale, reflective-color, and backlit-color LCD modes (`0x20`, `0x30`, `0x40`) with sharpness 3 ([`video.json:1-39`](dist/Cores/agg23.WonderSwan/video.json#L1-L39)). The handler stores the mode/request, remains busy until the applied state returns across the CDC, fails closed on X/Z, and emits `0x444D` only for active grayscale ([`core_bridge_cmd.v:445-478`](src/fpga/core/core_bridge_cmd.v#L445-L478)). Top-level synchronizes the request, applies a tested full-range 1:2:1 grayscale conversion at a frame boundary, and synchronizes the applied state back ([`core_top.v:911-999`](src/fpga/core/core_top.v#L911-L999)). Focused benches cover delayed enable/disable, exact responses, bypass, endpoints, and a 4,096-color matrix. | Keep the source gate green. Physical gate: each advertised mode on both scaler slots, transition frames, Pocket screenshots, Dock insertion/removal, and color restoration must show no unequal-channel grayscale pixel, partial-frame switch, resync, or stale mode. |
| P0-I/V | `00B2` Dock notification | **Compliant (source and focused simulation); hardware pending** | Core metadata permits Dock ([`core.json:17-20`](dist/Cores/agg23.WonderSwan/core.json#L17-L20)). The handler accepts, stores, and acknowledges `00B2`; `core_top` connects the held state, while no console behavior is intentionally conditional on Dock ([`core_bridge_cmd.v:440-478`](src/fpga/core/core_bridge_cmd.v#L440-L478), [`core_top.v:434-505`](src/fpga/core/core_top.v#L434-L505)). The focused command bench verifies set/clear without altering unknown-command behavior. | Pocket must still enter/leave Dock without reset, lost input, video resync, save corruption, or audio channel/rate change. Add Dock-specific behavior only if a demonstrated requirement emerges. |
| P1-V | `00B1` cartridge-adapter notification | **Compliant (source and focused simulation); hardware pending** | The core declares `cartridge_adapter: -1`, keeps the cartridge pins inactive, and now explicitly accepts Pocket's unconditional startup `00B1` notification as a no-op. The host-notify bench supplies representative play/power/adapter fields and proves an OK response without changing menu, Dock, or display-mode state. Reset and cartridge/BIOS download controls now have distinct `clk_mem` and `clk_sys` copies; a mutation contract rejects direct memory-domain use by system-domain logic, including the save-clear reset hold. | Keep the explicit OK response and destination-domain contract green. Pocket gate: boot and repeated title reloads must complete without a stuck command or reset, including Dock transitions and absent physical cartridge hardware. |
| P1-V | `00B0` menu behavior | **Compliant (source), hardware pending** | `00B0` is accepted and stored ([`core_bridge_cmd.v:434-438`](src/fpga/core/core_bridge_cmd.v#L434-L438)); the signal is otherwise unused ([`core_top.v:434-494`](src/fpga/core/core_top.v#L434-L494)). Officially this notification may be ignored for compatibility. | Keep the explicit OK response. Pocket gate: repeated menu entry/exit must not stick buttons, alter fast-forward, disturb audio, corrupt a Memory, or break return-to-game. Pausing in the menu is a product choice, not a protocol requirement. |
| P1-I/V | Interact readback and persistence | **Declaration-compliant; first-class UX partial** | Persistent runtime settings are all marked `writeonly`, which the official contract permits ([`interact.json:14-50`](dist/Cores/agg23.WonderSwan/interact.json#L14-L50), [`interact.json:59-143`](dist/Cores/agg23.WonderSwan/interact.json#L59-L143)). Top-level implements their writes ([`core_top.v:354-383`](src/fpga/core/core_top.v#L354-L383)), but its read mux returns zero outside command/save regions ([`core_top.v:309-328`](src/fpga/core/core_top.v#L309-L328)). | Either retain `writeonly` and prove APF JSON persistence is the sole authority, or add a read mux and remove `writeonly` so the UI reflects actual state. The latter is preferable for diagnostics and future core-driven changes. Gate: defaults arrive before reset exit, every option persists over quit/relaunch and sleep, Reset All to Defaults restores both UI and RTL, and the reset action remains momentary. |
| P1-V | Input mappings and orientation | **Partial** | One default controller exposes exactly the allowed maximum of eight mappings ([`input.json:4-50`](dist/Cores/agg23.WonderSwan/input.json#L4-L50)). The console uses only player 1's digital bits ([`core_top.v:769-814`](src/fpga/core/core_top.v#L769-L814)), which is appropriate for a one-player machine. Orientation selects scaler slot 0/1 through the documented end-of-line word ([`core_top.v:904-920`](src/fpga/core/core_top.v#L904-L920)). However, the inherited PAD wrapper discards the current controller type bits and exposes only 16 key bits ([`apf_top.v:283-304`](src/fpga/apf/apf_top.v#L283-L304), [`io_pad_controller.v:139-159`](src/fpga/apf/io_pad_controller.v#L139-L159)). | Add type propagation or prove that only Pocket/Dock gamepads reach the digital mapping; keyboard/mouse data must never be interpreted as buttons. Bench every mapping, simultaneous directions, fast-forward latch/release, auto/manual orientation, horizontal flip, and slot command placement. Pocket and Dock gates must cover built-in controls plus at least two representative wired/wireless Dock pads. |
| P1-V | Base video bus/timing | **Source appears in range; physical timing unverified** | The definition is 224x144 RGB with 0/270-degree slots ([`video.json:4-20`](dist/Cores/agg23.WonderSwan/video.json#L4-L20)). The PLL specifies 6.144 MHz for pixel clocks ([`mf_pllbase_0002.v:31-40`](src/fpga/core/mf_pllbase/mf_pllbase_0002.v#L31-L40)); the core generates 401x258 totals, about 59.34 Hz ([`wonderswan.sv:491-565`](src/fpga/core/wonderswan.sv#L491-L565)); top-level emits RGB888, DE, one-cycle sync pulses, and a 90-degree clock ([`core_top.v:885-940`](src/fpga/core/core_top.v#L885-L940)). These are inside documented APF ranges, but there is no bus-level timing assertion suite. | Add assertions for one VS/frame, one HS/line, HS-to-DE and DE-to-next-HS gaps, active 224x144, zero/reserved words outside DE except the scaler-slot command, stable RGB888, and 47-61 Hz. Gate on Pocket/Dock for both rotations, triple-buffer on/off, flicker blend modes, tearing/latency, display modes, and screenshots. |
| P1-V | Audio, 48 kHz I2S | **Compliant in focused waveform simulation; physical CDC pending** | `sound_i2s` now derives SCLK from the same accumulator event that raises MCLK, changes DAC only on falling SCLK, and emits signed stereo 16-bit samples with a one-bit I2S delay and zero spacer positions ([`sound_i2s.sv:47-72`](src/fpga/core/sound_i2s.sv#L47-L72), [`sound_i2s.sv:128-158`](src/fpga/core/sound_i2s.sv#L128-L158)). A randomized-seed 10 ms bench proves 12.288 MHz MCLK, 3.072 MHz SCLK, 48 kHz stereo, coincident clock edges, LRCK-low left/high right, asymmetric exact samples, zero startup, and all spacer bits. Top instantiates signed 16-bit stereo ([`core_top.v:1002-1015`](src/fpga/core/core_top.v#L1002-L1015)). The bench substitutes a behavioral CDC FIFO and host reset does not restart serializer phase. | Keep the waveform gate green. Quartus/hardware gates must cover the Intel FIFO, timing/overflow margins, Reset Enter/Exit phase expectations, silence, left/right tones, clipping extrema, fast-forward, menu, sleep/wake, Dock transitions, and a long run with no pops, drift, or swapped channels. |
| P1-I/V | Platform metadata, image, icon, and info | **Source metadata corrected; release polish partial** | `wonderswan` is a valid lowercase platform ID and has matching JSON ([`core.json:4-11`](dist/Cores/agg23.WonderSwan/core.json#L4-L11), [`wonderswan.json:1-8`](dist/Platforms/wonderswan.json#L1-L8)). The family platform is now named “WonderSwan,” dated to Bandai's 1999 launch, rather than mislabeling mono support as “WonderSwan Color.” The platform image is exactly `521*165*2 = 171930` bytes, matching the documented WIP dimensions. There is no optional core `icon.bin`, and release metadata intentionally remains upstream `1.0.1`/2023 until an authorized release workflow. | Add an original 36x36 author icon if desired, validate pixel format/rotation, correct any remaining `info.txt` claims, and update release version/date only from the release workflow. Gate: fresh-SD library/core-list/boot-screen inspection with no stale or misleading claims. |
| P1-V | Core/asset metadata and hardware declarations | **Mostly compliant (source)** | APF magic, target product, bitstream/Chip32 names, Dock true, link false, and cartridge power-off compatibility value `-1` are declared ([`core.json`](dist/Cores/agg23.WonderSwan/core.json)). ROM, BIOS, and save addresses are outside reserved `0xF8...` ([`data.json`](dist/Cores/agg23.WonderSwan/data.json)); top-level puts unused IR/link/cart pins into safe states. The integrated guard fixes the exact supported policy: slot 0 is write-only, power-of-two 64 KiB through the implemented 16 MiB 24-bit mapper cap; slot 9 is write-only/exact 4 KiB; slot 10 is write-only/exact 8 KiB; slot 11 read becomes ready only after Reset Enter is observed in the console plus backend quiescence, and write is size-gated as described above. WSdev documents known header sizes through 16 MiB, while the later Bandai 2003 mapper's six 1 MiB linear-bank bits imply a theoretical 64 MiB address capacity; this core does not advertise or accept that larger capacity. | Add JSON schema/unique-ID/address-overlap validation. Exercise boot with no BIOS, each BIOS independently, both, malformed files, WS/WSC extensions, minimum/maximum ROMs, and user ROM reload. Confirm cartridge/link/IR power and pin behavior on Pocket; source tie-offs alone are not an electrical measurement. |
| P1-I/V | Packaging | **Partial** | Packaging requires a nonempty current RBF, reads filenames from `core.json`, writes the per-byte bit-reversed stream, pins the Chip32 image, rejects ROM/BIOS/save leakage, and creates a deterministic ZIP ([`package_core.py:41-80`](scripts/package_core.py#L41-L80), [`package_core.py:96-140`](scripts/package_core.py#L96-L140)). Tests verify identity, deterministic ordering, expected roots, reversal, collisions, leaks, and stale-output removal ([`package_core_test.py:65-112`](scripts/package_core_test.py#L65-L112), [`package_core_test.py:152-235`](scripts/package_core_test.py#L152-L235)). It does not validate all APF JSON schemas, asset dimensions, metadata consistency, bitstream provenance, or timing results; it also packages placeholder files from `dist`. | Add a release validator and allowlist: permitted base folders only; required JSONs; APF magic/types/limits; unique IDs; references present; icon/platform dimensions; no `.gitkeep`, ROM, firmware, save, trace, report, or temporary leakage. Bind the ZIP to the exact Quartus build/report and publish hashes. Use the recommended `Author.Core_version_date.zip` name even though the inner bitstream filename `wonderswan.rev` is valid if it contains RBF_R bytes. |
| P0-I/V | Quartus bitstream and TimeQuest | **Missing release evidence** | The build script requires Quartus 21.1.1, deletes stale output, runs a full compile, and requires a nonempty RBF ([`build_core.sh:4-20`](scripts/build_core.sh#L4-L20)). The project targets Cyclone V `5CEBA4F23C8` and includes core/APF constraints ([`ap_core.qsf:289-303`](src/fpga/ap_core.qsf#L289-L303), [`apf_constraints.sdc:7-20`](src/fpga/apf/apf_constraints.sdc#L7-L20), [`core_constraints.sdc:7-16`](src/fpga/core/core_constraints.sdc#L7-L16)). No compiled release RBF or timing report is tracked in the working tree, and the build gate does not reject negative slack, unconstrained paths, critical warnings, or missing compressed-bitstream configuration. | Build in a pinned Quartus 21.1.1 environment; archive `.fit`, `.sta`, `.flow.rpt`, RBF/SOF hashes, tool version, commit, and warnings. Fail release on negative setup/hold/recovery/removal slack, unconstrained clocks/paths not explicitly waived, inferred-latch/multi-driver/CDC critical warnings, or unexpected resource/PLL changes. Confirm compressed RBF generation, then package only that accepted artifact. |
| P0-D | Pocket/Dock hardware QA and release truth | **Unverifiable here; mandatory** | Project status explicitly says hardware equivalence is not tested and requires Pocket validation ([`PHASE_STATUS.md:23-26`](PHASE_STATUS.md#L23-L26)); simulation excludes Pocket wrappers and physical SDRAM behavior ([`PHASE_STATUS.md:7-12`](PHASE_STATUS.md#L7-L12)). | Use a fresh SD card and current stable Analogue OS plus the declared minimum firmware if retained. Record device/OS/Dock versions, core ZIP/RBF SHA-256, ROM hashes from legally owned dumps, test duration, results, photos/captures where useful, and tester. Do not label the release first-class until every Gate 3 item below passes with no unexplained critical warning or data loss. |
| P2-D | Screenshots | **Unverifiable/host-owned** | Analogue says openFPGA cores [automatically support screenshots](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/changelog/1-1-beta-7); there is no core-side screenshot command or JSON integration. This core supplies the video bus on which that host feature depends. | Treat screenshot creation as an Analogue OS acceptance test, not a new RTL feature. On Pocket and Dock, capture horizontal/vertical, mono/color, each generic display mode, and both scaler slots; verify orientation, aspect, full frame, colors/grayscale, and file readability after relaunch. A failure may still reveal a video-bus or scaler-slot defect. |

## Acceptance gates

### Gate 0 — declarations and deterministic host-side checks

All must pass before building a candidate:

- APF JSON validation, unique IDs, length/range/address checks, and coherent
  framework/platform/release metadata.
- Save-slot bound and initialization policy are explicit; legacy type-`01`
  inputs cannot be silently loaded as corrected saves.
- Package tests pass twice byte-for-byte; the ZIP allowlist contains no ROM,
  BIOS, save, placeholder, trace, or temporary file.
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
- slot 0/9/10/11 direction and exact-size policy, atomic slot-11 metadata/table
  publication, canonical/legacy loaded sizes, and every supported save type;
- Interact defaults, persistence, readback policy, and Reset All to Defaults;
- PAD type plus all eight mappings and both orientation scaler slots;
- VIDEO timing assertions and exact grayscale pixels; and
- 48 kHz I2S frequency, phase, bit order, channel order, spacer, and reset.

### Gate 2 — reproducible FPGA candidate

- Clean Quartus Prime Lite 21.1.1 compile for `5CEBA4F23C8`.
- TimeQuest passes all clock domains with no negative slack and no unexplained
  unconstrained path or critical warning.
- Candidate RBF is nonempty, compressed as intended, bit-reversed once, and its
  SHA-256 is bound to the archived reports, Git commit, and final ZIP.
- Install is tested from the ZIP on a freshly prepared SD, not from loose files
  left by development.

### Gate 3 — physical Pocket and Dock release matrix

At minimum:

- cold boot/reboot/quit/relaunch with WS and WSC, no BIOS and each supported
  BIOS combination;
- every supported SRAM/EEPROM size, no-save creation, normal reload, RTC,
  corrected type-`01`, rejected legacy/short/long inputs, and save-file hashes
  before/after controlled operations;
- Memories create/load/delete and an older compatible Memory, then the repeated
  sleep/wake campaign described above;
- horizontal/vertical auto and forced modes, flip, triple buffer, all flicker
  modes, generic mono/color display modes, grayscale response, and screenshots;
- all controls, combinations, fast-forward behavior, menu enter/exit, at least
  two Dock controllers, Dock insert/remove, and loss/reacquisition of focus;
- stereo channel/frequency/listening checks across silence, extrema, menu,
  fast-forward, sleep, and at least a two-hour soak; and
- repeated launch/quit/Dock/sleep cycles with no crash, stuck reset, video loss,
  audio drift, save damage, or corrupted persistent setting.

Pass/fail evidence belongs in a dated release report. “Booted once” is not a
substitute for this matrix.

## Deliberately deferred or optional items

- A core author `icon.bin` is optional in the official packaging docs; it is
  release polish, not a blocker.
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

Accessed **2026-07-13**. The live Analogue developer pages are the normative APF
contract; dated archive links are retained only where useful for older
changelog history.

- [Analogue changelog 2.3](https://web.archive.org/web/20260412064744/https://www.analogue.co/developer/docs/changelog/2-3) — framework 2.3 and current display-mode changes.
- [Analogue changelog 1.1 beta 7](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/changelog/1-1-beta-7) — automatic openFPGA screenshots and their Memories integration.
- [Analogue `core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json) — minimum firmware, sleep, Dock, hardware, and bitstream declarations.
- [Analogue `data.json`](https://www.analogue.co/developer/docs/core-definition-files/data-json) — slot flags, bounds, nonvolatile flush, and dynamic sizes.
- [Analogue `interact.json`](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/core-definition-files/interact-json) — frame read-modify-write, `writeonly`, IDs, and persistence.
- [Analogue `input.json`](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/core-definition-files/input-json) — four-controller/eight-mapping limits.
- [Analogue `video.json`](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/core-definition-files/video-json) — scaler/display modes and grayscale LCD behavior.
- [Analogue bus communication](https://www.analogue.co/developer/docs/bus-communication) — BRIDGE, PAD, VIDEO, and exact 48 kHz I2S requirements.
- [Analogue host/target commands](https://www.analogue.co/developer/docs/host-target-commands) — 48-bit `0082`, results `0/1/2`, the data-slot table, `008F`, `0090`, target `0140`, and runtime notifications.
- [Analogue core boot process](https://www.analogue.co/developer/docs/core-boot-process) — the Setup -> slot loads -> `008F` -> `0090` -> acknowledged `0140`/Idle -> `0011`/Running sequence and shutdown flush.
- [Analogue platform metadata](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/platform-metadata) — platform IDs, JSON, and image location.
- [Analogue packaging](https://web.archive.org/web/20260412022658/https://www.analogue.co/developer/docs/packaging-a-core) — ZIP layout, RBF_R conversion, platform art, and optional icon.
- [Analogue SD directory structure](https://web.archive.org/web/20260425052517/https://www.analogue.co/developer/docs/directories-and-sd-folder-structure) — Assets, Saves, Settings, and up to 128 Memories per core.
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
