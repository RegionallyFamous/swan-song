# Analogue Pocket first-class compliance matrix

Last audited: **2026-07-13**
Repository baseline: `9f93a62937167ab54bd4f006996eeeb3e920aa89` on `codex/swan-song`

This is a source-and-evidence audit, not a hardware certification. The working
tree after the baseline snapshot integrates host notifications `00B2` and
`00B8`, clock-domain-safe frame-boundary grayscale, Pocket's required `0x444D`
affirmation, generic LCD modes, and focused APF simulations. Those paths are
source-verified below but still require Quartus and physical Pocket/Dock gates.

## Verdict

The repository is a strong functional-development tree, but it is **not yet a
first-class Pocket release**. The deterministic console regression and package
builder are valuable evidence; they do not prove the APF boundary, Quartus
timing closure, save/sleep behavior on Analogue OS, or Dock operation.

Release blockers, in order:

1. Make the dynamic nonvolatile save lifecycle fail-safe, including legacy
   type-`01` detection/migration and missing/truncated/oversized-file behavior.
2. Prove the `00A0`/`00A4` state machine on Pocket before continuing to declare
   `sleep_supported: true` or advertise Memories and sleep/wake.
3. Add the remaining APF-boundary simulations for boot, host commands,
   data-table updates,
   Interact persistence, video, audio, and controller type handling.
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
| P0-I | Framework level and APF baseline | **Partial** | The core declares APF v1 metadata and now requires framework `2.0`, the version that introduced display modes and `00B8`, while enabling sleep and Dock ([`core.json:3-25`](dist/Cores/agg23.WonderSwan/core.json#L3-L25)). Analogue's current changelog says the framework is `2.3`; the public `core-template` is still a 2023 v1.3.0 reference that declares `1.1`, so it is not the current protocol authority. The local PAD wrapper also retains the old 16-bit key interface ([`io_pad_controller.v:41-59`](src/fpga/apf/io_pad_controller.v#L41-L59)). | Treat `version_required` as the minimum actually needed, not a marketing version. The host-definition contract now binds `2.0`, the generic modes, slot limits, metadata, and wrapper hooks. Test on framework 2.0 and current 2.3 behavior, document the compatibility range, and resolve the remaining PAD/type and lifecycle gaps before release. |
| P0-I/V | Boot/status/data-slot command flow | **Partial** | The handler implements status, reset, `0080`, `0082`, `008A`, and `008F` ([`core_bridge_cmd.v:323-380`](src/fpga/core/core_bridge_cmd.v#L323-L380)), and raises target `0140` from the setup edge ([`core_bridge_cmd.v:490-550`](src/fpga/core/core_bridge_cmd.v#L490-L550)). Top-level `status_boot_done` and `status_setup_done` are both only PLL lock, and data-slot read/write requests are acknowledged immediately ([`core_top.v:395-411`](src/fpga/core/core_top.v#L395-L411)). Chip32 loads ROM, optional firmware paths, and save before `HOST 4002` ([`chip32.asm:60-92`](src/support/chip32.asm#L60-L92)). | Simulate the official startup and shutdown ordering, including delayed PLL/RAM readiness, absent optional slots, failed loads, reset enter/exit, `008F`, RTC, `0140`, Interact writes, and nonvolatile unload. Acknowledgements must describe actual readiness, not constants. Gate: no run transition before all required writes and CDC-backed loaders complete; shutdown holds reset through the final save read. |
| P0-V | RTC host command `0090` | **Partial** | `0090` captures epoch/date/time and returns OK ([`core_bridge_cmd.v:381-389`](src/fpga/core/core_bridge_cmd.v#L381-L389)); the console receives the epoch ([`core_top.v:413-475`](src/fpga/core/core_top.v#L413-L475), [`core_top.v:779-801`](src/fpga/core/core_top.v#L779-L801)). RTC save/load logic appends a 12-byte record, but `has_rtc` is forced true for every game ([`wonderswan.sv:614-683`](src/fpga/core/wonderswan.sv#L614-L683)). | Add a command bench for all three words and an RTC lifecycle test across no-RTC and RTC cartridges. Gate on Pocket: cold boot time, quit/relaunch, power cycle, sleep/wake, and a long enough run to cross minute/day boundaries preserve the intended game clock and trailer without modifying non-RTC save data. |
| P0-I/V | Nonvolatile slot flags and bounds | **Partial; release blocker** | Save slot 11 is cloned from slot 0, nonvolatile, and restart-on-reload (`0x84`), but has no `size_maximum` and does not request APF initialization ([`data.json:31-39`](dist/Cores/agg23.WonderSwan/data.json#L31-L39)). The core supports dynamic sizes from 2 KiB through 512 KiB plus a 12-byte trailer ([`wonderswan.sv:619-638`](src/fpga/core/wonderswan.sv#L619-L638)). It continuously writes slot-index 3's final size into the APF table ([`core_top.v:681-698`](src/fpga/core/core_top.v#L681-L698)) and has bridge load/unload paths at `0x2...` ([`core_top.v:609-663`](src/fpga/core/core_top.v#L609-L663)). | Add the true upper bound (`512 KiB + 12` bytes) and make missing-save initialization explicit. Bit 5 is one valid APF policy only if `0xFF` is the chosen hardware-compatible initial state; otherwise retain core-owned initialization and prove it. Capture the host-loaded length before overwriting the table, compare it with the cartridge header's required type/size, reject or migrate invalid files, and publish the final size only after the header is known. Gate all supported RAM/EEPROM types with absent, exact, short, legacy, oversized, malformed-RTC, quit, restart, and power/sleep flush cases. |
| P0-I/V | Legacy save migration | **Partial; release blocker** | A non-destructive converter validates a checksummed type-`01` ROM and the exact legacy 8,204-byte layout, then creates a 32,780-byte result without overwrite ([`migrate_type01_save.py:18-38`](scripts/migrate_type01_save.py#L18-L38), [`migrate_type01_save.py:97-125`](scripts/migrate_type01_save.py#L97-L125)); user instructions exist ([`BUILDING.md:170-190`](BUILDING.md#L170-L190)). The runtime loader does not identify this old file before loading slot 11 ([`chip32.asm:78-92`](src/support/chip32.asm#L78-L92)). | Keep the converter, but add runtime fail-closed detection and a user-facing migration error; silently treating 8 KiB as a corrected 32 KiB save is unacceptable. If automatic conversion is added, preserve the original and RTC trailer atomically. Gate: wrong ROM type/checksum, aliases, existing destination, short/long files, and interrupted publication never alter the source; a migrated file survives play/quit/reload with addresses above `0x1fff` distinct. |
| P0-I/V | Memories and `00A0`/`00A4` | **Partial; release blocker** | The handler returns supported/address/size and the documented result states for save and load ([`core_bridge_cmd.v:390-433`](src/fpga/core/core_bridge_cmd.v#L390-L433)). Support is hard-wired true at a fixed `0x40000000` and `0x90200`, while maximum load is inexplicably 4 KiB larger ([`core_top.v:415-432`](src/fpga/core/core_top.v#L415-L432)). The bridge/FIFO controller produces ack/busy/ok transitions ([`save_state_controller.sv:255-320`](src/fpga/core/save_state_controller.sv#L255-L320), [`save_state_controller.sv:322-368`](src/fpga/core/save_state_controller.sv#L322-L368)), but the blob has no visible magic/version/length compatibility contract. | Add protocol tests for query, start, polling, bridge copy, load, repeat operations, reset/menu interruption, and malformed/short/long blobs. Define a stable state-format version or a strict compatible-size policy and return error rather than hanging or accepting unknown state. Justify or remove the extra 4 KiB load allowance. Gate on Pocket across mono/color, SRAM/EEPROM/RTC, horizontal/vertical, fast-forward, and audio activity; load an older release Memory explicitly. |
| P0-D | Sleep/wake claim | **Unverifiable here; currently over-claimed** | `sleep_supported` is true ([`core.json:13-20`](dist/Cores/agg23.WonderSwan/core.json#L13-L20)); `info.txt` and README advertise Memories/sleep behavior ([`info.txt:5-9`](dist/Cores/agg23.WonderSwan/info.txt#L5-L9), [`README.md:54-58`](README.md#L54-L58)). The repository itself says this branch has not been validated on Pocket ([`README.md:29-31`](README.md#L29-L31)). | Until the physical gate passes, set `sleep_supported` false and remove the sleep claim, or keep the feature off release builds. Required evidence: at least 50 sleep/wake cycles distributed across the state matrix above, including low battery/power transitions, followed by save-file hash/semantic checks and continued audio/video/input/RTC operation. A single successful wake is not sufficient. |
| P0-I/V | `00B8`, grayscale, and display modes | **Compliant (source and focused simulation); hardware pending** | `video.json` advertises only generic grayscale, reflective-color, and backlit-color LCD modes (`0x20`, `0x30`, `0x40`) with sharpness 3 ([`video.json:1-39`](dist/Cores/agg23.WonderSwan/video.json#L1-L39)). The handler stores the mode/request, remains busy until the applied state returns across the CDC, fails closed on X/Z, and emits `0x444D` only for active grayscale ([`core_bridge_cmd.v:445-478`](src/fpga/core/core_bridge_cmd.v#L445-L478)). Top-level synchronizes the request, applies a tested full-range 1:2:1 grayscale conversion at a frame boundary, and synchronizes the applied state back ([`core_top.v:911-999`](src/fpga/core/core_top.v#L911-L999)). Focused benches cover delayed enable/disable, exact responses, bypass, endpoints, and a 4,096-color matrix. | Keep the source gate green. Physical gate: each advertised mode on both scaler slots, transition frames, Pocket screenshots, Dock insertion/removal, and color restoration must show no unequal-channel grayscale pixel, partial-frame switch, resync, or stale mode. |
| P0-I/V | `00B2` Dock notification | **Compliant (source and focused simulation); hardware pending** | Core metadata permits Dock ([`core.json:17-20`](dist/Cores/agg23.WonderSwan/core.json#L17-L20)). The handler accepts, stores, and acknowledges `00B2`; `core_top` connects the held state, while no console behavior is intentionally conditional on Dock ([`core_bridge_cmd.v:440-478`](src/fpga/core/core_bridge_cmd.v#L440-L478), [`core_top.v:434-505`](src/fpga/core/core_top.v#L434-L505)). The focused command bench verifies set/clear without altering unknown-command behavior. | Pocket must still enter/leave Dock without reset, lost input, video resync, save corruption, or audio channel/rate change. Add Dock-specific behavior only if a demonstrated requirement emerges. |
| P1-V | `00B0` menu behavior | **Compliant (source), hardware pending** | `00B0` is accepted and stored ([`core_bridge_cmd.v:434-438`](src/fpga/core/core_bridge_cmd.v#L434-L438)); the signal is otherwise unused ([`core_top.v:434-494`](src/fpga/core/core_top.v#L434-L494)). Officially this notification may be ignored for compatibility. | Keep the explicit OK response. Pocket gate: repeated menu entry/exit must not stick buttons, alter fast-forward, disturb audio, corrupt a Memory, or break return-to-game. Pausing in the menu is a product choice, not a protocol requirement. |
| P1-I/V | Interact readback and persistence | **Declaration-compliant; first-class UX partial** | Persistent runtime settings are all marked `writeonly`, which the official contract permits ([`interact.json:14-50`](dist/Cores/agg23.WonderSwan/interact.json#L14-L50), [`interact.json:59-143`](dist/Cores/agg23.WonderSwan/interact.json#L59-L143)). Top-level implements their writes ([`core_top.v:354-383`](src/fpga/core/core_top.v#L354-L383)), but its read mux returns zero outside command/save regions ([`core_top.v:309-328`](src/fpga/core/core_top.v#L309-L328)). | Either retain `writeonly` and prove APF JSON persistence is the sole authority, or add a read mux and remove `writeonly` so the UI reflects actual state. The latter is preferable for diagnostics and future core-driven changes. Gate: defaults arrive before reset exit, every option persists over quit/relaunch and sleep, Reset All to Defaults restores both UI and RTL, and the reset action remains momentary. |
| P1-V | Input mappings and orientation | **Partial** | One default controller exposes exactly the allowed maximum of eight mappings ([`input.json:4-50`](dist/Cores/agg23.WonderSwan/input.json#L4-L50)). The console uses only player 1's digital bits ([`core_top.v:769-814`](src/fpga/core/core_top.v#L769-L814)), which is appropriate for a one-player machine. Orientation selects scaler slot 0/1 through the documented end-of-line word ([`core_top.v:904-920`](src/fpga/core/core_top.v#L904-L920)). However, the inherited PAD wrapper discards the current controller type bits and exposes only 16 key bits ([`apf_top.v:283-304`](src/fpga/apf/apf_top.v#L283-L304), [`io_pad_controller.v:139-159`](src/fpga/apf/io_pad_controller.v#L139-L159)). | Add type propagation or prove that only Pocket/Dock gamepads reach the digital mapping; keyboard/mouse data must never be interpreted as buttons. Bench every mapping, simultaneous directions, fast-forward latch/release, auto/manual orientation, horizontal flip, and slot command placement. Pocket and Dock gates must cover built-in controls plus at least two representative wired/wireless Dock pads. |
| P1-V | Base video bus/timing | **Source appears in range; physical timing unverified** | The definition is 224x144 RGB with 0/270-degree slots ([`video.json:4-20`](dist/Cores/agg23.WonderSwan/video.json#L4-L20)). The PLL specifies 6.144 MHz for pixel clocks ([`mf_pllbase_0002.v:31-40`](src/fpga/core/mf_pllbase/mf_pllbase_0002.v#L31-L40)); the core generates 401x258 totals, about 59.34 Hz ([`wonderswan.sv:491-565`](src/fpga/core/wonderswan.sv#L491-L565)); top-level emits RGB888, DE, one-cycle sync pulses, and a 90-degree clock ([`core_top.v:885-940`](src/fpga/core/core_top.v#L885-L940)). These are inside documented APF ranges, but there is no bus-level timing assertion suite. | Add assertions for one VS/frame, one HS/line, HS-to-DE and DE-to-next-HS gaps, active 224x144, zero/reserved words outside DE except the scaler-slot command, stable RGB888, and 47-61 Hz. Gate on Pocket/Dock for both rotations, triple-buffer on/off, flicker blend modes, tearing/latency, display modes, and screenshots. |
| P1-V | Audio, 48 kHz I2S | **Source-intent compliant; waveform unverified** | `sound_i2s` targets 12.288 MHz MCLK, divides to 3.072 MHz SCLK, sends signed stereo 16-bit samples plus 16 spacer bits per channel, and reloads after the LRCK transition ([`sound_i2s.sv:47-72`](src/fpga/core/sound_i2s.sv#L47-L72), [`sound_i2s.sv:76-111`](src/fpga/core/sound_i2s.sv#L76-L111), [`sound_i2s.sv:129-156`](src/fpga/core/sound_i2s.sv#L129-L156)). Top instantiates signed 16-bit stereo ([`core_top.v:945-958`](src/fpga/core/core_top.v#L945-L958)). No test measures long-run frequency, channel order, one-bit I2S delay, reset startup, spacer zeros, or CDC behavior. | Add a self-checking waveform test using asymmetric signed samples. Over a long window require 256 MCLK and 64 SCLK per 48 kHz frame, LRCK-low left/high right, one-bit delay, MSB first, 16 zero spacer bits, no rate modulation, and bounded CDC behavior. Pocket/Dock gate: silence, left/right test tones, clipping extrema, fast-forward mute/on, menu, sleep/wake, and a long run with no pops, drift, or swapped channels. |
| P1-I/V | Platform metadata, image, icon, and info | **Source metadata corrected; release polish partial** | `wonderswan` is a valid lowercase platform ID and has matching JSON ([`core.json:4-11`](dist/Cores/agg23.WonderSwan/core.json#L4-L11), [`wonderswan.json:1-8`](dist/Platforms/wonderswan.json#L1-L8)). The family platform is now named “WonderSwan,” dated to Bandai's 1999 launch, rather than mislabeling mono support as “WonderSwan Color.” The platform image is exactly `521*165*2 = 171930` bytes, matching the documented WIP dimensions. There is no optional core `icon.bin`, and release metadata intentionally remains upstream `1.0.1`/2023 until an authorized release workflow. | Add an original 36x36 author icon if desired, validate pixel format/rotation, correct any remaining `info.txt` claims, and update release version/date only from the release workflow. Gate: fresh-SD library/core-list/boot-screen inspection with no stale or misleading claims. |
| P1-V | Core/asset metadata and hardware declarations | **Mostly compliant (source)** | APF magic, target product, bitstream/Chip32 names, Dock true, link false, and cartridge power-off compatibility value `-1` are declared ([`core.json:3-32`](dist/Cores/agg23.WonderSwan/core.json#L3-L32)). ROM, BIOS, and save addresses are outside reserved `0xF8...` ([`data.json:4-39`](dist/Cores/agg23.WonderSwan/data.json#L4-L39)); top-level puts unused IR/link/cart pins into safe states ([`core_top.v:227-259`](src/fpga/core/core_top.v#L227-L259)). | Add JSON length/range/unique-ID/address-overlap validation and exact supported BIOS-size policy. Exercise boot with no BIOS, each BIOS independently, both, malformed files, WS/WSC extensions, and user ROM reload. Confirm cartridge/link/IR power and pin behavior on Pocket; source tie-offs alone are not an electrical measurement. |
| P1-I/V | Packaging | **Partial** | Packaging requires a nonempty current RBF, reads filenames from `core.json`, writes the per-byte bit-reversed stream, pins the Chip32 image, rejects ROM/BIOS/save leakage, and creates a deterministic ZIP ([`package_core.py:41-80`](scripts/package_core.py#L41-L80), [`package_core.py:96-140`](scripts/package_core.py#L96-L140)). Tests verify identity, deterministic ordering, expected roots, reversal, collisions, leaks, and stale-output removal ([`package_core_test.py:65-112`](scripts/package_core_test.py#L65-L112), [`package_core_test.py:152-235`](scripts/package_core_test.py#L152-L235)). It does not validate all APF JSON schemas, asset dimensions, metadata consistency, bitstream provenance, or timing results; it also packages placeholder files from `dist`. | Add a release validator and allowlist: permitted base folders only; required JSONs; APF magic/types/limits; unique IDs; references present; icon/platform dimensions; no `.gitkeep`, ROM, firmware, save, trace, report, or temporary leakage. Bind the ZIP to the exact Quartus build/report and publish hashes. Use the recommended `Author.Core_version_date.zip` name even though the inner bitstream filename `wonderswan.rev` is valid if it contains RBF_R bytes. |
| P0-I/V | Quartus bitstream and TimeQuest | **Missing release evidence** | The build script requires Quartus 21.1.1, deletes stale output, runs a full compile, and requires a nonempty RBF ([`build_core.sh:4-20`](scripts/build_core.sh#L4-L20)). The project targets Cyclone V `5CEBA4F23C8` and includes core/APF constraints ([`ap_core.qsf:289-303`](src/fpga/ap_core.qsf#L289-L303), [`apf_constraints.sdc:7-20`](src/fpga/apf/apf_constraints.sdc#L7-L20), [`core_constraints.sdc:7-16`](src/fpga/core/core_constraints.sdc#L7-L16)). No compiled release RBF or timing report is tracked in the working tree, and the build gate does not reject negative slack, unconstrained paths, critical warnings, or missing compressed-bitstream configuration. | Build in a pinned Quartus 21.1.1 environment; archive `.fit`, `.sta`, `.flow.rpt`, RBF/SOF hashes, tool version, commit, and warnings. Fail release on negative setup/hold/recovery/removal slack, unconstrained clocks/paths not explicitly waived, inferred-latch/multi-driver/CDC critical warnings, or unexpected resource/PLL changes. Confirm compressed RBF generation, then package only that accepted artifact. |
| P0-D | Pocket/Dock hardware QA and release truth | **Unverifiable here; mandatory** | Project status explicitly says hardware equivalence is not tested and requires Pocket validation ([`PHASE_STATUS.md:22-25`](PHASE_STATUS.md#L22-L25)); simulation excludes Pocket wrappers and physical SDRAM behavior ([`PHASE_STATUS.md:7-12`](PHASE_STATUS.md#L7-L12)). | Use a fresh SD card and current stable Analogue OS plus the declared minimum firmware if retained. Record device/OS/Dock versions, core ZIP/RBF SHA-256, ROM hashes from legally owned dumps, test duration, results, photos/captures where useful, and tester. Do not label the release first-class until every Gate 3 item below passes with no unexplained critical warning or data loss. |
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

- boot/status/reset/`0080`/`0082`/`008A`/`008F`/`0090`/`0140` ordering;
- `00A0` and `00A4` query, request, busy, done, error, malformed length, and
  repeated save/load sequences;
- `00B0`, `00B2`, and `00B8`, including cross-clock synchronization and a
  fail-closed grayscale acknowledgement;
- dynamic slot-11 loaded/final sizes and every supported save type;
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

Accessed **2026-07-13**. Analogue's live legacy documentation routes were not a
stable citation target during the audit, so the links below are timestamped
Internet Archive snapshots of Analogue's own official pages. They preserve the
current official text and are preferable to secondary summaries.

- [Analogue changelog 2.3](https://web.archive.org/web/20260412064744/https://www.analogue.co/developer/docs/changelog/2-3) — framework 2.3 and current display-mode changes.
- [Analogue changelog 1.1 beta 7](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/changelog/1-1-beta-7) — automatic openFPGA screenshots and their Memories integration.
- [Analogue `core.json`](https://web.archive.org/web/20260224180301/https://www.analogue.co/developer/docs/core-definition-files/core-json) — minimum firmware, sleep, Dock, hardware, and bitstream declarations.
- [Analogue `data.json`](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/core-definition-files/data-json) — slot flags, bounds, nonvolatile flush, and dynamic sizes.
- [Analogue `interact.json`](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/core-definition-files/interact-json) — frame read-modify-write, `writeonly`, IDs, and persistence.
- [Analogue `input.json`](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/core-definition-files/input-json) — four-controller/eight-mapping limits.
- [Analogue `video.json`](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/core-definition-files/video-json) — scaler/display modes and grayscale LCD behavior.
- [Analogue bus communication](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/bus-communication) — BRIDGE, PAD, VIDEO, and exact 48 kHz I2S requirements.
- [Analogue host/target commands](https://web.archive.org/web/20260414192744/https://www.analogue.co/developer/docs/host-target-commands) — `0090`, `00A0`, `00A4`, `00B0`, `00B2`, `00B8`, and `0x444D`.
- [Analogue core boot process](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/core-boot-process) — startup/runtime/shutdown sequencing.
- [Analogue platform metadata](https://web.archive.org/web/20260412064743/https://www.analogue.co/developer/docs/platform-metadata) — platform IDs, JSON, and image location.
- [Analogue packaging](https://web.archive.org/web/20260412022658/https://www.analogue.co/developer/docs/packaging-a-core) — ZIP layout, RBF_R conversion, platform art, and optional icon.
- [Analogue SD directory structure](https://web.archive.org/web/20260425052517/https://www.analogue.co/developer/docs/directories-and-sd-folder-structure) — Assets, Saves, Settings, and up to 128 Memories per core.

Primary implementation reference, accessed **2026-07-13**:

- [`open-fpga/core-template` v1.3.0 tip `da3a021...`, `core.json`](https://github.com/open-fpga/core-template/blob/da3a021b1eaf742604d86d8dc9b33a6666263e6a/core.json#L13-L30)
- [`open-fpga/core-template` host-command handler](https://github.com/open-fpga/core-template/blob/da3a021b1eaf742604d86d8dc9b33a6666263e6a/src/fpga/core/core_bridge_cmd.v#L393-L450)

The template is useful provenance for the inherited wrapper and `0090`/`00A0`/
`00A4`/`00B0` implementation. Its last commit is from 2023 and it lacks current
`00B2`/`00B8` handling, so the current Analogue protocol documentation above is
normative where they differ.
