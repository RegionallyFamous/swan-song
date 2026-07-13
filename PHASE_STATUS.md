# Roadmap status

## Phase 0 — faithful rebuild

| Item | Status | Evidence |
| --- | --- | --- |
| History-preserving Pocket fork | Complete | current branch is based at Pocket `1.0.1` / `073213a2` and retains its ancestry |
| Upstream pins and license audit | Provenance complete; release clearance open | `UPSTREAMS.md`; MiSTer program notice is GPL v2-or-later and is version-compatible with GPL-v3-or-later RTL, but Pocket omitted that notice and the tree lacks a GPL v3 license copy |
| Architecture and port boundary | Complete | `ARCHITECTURE.md`, `PORTING.md` |
| System simulation | Implemented for open tests | deterministic GPU-framebuffer hashes for two checked-in MiSTer tests, Wonderful's mono 80186-quirks, SoC-interrupt, internal-EEPROM, WSC extended-range, and Color Sound-DMA fixtures, the native Shift-JIS/Misaki glyph fixture, paired build-generated planar/packed 4bpp and type-01/type-02 32 KiB SRAM probes, build-generated Color sprite-priority, interrupt/input, and Sound-DMA modes probes, plus direct DMA/EEPROM/APF arbitration, boot/status/data-slot/RTC, full-48-bit size/result guard, startup sequencer, save-metadata CDC/table publication, A0/A4 commands, display-mode, I2S-waveform, and save-state tests via `make regression`; a pinned Wonderful `initfini` pass is recorded in `WONDERFUL_VALIDATION.md`; generated probe binaries are not checked in; physical SDRAM and Pocket hardware remain outside this harness |
| APF lifecycle and slot contract | Integrated source path and focused simulation verified; compiled wrapper/Pocket open | `0082` preserves the full 48-bit byte count and independent `0` ready / `1` never / `2` later results; the guard enforces exact slot 0/9/10/11/12/13 directions and lengths, including bidirectional 128-byte mono and 2,048-byte Color console EEPROM; startup remains in Setup through `008F`, delivered `0090`, metadata/table publication, and both cartridge/console initialization, then requires Pocket acknowledgement of target `0140` before Idle and `0011` before Running; early Reset Exit stays busy/reset and a new title invalidates the preceding title's acknowledgement; shutdown `0080` returns `2` until `reset_n=0`, synchronized execution has stopped, and a fixed 31-`clk_74a` drain guard has elapsed; contracts match Analogue's [boot](https://www.analogue.co/developer/docs/core-boot-process), [commands](https://www.analogue.co/developer/docs/host-target-commands), [`data.json`](https://www.analogue.co/developer/docs/core-definition-files/data-json), [`core.json`](https://www.analogue.co/developer/docs/core-definition-files/core-json), and [bus](https://www.analogue.co/developer/docs/bus-communication) documentation; no physical validation is claimed |
| Pocket launch and package truth | Definition and host-side contracts aligned; physical UX pending | slot 0 now uses the documented persistent-browser plus full-reload parameters, so a normal launch is expected to reuse the last title while Core Settings > Cartridge still performs a shutdown/save flush and clean title reload; Pocket's Startup Action can open openFPGA at power-on, but no documented public APF mechanism adds this core or its games to the first-party Library; firmware 2.6.0 adds a host-owned Recent category and returns quit to the openFPGA menu, but public APF exposes no supported pin/preseed hook; framework 2.3 is required for its corrected **Reset all to defaults** browser-history behavior; the current Chip32 program queries and loads both BIOS files on every launch, so slots 9/10 are `required: true`, read-only, and persistent-browser assets with APF `size_exact` 4,096/8,192 plus the independent RTL guards; the nonpersistent **Console Setup** action recreates the original BIOS owner-registration gesture (hold Start at power-on) with a 1,048,576-cycle reset plus 33,554,432-cycle forced-Start sequencer, independent three-stage CDC levels, retrigger, and host-reset cancellation; forced Start is ORed only at logical Start and does not change Display Orientation; the advertised openFPGA boundary is `.ws`/`.wsc` SD-card assets with user-supplied BIOS, not Pocket's physical-cartridge/Library path; cartridge power remains off and link/cartridge pins are unused; the system menu exposes only Auto/WonderSwan/WonderSwan Color because PocketChallenge v2 behavior is not implemented; package and first-class contract tests bind these claims, but Recent/relaunch, prompts, title-switch save integrity, menus, presentation, and Dock behavior still need hardware validation |
| Per-asset APF presets | Deterministic host tooling verified; Pocket lookup/Controls behavior pending | `pocket_per_game_preset.py` implements Analogue's documented slot-0 mirrors under `/Presets/agg23.WonderSwan/Interact/...` and `/Presets/agg23.WonderSwan/Input/...`, clones the complete live menu/control definitions, and changes only selected defaults; adversarial tests prove exact nested paths, deterministic bytes, no ROM reads or embedded ROM metadata, all-or-nothing conflict preflight, source-contract drift detection, and traversal/core-ID/symlink rejection; user-local presets remain deliberately excluded from the release core ZIP; current developer pages call Controls read-only and say remapping is coming soon, while firmware 2.4 says beta Dock remapping applies to four controllers, so the generator promises only the documented per-title definition/label/default surface and never fabricates remap state; firmware 2.6.0 Pocket/Dock must still record actual editability, application, reset, relaunch/persistence and per-title scope plus settings precedence, nested/case-varied paths, and updater preservation; see `PER_GAME_PRESETS.md`, Analogue's [`input.json`](https://www.analogue.co/developer/docs/core-definition-files/input-json), and [firmware 2.4](https://www.analogue.co/support/pocket/firmware/2.4) |
| Pocket presentation and buffering | Focused source/simulation verified; Quartus/Pocket pending | full 32-bit PAD typing rejects non-gamepad/stale packets; eleven settings bits cross atomically with JSON-matching defaults; scaler slots 0/270/180 apply only at frame boundaries; buffered frame orientation is captured when the producer completes each bank and direct-mode orientation is latched only at the output-frame boundary, preventing live orientation changes from rotating queued or mid-frame pixels; the related-clock RGB/control bundle is half-cycle staged; a two-frame APF bus bench proves exact 224x144 active output, 258 lines, single-cycle HS/VS, one scaler command per active line, reserved-word zeroing, frame-atomic grayscale, and 59.985 Hz cadence; a separate raster bench proves the complete 397x258 cadence at 6.144 MHz; framebank ownership keeps completed histories immutable and its split 10+2-bit memories target 200 rather than a naïve 240 M10Ks; frame-atomic raw/ares color selection, rounded two-frame blending, and finite 50/25/25 persistence are exact in focused arithmetic simulation; physical latency, realized resource fit, timing closure, Pocket/Dock output, and display modes remain mandatory gates |
| Phase 4 frame delivery | Cadence improved; new low-latency mode researched and rejected pending safety contracts | shortening only the late horizontal blank tail corrects the APF raster from 59.386418 to 59.984769 Hz and reduces forced complete-frame skips by 0.598352/s without claiming lower buffer latency; phase-parameterized metrics cover every 36-cycle reset/event residue. An isolated beam-race candidate would select one-generation-newer pixels on 12,277/13,568 default-timing outputs with a modeled 1.556695 ms minimum write-before-read margin, but live programmable LCD Final Line can legally omit row 143 and the current arbiter can recycle the selected writer. The candidate is therefore regression-tested but explicitly absent from production/QSF; see `FRAME_DELIVERY.md` and `BEAM_RACE_ANALYSIS.md`. |
| Phase 3 screen authenticity | Research-backed options implemented; real-panel calibration open | `SCREEN_AUTHENTICITY.md` follows the brief's source order: current/MiSTer RTL, official Mednafen 1.32.1 source, pinned ares, WSdev, and official APF display-mode docs. Raw RGB444 remains the neutral default; an optional exact ares Color/SwanCrystal matrix and a project-designed three-history approximation of its recursive interframe response are menu-selectable and frame-atomic. The arithmetic bench covers all 4,096 native colors, all 4,096 scalar history triples in every mode, endpoints, primaries, reserved encodings, and constant invariants. No WSC/CSTN or SwanCrystal/TFT response curve was found, so no arbitrary strength or hardware-accuracy claim was added. | Capture controlled color and motion charts from unmodified WSC and SwanCrystal panels, publish lighting/camera/timing methodology and uncertainty, fit separate response parameters only if the data supports them, then verify Pocket/Dock output and latency. |
| V30MZ instruction quirks | Value, flag, exception, and memory-side-effect behavior verified in translated RTL | pinned open `80186_quirks.ws` renders three upstream-authored PASS results for D4/AAM and D5/AAD with base 16 plus D6/SALC; a separate build-generated probe records 24 exact results covering defined AAM flags, full AAD byte-ADD flags, D4 base-zero vector 0/post-IP/AX state, and D6 values with AH plus full before/after PUSHF words preserved and no data-memory access; exact hardware timing remains reference-correlated rather than trace-measured |
| SoC interrupt controller | UART-TX level, vector/status/ACK, and keypad-edge paths verified in translated RTL | pinned open `interrupts.ws` renders all 13 real-hardware-authored PASS results in two byte-identical six-frame runs and remains at its exact terminal loop; a separate build-generated Color probe proves `$B0` F8 alignment, disabled-edge isolation, actual key dispatch through vector `$81`, held/release/repress edge behavior, mask-independent pending retention, ACK, and exact combined-row values through the deterministic `BDVIHRPACZ` marker; UART receive/transmit timing, cartridge IRQ, and exact interrupt latency remain open |
| Simulation CI | Immutable workflow contract; remote run open | checkout is pinned by full SHA; official Verilator 5.050/GCC 13.3.0 and GHDL 6.0.0 images are digest-pinned and version-checked before `make regression`; the Ubuntu runner still supplies platform-managed shell/Make/Python; the current branch has not been pushed to a configured fork, so no remote green run is claimed |
| PNG framebuffer output | Complete | `sim/verilator/rgb_to_png.py` |
| Optional waveform trace | Complete at whole-design VCD level | `--trace FILE.vcd` |
| Structured event trace | V5/v6 runtime verified in Verilator | simulation-gated CPU, bank-register, completion-aligned display word/collision, completed CPU/GDMA/SDMA memory, atomic Screen 1/2 background-cell taps, and conditional atomic sprite-row taps; v5/v6 CSV/JSONL with v1-v6 CSV fixtures; translated open/generated-ROM regression plus focused atomic decode/grouping/writer-snapshot tests pass; `sim/verilator/TRACE.md` |
| Trace-to-frame artifact binding | Opt-in manifest v2 verified | `--trace-frame-artifacts` preserves v5/v6 trace bytes while binding every raw 224×144 RGB888 artifact to its zero-based final-pixel cycle, manifest-relative path, exact 96,768-byte size, and FNV-1a digest; atomic frame publication plus a strict artifact verifier reject mutation, symlink/hardlink/trace aliasing, field/count/index/cycle/path errors, and incomplete bundles while legacy manifest v1 remains unchanged; publication cycles are not claimed as hardware VBlank or blanket pixel causality |
| APF package assembly | Host release gate verified; publisher and final evidence unavailable | `package_validator.py` fail-closes the exact release tree, every shipped APF/platform JSON, official limits and cross-file identities, plus 521x165 platform art and the supplied deterministic 36x36 core-author icon; the original generic swan mark is generated from a reviewable 18x18 grid at Analogue's recommended 2x2 scale, stored in the documented rotated 16-bit monochrome format, and bound by an upright-decode/digest/staleness test; `package_core.py` reverses the supplied RBF, materializes the pinned 411-byte Chip32 loader rebuilt from this fork's extended source with the official assembler, and emits byte-identical ZIP/provenance pairs that hash every payload; release mode enforces metadata-derived naming, requires an explicitly authorized publisher, rejects the two pinned public `agg23.WonderSwan` version/date tuples plus any candidate Semantic Version not strictly newer than public 1.0.1, non-newer dates, and URL/identity drift, and binds the reviewed inventory policy, exact RBF, generated date/time/commit build-ID MIF, Quartus 21.1.1 flow/fit/STA reports, and eleven explicitly accepted timing/warning/compression/hardware gates into the sidecar; 19 focused packaging tests cover deterministic non-release behavior, policy/schema/order/collision failures, mutation/tamper paths, and successful evidence/policy binding; the checked policy remains unauthorized and no real Quartus or Pocket evidence has been accepted |
| Mac SD staging | Read-only by default; focused host tests verified | `stage_pocket_sd.py` validates a development ZIP and provenance against the current checkout, exact user-supplied BIOS sizes, destination identity/case/path/symlink safety, and preserves unrelated SD contents; mutation requires explicit `--apply`, direct `/Volumes` targets additionally require `--allow-volume`, and the tool downloads neither games nor BIOS; physical SD filesystem/eject/power-loss behavior remains outside the host tests; see `POCKET_SD_STAGING.md` |
| Reproducible build identity | Generator verified; full RBF proof open | the APF pre-flow MIF uses a clean source commit, its UTC commit timestamp or explicit `SOURCE_DATE_EPOCH`, and a commit-derived 32-bit identity; focused tests prove identical output across repeats/timezones plus fail-closed dirty, mismatched, malformed, and non-Git inputs; two Quartus builds have not been compared |
| Quartus bitstream | Host workflow provisioned; vendor install/build unrun | native macOS remains unsupported; the pinned Linux/amd64 Docker package layer and preflight pass on Apple Silicon, but a user-supplied official Quartus 21.1.1 archive, installer/device probe, fit/RBF, and flow/STA reports remain open |
| Timing closure | Not tested | requires Quartus build |
| Hardware equivalence | Not tested | requires user-approved Pocket validation |
| Known-title Pocket/Dock compatibility | Catalogue and fail-closed evidence contract complete; every hardware result pending | `KNOWN_TITLE_COMPATIBILITY.md` and `known-title-compatibility.json` bind 12 primary-source commercial issue cases without embedding ROM identities or claiming passes, require tester-computed SHA-256, exact operator input records, same-revision original-hardware references, separate Pocket/Dock results, core/RBF/firmware identities, and hashed evidence; 5 redistributable open/generated sanity fixtures are separate and hash-bound; `known_title_compatibility.py` rejects missing/mutated cases, incomplete evidence, unsafe/tampered/reused artifacts, pending modes under completion, and any failed mode under acceptance; physical execution remains entirely open |

Phase 0 is not complete as a hardware deliverable until Quartus compilation,
timing closure, and on-device Pocket testing are performed.

## Phase 1 — debug instrumentation

This section records Phase 1 groundwork while Phase 0's Quartus, timing, and
authorized Pocket gates remain unavailable. It does not declare Phase 0
deferred or Phase 1 accepted.

| Item | Status | Evidence needed or available |
| --- | --- | --- |
| ROM bank-switch writes | Verified with generated open probe | `make regression` executes distinct byte writes to C0-C3 plus a word write spanning C0-C1, and requires their exact accepted sequence, nonzero instruction IDs, and origin PCs (`0xf0003`, `0xf0007`, `0xf000b`, `0xf000f`, `0xf0014`); both bytes of the word write share one instruction identity; no probe binary is checked in |
| Deterministic controller replay | Verified through translated keypad and key-IRQ RTL | strict full-state scripts address physical `x1`-`x4`, `y1`-`y4`, Start/A/B at exact reset-relative system cycles; the mono routing probe proves X2 press/release through port B5 with no-input isolation and exact `INP`, while the Color interrupt probe proves exact combined X2+Y1 `B5=0x33`, released `B5=0x30`, key-edge IRQ isolation/dispatch/retention/ACK, exact `BDVIHRPACZ`, paired byte identity, raw+normalized manifest binding, and adversarial mutation rejection; user-owned title routing remains private and target-specific |
| VRAM/character fetch addresses | Raw and atomic runtime paths verified | open-ROM regression requires all six Screen 1/2 map/tile and sprite table/tile roles with aligned completion data and collision status; v5 binds a promoted background map word to decoded tile attributes and its contributing row, while conditional v6 binds a cached sprite descriptor and contributing row to its accepted line-buffer slot; the open Shift-JIS fixture binds six licensed Misaki characters to exact ROM offsets, GDMA tile writers, CPU map writers, 96 promoted rows, and final pixels; paired generated probes bind 4bpp planar/packed rows and all flip modes through exact ROM sources to identical final pixels; title-specific glyph provenance remains open |
| CPU PC ranges | Verified with running ROMs | regression checks `CS:IP` against wrapped physical PC and disjoint range-union containment; Wonderful execution terminates at the expected `0xff68b` loop |
| Memory provenance | All eight trace-space labels runtime verified with generated open probes | paired complete-from-reset traces require 36,817 memory plus five bank events each and exact `iram`, `cart_sram`/`absent_sram`, `cart_rom0`, `cart_rom1`, `cart_rom_linear`, `boot_rom`, and mono `unmapped` behavior; checks bind ROM/boot inputs, values, masks, offsets, CPU origins, ROM aliases, and the separate GDMA chains |
| ROM input capacity | Power-of-two path retained; compact 896 KiB path focused-tested; Pocket proof open | slot 0 accepts whole-64-KiB-bank images from 64 KiB through the implemented 16 MiB 24-bit-mapper cap. Power-of-two files keep the legacy direct route. Non-power-of-two files require a valid final 16-byte WonderSwan footer/checksum, receive an `0xff` lower prefix, and are right-aligned in the next-power-of-two aperture, matching [WSdev's documented compact-ROM convention](https://ws.nesdev.org/wiki/ROM_header) and [Mesen2's loader behavior](https://github.com/SourMesen/Mesen2/blob/master/Core/WS/WsConsole.cpp). An original generated 896 KiB fixture and footer/size/checksum mutations pass host, translated-core, and RTL mapping tests, including a continuously held raw stream, prefix completion before EOF, reset-hold continuity, and invalid-to-valid reload recovery. Terminal ready/fail crosses back to Chip32 at PMP `0x14`; malformed data prints a specific error and a 1,048,576-poll instruction guard covers only validation/status CDC stuck-pending logic. That guard is not a wall-clock claim because Analogue publishes no VM rate/limit and firmware beta 5 added a crash cycle limit, so visible timeout behavior still requires Pocket fault-injection/calibration. The exact two-bit synchronizer and PMP mux are mutation-locked, but compiled full-wrapper and Pocket observations remain mandatory. WSdev's header table documents known encodings through 16 MiB, while the [later Bandai 2003 mapper](https://ws.nesdev.org/wiki/Mapper) implies a theoretical 64 MiB capacity that is not implemented or advertised here |
| SRAM header types `0x01`/`0x02` | Corrected to 32 KiB and runtime verified | WSdev revision 680, pinned Mesen, and pinned ares all map both values to 32 KiB; paired generated ROMs produce byte-identical seven-event traces in which offsets `0x0000`, `0x2000`, and `0x7fff` remain distinct and `0x8000` mirrors `0x0000`; focused contracts lock the same 32,768-byte size in the mapper, save-state payload, Pocket 64×512-byte block count, and dynamic APF Save slot; a mutation-tested, non-destructive converter migrates exact legacy 8,204-byte Pocket saves before loading |
| Internal EEPROM protocol | Open fixture plus persistence-focused RTL tests pass; physical power-cycle open | pinned Wonderful mono fixture produces byte-identical paired traces, 184 complete PASS rows, terminal PC `0xff620`, and exact target pixels; focused GHDL covers separate write/read latches, single read/write/erase, EWDS/EWEN, WRAL/ERAL, protected versus user words, invalid controls, DONE/READY, saved-EWDS restoration, and word retention across ordinary reset; the Pocket wrapper keeps Color and mono simultaneously resident in separate banks, runs the deterministic factory pass only for cold/title initialization, overlays fixed-name `mono.eeprom`/`color.eeprom` before execution, and never aliases cartridge EEPROM; the ten-enable READ delay is a deterministic functional model and does not establish physical latency, Color-hardware mono mode, or Pocket power-cycle persistence |
| Pocket nonvolatile sizing and RTC boundary | Integrated source contract and focused RTL/CDC verified; compiled wrapper/Pocket flush open | cartridge slot 11 remains dynamic and capped at 524,300 bytes; SRAM types `01/02`/`03`/`04`/`05` use 32/128/256/512 KiB and cartridge EEPROM `10`/`20`/`50` uses 128/2,048/1,024 bytes, with a conditional exact 12-byte RTC trailer; fixed core-specific console slots 12/13 independently publish table indices 4/5 as exact 128/2,048-byte `mono.eeprom`/`color.eeprom` images after `008F`; the guard returns `2` until dynamic metadata is ready, accepts only exact console-slot writes and shutdown reads, and rejects malformed lengths/directions with `1`; title changes use slot 0's full restart, which APF documents as unloading all nonvolatile slots first, while ordinary reset does not re-arm factory clearing; exact-capacity initialization, loaded-save preservation, offline conversion, and padded-cartridge-EEPROM canonical writeback are focused-tested, and a wrapper/model bench now drives factory seed, persisted-slot overlay, both clocks of the real dual-bank EEPROM backing, exact 128/2,048-byte unload comparison, model selection, and ordinary-reset retention; static backing generates keep external cartridge EEPROM bankless at 1,024×16 while only internal console EEPROM uses 2,048×16, with both elaboration paths focused-tested; compiled full-wrapper unload and physical Pocket quit/relaunch/model-switch/title-switch/power-off flushing remain open, and Memories/Sleep remain disabled |
| CPU ROM-to-IRAM provenance | Strictly verified for the trace-observed bootstrap `REP MOVSB` copies | conservative classification requires an `F3 A4` origin signature plus an immediate exact same-instruction ROM-read/IRAM-byte-write pair; a dedicated verifier binds the canonical open ROM, complete v5 manifest, uninterrupted alternating chains, ranges, lanes, and all 4,096 byte values; bootstrap yields two 2,048-byte chains, ROM `0x00252..0x00a51` to IRAM `0x2800..0x2fff` and ROM `0x00a52..0x01251` to IRAM `0x2000..0x27ff`, totaling two origins, 52,512 display words, and 26,222 atomic cells whose contributing tile-row bytes are MOVSB-sourced; extended-range and Shift-JIS fixtures are zero for all four counts, and `unattributed` alone is not treated as proven prefetch |
| Sound-DMA modes, provenance, and save-state continuation | Functional subset and legal save boundaries verified in translated RTL | the original `sdma` capture locks four one-shot linear-ROM reads and fastest-rate cadence; a second self-checking WSC probe locks 21 selected reads plus `PONSREATDHUZ` across live/shadow, pause/resume, repeat, decrement, zero-length, and held-zero behavior; the pinned open hardware fixture runs twice with byte-identical 346-read traces, all 22 PASS markers, terminal PC `0xff63a`, and exact final pixels, covering 20-bit register masks, specific ROM/IRAM reads, hold, terminal counters/control, and 20-bit wrap; its two source-labeled SRAM phases resolve to 43 IRAM rows and zero actual SRAM rows, so they prove no SRAM or wait-state behavior; direct entity tests cover pending/issued arbitration and versioned slot-18 continuation with legacy/malformed fallback; raw `byte_enable=3`, held reads, and fixture cadence are translated-core observations, not sample-width or physical timing claims |
| Boot-ROM overlay and lockout | Runtime verified for mono and Color models | generated 4 KiB/8 KiB open test images execute from byte zero, read exact markers at `0xff100`/`0xfe100`, write A0 lockout, then require physical addresses `0xffff0..0xffffe` to change from mono boot offsets `0xff0..0xffe` or Color offsets `0x1ff0..0x1ffe` to cartridge offsets `0x1fff0..0x1fffe`; no proprietary firmware is used |
| Display-to-writer correlation | Verified on open regression | complete-from-reset manifest plus byte-lane IRAM scoreboard matches all 78,940 physical fetches: 78,750 exact CPU writers, 190 defined power-up prefetches, zero mismatches/collisions; `correlate_provenance.py` |
| Atomic background-cell correlation | Verified on open regression | `correlate_bg_cells.py` independently groups Screen 1/2 map/tile reads, validates 2bpp selected-word and 4bpp two-word rows, and snapshots byte writers/GDMA sources at the raw-fetch edge; regression validates 26,224 bootstrap cells, 5,176 extended-range Color cells, 8,307 Shift-JIS fixture cells, and 8,493 cells in each generated 4bpp format, with no atomic mismatch/collision |
| Atomic sprite-row correlation | Verified in translated RTL on open/generated probes | `correlate_sprite_rows.py` independently binds each promotion to its exact latched raw OAM generation, line-load epoch, exact two-read tile group, and fetch-time byte writers/sources; it locks the one-cycle admission edge and contiguous per-epoch slots, including focused slot-31, interleaved-DMA, repeated-line, and identical-refresh mutations; the open extended-range fixture covers 32 planar 2bpp rows and separates 32 noncontributing second reads, while the generated Color-priority probe covers 48 packed 4bpp rows sourced through GDMA; this stops at line-buffer admission, before X/window/transparency/priority/composition |
| Color 4bpp format equivalence | Verified in translated RTL | repository-authored, build-generated, non-checked-in probes select planar `0xc0` and packed `0xe0`, copy distinct 32-byte tile payloads by exact GDMA chains, display normal/H/V/HV placements, and require 64 provenance-complete diagnostic rows plus identical reporter fingerprints and final RGB across both encodings |
| Open Japanese text workload | Verified in Verilator | native Wonderful-built fixture parses `日本語かな漢`; a dedicated verifier binds licensed Misaki Unicode/Shift-JIS rows to exact ROM/GDMA/tile/map/cell provenance and pixel-perfect output; `testroms/swan-song/sjis_glyph_provenance/README.md` |
| Wonderful medium-SRAM homebrew runtime | Verified in Verilator; Pocket hardware open | a current open `wswan/medium-sram` Color build binds the CRT's DS=`1000h` `.bss` clear and `.data` copy, ordered `5aa5/0000 -> a55a/c33c` cartridge-SRAM accesses, far jump into `main`, far ROM strings, exact `MEDIUM-SRAM OK` map cells, terminal HLT, and final raster; the probe also establishes that the 32 KiB target's SP=`8000h` requires Color IRAM and that CRT-managed SRAM sections must not overlap persistent records; `HOMEBREW_WONDERWITCH.md` |
| Glyph candidate report | Verified on open Japanese fixture | `report_glyphs.py` emits a deterministic, title-agnostic epoch CSV and labeled contact PNG across 2bpp/4bpp planar/packed formats and both flips; regression preserves all 592 fixture epochs while the compact unique-exact view surfaces seven bitmaps and binds the six ROM-sourced glyph candidates to their exact fingerprints, map slots, writers, IRAM spans, and source offsets; it never infers character identity |
| Trace-filter config | Verified with v5/v6 CPU/GDMA/SDMA/display runtime | parser/serializer unit tests plus translated-model event selection, PC/address/offset containment, all three memory initiator filters, memory access/space/origin filters, all six display roles, conditional sprite-row schema, and legacy stability; `trace.example.conf`, v1-v6 CSV, and JSONL are documented |
| Translation-target acceptance | Not tested | no trace of the target 2001 WSC title has been captured or correlated with its kanji/glyph mapping |

The general Phase 1 v5/v6 instrumentation is working end to end in the translated
model. Phase acceptance remains open because it specifically requires a useful text-renderer trace
from the target 2001 WSC title and correlation with that title's kanji/glyph
mapping. No commercial ROM is included or acquired by this project.

### Research-backed provenance step

Role and address identify which map/tile word the display requested. V3 adds
the filtered memory-transaction bridge: initiator, read/write, value,
write/DMA byte enable, exact CPU instruction identity/origin where provable, mapped
memory space, and resolved ROM/SRAM byte offset. This direction matches [Mesen's WonderSwan
memory-operation debugger](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/Debugger/WsDebugger.cpp#L149-L230)
and an open translation project's [far-pointer/charmap
workflow](https://github.com/JohnTsq/WS_Cardcaptor_Sakura_chs/blob/52c7d2b89865874cb2d6b538359f3ac76570471a/tools/TransMsg/TransMsg.c).
V4 proves the transport chain through the exact display word and writer present
on its fetch edge. V5 adds a narrower logical boundary for backgrounds: the map
word and decoded, contributing 2bpp/4bpp tile row promoted into the pixel
shifter, with writers frozen at their earlier raw-fetch edges. It does not claim
that a promoted cell survives windowing, transparency, layer/sprite priority,
or clipping, and a tile index is not automatically a character code. V6 adds
the analogous descriptor/row-to-line-slot boundary for sprites without
claiming X visibility, window/transparency, priority, palette RGB, or final
pixel survival. Phase 1
acceptance still needs
the user-owned target title trace and correlation of those transactions with
its specific glyph table and visible text.

The generated mapper probes prove the current resolver and observer, not every
underlying hardware behavior. In particular, this RTL returns zero for absent
SRAM, while pinned [ares returns cartridge open
bus](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cartridge/memory.cpp#L25-L38)
and pinned Mesen leaves its fallback behavior as an open-bus TODO. The probe
therefore locks the observed core value without calling it hardware-correct.
CPU reads use `byte_enable=0` as an observer convention because the functional
CPU only drives byte enables for writes; the field must not be read as CPU
operand width. The integrated top keeps the DMA engine's hardware path enabled
inside the translated model. The original generated probe proves four one-shot
SDMA byte steps, exact linear-ROM provenance, and the translated fastest-rate
cadence. A second self-checking probe proves the selected functional modes
above through every admitted `sdma` memory event and bank success marker in two
byte-identical captures. The pinned open [ws-test-suite fixture](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/color/dma/sound_dma/main.c)
adds 346 exact functional reads, all 22 source-defined PASS results, a stable
terminal loop, and exact final pixels in two deterministic runs. Its Wonderful
build places `sample_data_sram` in segment zero: 43 reads from the two
SRAM-labeled phases are therefore required to resolve to IRAM `0x0059..0x0068`,
and the fixture explicitly reports zero cartridge-SRAM rows. [WSdev revision
562 documents SDMA as byte-oriented](https://ws.nesdev.org/w/index.php?title=DMA&oldid=562),
but the inherited shared DMA bus still drives raw `byte_enable=3`; the trace
records that signal without interpreting it as sample width. The fixture's
header value `0x01` now maps to the corrected 32 KiB save size, but its
segment-zero placement means it still contributes no physical SRAM coverage.

The functional probe covers selected Channel 2 behavior, not full physical
Sound-DMA fidelity. Pinned [Mesen](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsDmaController.cpp#L46-L92)
performs a held memory read and substitutes zero, while pinned
[ares](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/apu/dma.cpp#L1-L33)
skips the held read; the exact held `0xf1070` rows therefore lock only the
current Mesen-aligned translated policy. Mesen's [control-write path](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsDmaController.cpp#L171-L192)
rejects every enable request at zero live length and attributes that choice to
`sound_dma + WSHSTest`, whereas pinned ares [assigns enable directly](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/apu/io.cpp#L160-L181).
The repository implements and tests the Mesen/WSdev-consistent rule without
claiming emulator consensus or importing those hardware tests. Physical
`117 mod 128` phase, `6+N` bus-steal cost, slower rates and slow-source
extension, wider active-byte edits, arbitrary mappings beyond the fixture's
specific IRAM/ROM/wrap cases, Hyper Voice routing, and hardware timing remain
open. Save-state continuation now follows
pinned [Mesen2's serialization](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsDmaController.cpp#L196-L213)
of live/reload counters, control, frequency, and timer plus [ares'
serialization](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/apu/serialization.cpp#L32-L44)
of programmed/live counters and its DMA clock, with FPGA-specific queued and
pre-bus state added for the shared bus FSM. Existing
slot 17 remains byte-for-byte unchanged and the previously unused, zero slot
18 carries reload length `[19:0]`, reload source `[39:20]`, the 10-bit timer
phase `[49:40]`, queued request `[50]`, fixed FSM code `[53:51]`, zero reserved
bits `[59:54]`, version `001` `[62:60]`, and valid bit `[63]`; the save image
size does not change. An all-zero legacy slot, or a header invalidated by its
valid/version/reserved fields, derives both reload counters from slot 17's live
counters and resumes with timer zero, request clear, and IDLE. A valid header
with an illegal FSM code retains its reload/timer payload but sanitizes the
FSM to IDLE with no request. The direct save/load bench proves the wire layout,
timer phase, divergent live/reload repeat, pending IDLE, enabled and disabled
pre-bus single-read continuation, legacy collapse, invalid-header fallback,
and illegal-state fail-safe behavior. This is exact continuation at the legal
save-handshake boundaries, not evidence for the open physical timing,
Hyper Voice, arbitrary source mappings, or Pocket-hardware cases.

## Phase 6 — homebrew and WonderWitch

Ordinary Wonderful cartridge homebrew now has a current, deterministic open
regression beyond the older pinned `initfini` result. The
`wswan/medium-sram` Color fixture proves current CRT `.data`/`.bss`
initialization in cartridge SRAM, medium-model far code, far ROM data, current
console libraries, exact SRAM mutation/readback, success cells, final pixels,
and terminal HLT. This is translated-RTL evidence only; Pocket hardware and
save persistence still require validation. Full build advice and the discovered
32 KiB Color-stack/persistent-region constraints are in
[`HOMEBREW_WONDERWITCH.md`](HOMEBREW_WONDERWITCH.md).

The current Wonderful `wwitch` target emits traditional `.fx` applications and
can now assemble them with a pinned clean-room AthenaOS into an ordinary `.ws`
using `wf-wwitchtool mkrom`. A source-only Swan Song fixture produces
byte-identical `.fx`/`.ws` outputs after normalizing the otherwise wall-clock
Freya mtime. In translated RTL, the 256 KiB read-only image boots AthenaBIOS,
starts AthenaOS, locates and launches the `rom0` executable, reaches its dynamic
CRT and `main`, executes BIOS text/input services, renders `Hello, World!`, and
settles in `key_wait`. Exact package/firmware/artifact hashes, ordered CPU PCs,
33,602 background-cell events, five frame hashes, and the 238-pixel glyph
raster are bound by [`WONDERWITCH_VALIDATION.md`](WONDERWITCH_VALIDATION.md)
and its opt-in validator. No firmware or composite ROM is checked in.

This is a narrow read-only `mkrom` compatibility result, not a complete
WonderWitch claim. The exact Bandai 2003 selector now implements `CEh` bit 0
and routes the byte-wide `10000h-1ffffh` window through the selected flash/ROM
bank in volatile SDRAM; black-box VHDL covers reset, readback, masks, even/odd
lanes, SRAM fallback, and ordinary ROM write protection. The new `cart_flash`
trace label keeps those events distinct from cartridge SRAM. MBM29DL400TC
unlock/program/erase semantics and APF persistence are still absent, so direct
APF `.fx` selection, a writable Freya/Athena filesystem, high mapper bytes
beyond the current 16 MiB APF path, serial/XMODEM, Quartus fit, and Pocket/Dock
execution remain open. The ordinary regression mutation-binds the source; the
external Wonderful/Athena dependency is exercised by
`scripts/validate_wonderwitch_athena.sh`.

## Baseline corrections discovered

The attached brief's limitation list predates the pinned Pocket release. The
baseline contains APF Memories/sleep-wake controller logic, RTC logic, native
vertical input-matrix selection, triple buffering, and two/three-frame flicker blending. The
last of those is now exposed as source-qualified LCD-response choices rather
than being presented as a measured panel model.
Memories/sleep is now deliberately reported unsupported until its end-to-end
and physical Pocket gates pass; the other inherited implementations must be
evaluated and improved rather than treated as absent.

The provenance audit also exposed and fixed a console-logic error: mono writes
above the documented 16 KiB IRAM range were classified unmapped but still
enabled the hidden 64 KiB backing RAM. The mono-unmapped branch now suppresses
that write enable; the open golden-frame regressions remain unchanged.

The open WSC extended-range fixture exposed a second console-logic error:
`SPR_BASE` bit 5 was incorrectly restricted to 4bpp, aliasing a 2bpp Color
sprite table at `0x5600` down to `0x1600`. The corrected Color-mode decode now
renders PASS and traces the exact extended table words, matching WSdev, ares,
and Mesen behavior.

The generated Color sprite-priority probe exposed a third console-logic error:
the Color mixer lacked the grayscale path's high-priority fallback. An earlier
low-priority sprite hidden by opaque Screen 2 therefore suppressed a later
high-priority sprite. The corrected ladder renders four exact blue/green/green/
red control panels and binds both OAM snapshots, all sprite-tile reads, the
ROM-to-IRAM GDMA chain, CPU setup writes, and the stable final frame. This is
verified in translated RTL only; it is not an on-device claim.

The open Wonderful CPU fixture exposed a fourth console-logic error: D4/AAM
and D5/AAD ignored their immediate base, while D6 incorrectly followed the D7
XLAT memory path. The shared V30MZ RTL now consumes the unsigned D4/D5 base,
raises vector 0 for D4 base zero after fetching the immediate, and implements
the eight-clock D6/SALC value behavior without a data-memory read. Defined
AAM flags derive from the result low byte; AAD uses the full low-byte ADD flag
model on which pinned ares and Mesen agree. The open upstream-authored ROM
proves the three value results in translated RTL. A generated, self-contained
probe now verifies the flag, exception-return, and no-data-memory contracts
through 24 exact IRAM records plus complete CPU/memory history. The eight-clock
SALC setting remains reference-correlated: prefetch-buffer credit makes the
observer's end-to-end completion delta unsuitable as an isolated hardware
timing measurement.

The pinned open interrupt fixture exposed a fifth console-logic error cluster.
The inherited controller sourced only display/timer interrupts, cleared pending
bits when their enables were written, returned the raw and model-mismasked B0
base, and acknowledged only a subset of sources. The corrected path aligns the
base to eight vectors on every model, returns the highest pending status index,
retains status across mask changes, acknowledges all eight bits, and connects
the enabled-and-ready UART-TX level source. The keypad now wired-ORs every
selected matrix row and raises a CE-safe interrupt only on selected-input rising
edges. This matches pinned [WSdev interrupt revision 553](https://ws.nesdev.org/w/index.php?title=Interrupts&oldid=553),
[WSdev UART behavior](https://ws.nesdev.org/wiki/UART), pinned ares
[interrupt](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cpu/interrupt.cpp#L1-L27)
and [keypad](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cpu/keypad.cpp#L1-L57)
models, and pinned Mesen's
[controller](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsMemoryManager.cpp)
behavior. The upstream
[hardware-authored fixture](https://github.com/asiekierka/ws-test-suite/blob/7dfa0e2e869d08386b685d6a56df0bcfaf181b47/src/mono/soc/interrupts/main.c)
proves its eight UART-TX and five vector/status assertions through exact final
pixels. The generated Color/input probe additionally proves the actual vector
81h handler path, disabled and held-key isolation, release/repress, retained
pending status, full ACK, and simultaneous-row readback. The UART remains a
ready-only stub: receive, transmitted-byte timing, cartridge IRQ, and precise
interrupt latency are not established by this milestone.

The Sound-DMA audit exposed a sixth console-logic error cluster. The inherited
start path reloaded the working counters and reset its divider, visible
source/length writes changed only hidden register copies, hold still advanced
the counters and forwarded memory data, and a queued request could survive a
stop while the shared FSM was serving GDMA. The corrected path updates live and
repeat-shadow bytes together, preserves live counters and timer phase across
ordinary stop/resume, rejects requested enable at zero live length, freezes
held counters while writing zero to Channel 2, supports repeat/decrement, and
cancels every unissued request while allowing one already-issued transaction
to finish. The paired generated probe verifies the functional subset in the
translated top; a direct GHDL entity test forces the pending/GDMA and issued
transaction boundaries and fails against the pre-fix RTL. The held bus read is
an explicit translated policy because the pinned emulators disagree, and the
timing, Hyper Voice, source-space/wrap, and hardware limits above still apply.
The save-state extension now preserves repeat shadows, timer phase, queued
request, and the only legal in-flight pre-bus FSM point while keeping old
slot-17 images compatible; its direct entity bench covers exact restore and
legacy/malformed fail-safe behavior without claiming arbitrary mid-transaction
or on-device equivalence.

The ROM-header audit exposed a seventh console-logic error: save type `0x01`
was masked and advertised as 8 KiB even though pinned [WSdev revision
680](https://ws.nesdev.org/w/index.php?title=ROM_header&oldid=680), [Mesen2](https://github.com/SourMesen/Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2/Core/WS/WsConsole.cpp#L58-L65),
and [ares](https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/mia/medium/wonderswan.cpp#L85-L95)
all map both `0x01` and `0x02` to 32 KiB. The mapper mask, save-state payload,
Pocket block count, and APF dynamic-size contract now agree. Paired generated
ROMs prove the corrected address distinctions and type equivalence in fresh
translated-RTL traces. This changes Pocket files from 8,204 bytes (8 KiB plus
the 12-byte RTC trailer) to 32,780 bytes. The mutation-tested
`scripts/migrate_type01_save.py` requires a valid type-01 ROM and exact legacy
length, preserves the old SRAM prefix, zero-fills the new suffix, relocates the
opaque RTC trailer, publishes only to a new path, and leaves both inputs
unchanged. Data already lost through the old 8 KiB alias cannot be
reconstructed.

The boot-overlay probe exposed a simulator initialization error: the model had
not observed its initial low clock level before the first BIOS-programming
cycle, so bytes 0/1 of a supplied boot image were skipped. The harness now
evaluates the initialized low clocks once, and both generated boot images must
execute successfully from byte zero. The mapper probe also exposed stale CPU
write-lane state on later read trace events; v5 now emits a deliberate zero
mask for CPU reads while retaining real masks for writes and DMA transfers.
